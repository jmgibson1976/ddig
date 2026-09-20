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
from pathlib import Path
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
SOURCE             = "dropcatch"

_PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR      = _PROJECT_ROOT / "data" / "dropcatch"

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
            dt = datetime.strptime(value.strip(), fmt)
            return dt.replace(tzinfo=timezone.utc)    # always attach UTC
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
        DATA_DIR.mkdir(parents=True, exist_ok=True)

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

    def _local_path(self) -> Path:
        """Return the expected cache path for today's CSV for this feed."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return DATA_DIR / f"dropcatch_{self.feed}_{today}.csv"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _download(self) -> str:
        """
        Return CSV text for today's feed.

        If today's cached file exists, reads from disk and skips the network.
        Otherwise: step 1 — get signed S3 URL, step 2 — download and unzip,
        save to cache, return text.
        """
        path = self._local_path()
        if path.exists():
            log.info("DropCatch: using cached file %s", path.name)
            return path.read_text(encoding="utf-8", errors="replace")

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
                csv_name = next((n for n in names if n.endswith(".csv")), names[0])
                log.info("Extracting %r from zip", csv_name)
                text = zf.read(csv_name).decode("utf-8", errors="replace")

        except zipfile.BadZipFile:
            text = response.text.strip()
            log.debug("Not a zip file, trying plain text. Preview: %r", text[:200])
            if text.startswith("<!") or text.lower().startswith("<html"):
                raise ValueError(f"DropCatch returned HTML. Preview:\n{text[:300]}")

        path.write_text(text, encoding="utf-8")
        log.info("DropCatch: saved %s (%d bytes)", path.name, path.stat().st_size)
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
            try:
                # Normalize keys — strip whitespace from header names
                row = {k.strip().lower(): v for k, v in row.items()}

                raw_domain = (row.get("domain") or "").strip().lower()
                raw_tld    = (row.get("tld")    or "").strip().lower().lstrip(".")

                if not raw_domain:
                    skipped += 1
                    continue

                ext = tldextract.extract(raw_domain)

                domain_name = ext.domain or raw_domain
                tld_clean   = (ext.suffix or raw_tld).lstrip(".")
                fqdn        = f"{domain_name}.{tld_clean}" if tld_clean else domain_name

                if not domain_name or not tld_clean:
                    skipped += 1
                    continue

                yield Domain(
                    name       = domain_name,
                    tld        = tld_clean,
                    fqdn       = fqdn,
                    source     = SOURCE,
                    drop_date  = _parse_date(row.get("drop date")),
                    fetched_at = datetime.now(timezone.utc),
                )
                yielded += 1

            except Exception as exc:
                log.warning("Error processing row: %s", exc)
                skipped += 1

        log.info(
            "DropCatch '%s': yielded %d domains, skipped %d rows",
            self.feed, yielded, skipped,
        )