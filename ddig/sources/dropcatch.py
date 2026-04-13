"""
DropCatch.com CSV source.

Downloads page: https://www.dropcatch.com/downloads

Real flow (discovered via DevTools):
  1. GET https://client.dropcatch.com/GetFileUrl?FileType=csv&RequestType=<type>&BackorderDay=<day>
     → returns a signed S3 URL
  2. GET that S3 URL → downloads a .csv.zip
  3. Unzip → parse CSV
"""
from __future__ import annotations

import csv
import io
import logging
import zipfile
from datetime import datetime, timezone
from typing import Iterator
from urllib.parse import urlencode

import requests
import tldextract
from tenacity import retry, stop_after_attempt, wait_exponential

from ..models.domain import Domain
from .base import DomainSource

log = logging.getLogger(__name__)

DROPCATCH_API_BASE = "https://client.dropcatch.com/GetFileUrl"
DROPCATCH_REFERER  = "https://www.dropcatch.com/downloads"

# RequestType values observed in network traffic
# BackorderDay is only used for Dropping requests
REQUEST_TYPES: dict[str, dict] = {
    # --- Auctions ---
    "all-auctions":    {"RequestType": "Auction",        "BackorderDay": None},
    "drop-auctions":   {"RequestType": "DropAuction",    "BackorderDay": None},
    "private-sellers": {"RequestType": "PrivateSeller",  "BackorderDay": None},
    "pre-release":     {"RequestType": "PreRelease",     "BackorderDay": None},
    # --- Backorders ---
    "all-backorders":    {"RequestType": "Backorder",    "BackorderDay": None},
    "dropping-today":    {"RequestType": "Dropping",     "BackorderDay": "DaysOut0"},
    "dropping-tomorrow": {"RequestType": "Dropping",     "BackorderDay": "DaysOut1"},
    "dropping-2":        {"RequestType": "Dropping",     "BackorderDay": "DaysOut2"},
    "dropping-3":        {"RequestType": "Dropping",     "BackorderDay": "DaysOut3"},
    "dropping-4":        {"RequestType": "Dropping",     "BackorderDay": "DaysOut4"},
}

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%m/%d/%y",
)


def _parse_date(value: str | None) -> datetime | None:
    if not value or not value.strip():
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    log.debug("Could not parse date: %r", value)
    return None


class DropCatchSource(DomainSource):
    """
    Fetches domain lists from DropCatch.com.

    Available feeds
    ---------------
    Auctions:   all-auctions | drop-auctions | private-sellers | pre-release
    Backorders: all-backorders | dropping-today | dropping-tomorrow |
                dropping-2 | dropping-3 | dropping-4

    Usage::

        source = DropCatchSource(feed="dropping-today")
        for domain in source.fetch():
            print(domain)
    """

    name = "dropcatch"

    def __init__(
        self,
        feed: str = "dropping-today",
        file_type: str = "csv",
        timeout: int = 60,
    ) -> None:
        if feed not in REQUEST_TYPES:
            raise ValueError(
                f"feed must be one of:\n  {list(REQUEST_TYPES)}\nGot: {feed!r}"
            )
        self.feed      = feed
        self.file_type = file_type
        self.timeout   = timeout
        self._config   = REQUEST_TYPES[feed]

        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept":          "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer":         DROPCATCH_REFERER,
            "Origin":          "https://www.dropcatch.com",
        })

    def is_available(self) -> bool:
        try:
            r = self._session.head(DROPCATCH_REFERER, timeout=5)
            return r.status_code < 400
        except requests.RequestException as exc:
            log.warning("DropCatch availability check failed: %s", exc)
            return False

    def _get_signed_url(self) -> str:
        """
        Step 1 — call the API to get a signed S3 download URL.
        e.g. GET /GetFileUrl?FileType=csv&RequestType=Dropping&BackorderDay=DaysOut0
        Returns JSON: {"result": {"fileUrl": "https://...", "fileName": "..."}}
        """
        params: dict[str, str] = {
            "FileType":    self.file_type,
            "RequestType": self._config["RequestType"],
        }
        if self._config["BackorderDay"] is not None:
            params["BackorderDay"] = self._config["BackorderDay"]

        url = f"{DROPCATCH_API_BASE}?{urlencode(params)}"
        log.info("Requesting signed URL: %s", url)

        response = self._session.get(url, timeout=self.timeout)
        response.raise_for_status()

        log.debug("GetFileUrl response: %r", response.text[:300])

        # Response is JSON: {"result": {"fileUrl": "https://...", "fileName": "..."}}
        try:
            data = response.json()
            signed_url = data["result"]["fileUrl"]
            file_name  = data["result"].get("fileName", "unknown")
            log.info("Received signed URL for file: %s", file_name)
        except (ValueError, KeyError) as exc:
            raise ValueError(
                f"Unexpected GetFileUrl response:\n{response.text[:300]}"
            ) from exc

        if not signed_url.startswith("http"):
            raise ValueError(f"fileUrl does not look like a URL: {signed_url!r}")

        log.debug("Signed S3 URL: %r", signed_url[:120])
        return signed_url

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _download(self) -> str:
        """Step 1 + 2: get signed URL then download and unzip the CSV."""
        signed_url = self._get_signed_url()

        log.info("Downloading CSV zip from S3…")
        response = self._session.get(signed_url, timeout=self.timeout)
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "")
        log.debug("S3 Content-Type: %s  size: %d bytes", content_type, len(response.content))

        # Unzip in-memory
        try:
            with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
                names = zf.namelist()
                log.debug("Zip contents: %s", names)

                # Pick the first CSV file inside the zip
                csv_name = next((n for n in names if n.endswith(".csv")), names[0])
                log.info("Extracting %r from zip", csv_name)
                return zf.read(csv_name).decode("utf-8", errors="replace")

        except zipfile.BadZipFile:
            # Some feeds may return plain CSV (not zipped) — try that
            text = response.text.strip()
            log.debug("Not a zip file, trying plain text. Preview: %r", text[:200])
            if text.startswith("<!") or text.lower().startswith("<html"):
                raise ValueError(f"DropCatch returned HTML. Preview:\n{text[:300]}")
            return text

    def fetch(self) -> Iterator[Domain]:
        """Download the CSV and yield :class:`Domain` objects."""
        raw_text = self._download()

        reader = csv.DictReader(io.StringIO(raw_text))

        if reader.fieldnames is None:
            log.warning("DropCatch CSV had no headers — skipping")
            return

        normalized_headers = [f.strip().lower() if f else "" for f in reader.fieldnames]
        log.info("DropCatch CSV columns: %s", normalized_headers)

        yielded = 0
        skipped = 0

        for row in reader:
            norm = {
                (k.strip().lower() if k else ""): (v.strip() if v else "")
                for k, v in row.items()
                if k is not None
            }

            fqdn = (
                norm.get("domainname")
                or norm.get("domain_name")
                or norm.get("domain")
                or norm.get("name")
                or ""
            ).lower()

            if not fqdn:
                skipped += 1
                continue

            ext = tldextract.extract(fqdn)
            if not ext.domain or not ext.suffix:
                skipped += 1
                continue

            expiry_raw = (
                norm.get("expirydate")
                or norm.get("expiry_date")
                or norm.get("expiry")
                or norm.get("expiration")
                or norm.get("expiredate")
            )
            drop_raw = (
                norm.get("dropdate")
                or norm.get("drop_date")
                or norm.get("drop")
                or norm.get("deletedate")
            )

            yield Domain(
                name        = ext.domain,
                tld         = ext.suffix,
                fqdn        = fqdn,
                expiry_date = _parse_date(expiry_raw),
                drop_date   = _parse_date(drop_raw),
                source      = self.name,
                fetched_at  = datetime.now(timezone.utc),
                registrar   = norm.get("registrar"),
                raw         = dict(row),
            )
            yielded += 1

        log.info(
            "DropCatch '%s': yielded %d domains, skipped %d rows",
            self.feed, yielded, skipped,
        )