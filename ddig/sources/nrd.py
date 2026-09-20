"""
NRD (Newly Registered Domains) source.

Fetches lists of recently registered domain names from two free feeds:

    cenk/nrd (GitHub)
        https://raw.githubusercontent.com/cenk/nrd/master/nrd-last-10-days.txt
        Only one file exists — covers the last 10 days.

    WhoisDS
        https://whoisds.com//whois-database/newly-registered-domains/<base64-date>/nrd
        Date is base64-encoded as YYYY-MM-DD.zip (with .zip suffix, no newline).
        Files are available ~4 days in arrears. Tries today and all 10 days back,
        collecting ALL available dates. Files are cached locally — if
        *nrd_whoisds_YYYY-MM-DD.zip already exists it is used directly.

These feeds are used by `ddig purge-registered` to identify and remove
domains from the DDig database that have since been registered by someone.

No authentication required for either feed.

Downloaded files are saved to <project_root>/data/nrd/ with timestamps
so you can review them after the fact.
"""
from __future__ import annotations

import base64
import io
import logging
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterator

import requests

from .base import FQDNSource

log = logging.getLogger(__name__)

# cenk/nrd GitHub feed — only the 10-day file is confirmed to exist
NRD_GITHUB_URL = "https://raw.githubusercontent.com/cenk/nrd/master/nrd-last-10-days.txt"

# WhoisDS base URL — date is base64-encoded as YYYY-MM-DD.zip (with .zip suffix, no newline)
WHOISDS_BASE_URL = "https://whoisds.com//whois-database/newly-registered-domains/{encoded}/nrd"

# How many days back to try for WhoisDS (files are ~4 days in arrears)
WHOISDS_LOOKBACK_DAYS = 10

# Data directory — relative to project root (two levels up from this file)
_PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = _PROJECT_ROOT / "data" / "nrd"


def _whoisds_url(date: datetime) -> str:
    """Build the WhoisDS download URL for a given date.

    WhoisDS encodes the date as YYYY-MM-DD.zip (with .zip suffix, no newline).
    """
    date_str = date.strftime("%Y-%m-%d") + ".zip"
    encoded  = base64.b64encode(date_str.encode()).decode()
    return WHOISDS_BASE_URL.format(encoded=encoded)


class NRDSource(FQDNSource):
    """
    Fetches newly registered domain FQDNs from NRD feeds.

    By default fetches from both cenk/nrd (GitHub) and WhoisDS for
    maximum coverage. Pass sources=['nrd'] or sources=['whoisds'] to
    restrict to one feed.

    Downloaded files are saved to <project_root>/data/nrd/ with
    timestamps so you can review them later.

    Usage::

        src = NRDSource()
        fqdns = set(src.fetch())

        src = NRDSource(sources=["nrd"])
        for fqdn in src.fetch():
            print(fqdn)
    """

    name = "nrd"

    def __init__(
        self,
        sources: list[str] = None,  # type: ignore[assignment]
    ) -> None:
        """
        Args:
            sources: Which feeds to use. Default: ["nrd", "whoisds"].
                     Valid values: "nrd", "whoisds".
        """
        self._sources = sources if sources is not None else ["nrd", "whoisds"]
        self._session = requests.Session()
        self._session.headers["User-Agent"] = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # FQDNSource interface
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        try:
            resp = self._session.head(NRD_GITHUB_URL, timeout=10, allow_redirects=True)
            return resp.status_code < 500
        except Exception as exc:
            log.debug("NRD availability check failed: %s", exc)
            return False

    def fetch(self) -> Iterator[str]:
        """Yield unique FQDNs from all configured NRD feeds."""
        seen: set[str] = set()

        if "nrd" in self._sources:
            yield from self._fetch_github(seen)

        if "whoisds" in self._sources:
            yield from self._fetch_whoisds(seen)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _save_raw(self, content: bytes, label: str) -> Path:
        """Save raw downloaded content to data/nrd/ with a timestamp."""
        ts       = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"{ts}_{label}"
        path     = DATA_DIR / filename
        path.write_bytes(content)
        log.debug("Saved raw NRD feed to %s (%d bytes)", path, len(content))
        return path

    def _fetch_github(self, seen: set[str]) -> Iterator[str]:
        """Fetch cenk/nrd 10-day feed from GitHub."""
        log.info("Fetching NRD feed (cenk/nrd, 10-day): %s", NRD_GITHUB_URL)

        try:
            resp = self._session.get(NRD_GITHUB_URL, timeout=60)
            resp.raise_for_status()
        except Exception as exc:
            log.warning("Failed to fetch cenk/nrd feed: %s", exc)
            return

        if not resp.content.strip():
            log.warning("Empty response from cenk/nrd feed")
            return

        self._save_raw(resp.content, "nrd_github_10day.txt")

        count = 0
        for line in resp.text.splitlines():
            fqdn = line.strip().lower()
            if not fqdn or fqdn.startswith("#") or "." not in fqdn:
                continue
            if fqdn in seen:
                continue
            seen.add(fqdn)
            count += 1
            yield fqdn

        log.info("cenk/nrd feed: %d unique FQDNs", count)

    def _fetch_whoisds(self, seen: set[str]) -> Iterator[str]:
        """
        Fetch WhoisDS newly-registered-domains ZIPs.

        Tries today and up to WHOISDS_LOOKBACK_DAYS days back.
        For each date:
        - If the file already exists in DATA_DIR, use it directly (skip download).
        - Otherwise attempt to download it; skip silently on 404/error.
        Yields FQDNs from ALL successfully retrieved dates (not just the first).
        """
        now = datetime.now(timezone.utc)

        for days_back in range(0, WHOISDS_LOOKBACK_DAYS + 1):
            date     = now - timedelta(days=days_back)
            date_str = date.strftime("%Y-%m-%d")
            filename = f"nrd_whoisds_{date_str}.zip"

            # Check if any saved file matches this date (regardless of timestamp prefix)
            existing = list(DATA_DIR.glob(f"*{filename}"))
            if existing:
                cached_path = existing[0]
                log.info("WhoisDS: using cached file for %s: %s", date_str, cached_path.name)
                content = cached_path.read_bytes()
            else:
                url = _whoisds_url(date)
                log.info("Trying WhoisDS NRD feed for %s: %s", date_str, url)

                try:
                    resp = self._session.get(url, timeout=60)
                    resp.raise_for_status()
                except Exception as exc:
                    log.debug("WhoisDS %s failed: %s — skipping", date_str, exc)
                    continue

                if not resp.content:
                    log.debug("WhoisDS %s — empty response, skipping", date_str)
                    continue

                if not zipfile.is_zipfile(io.BytesIO(resp.content)):
                    log.debug("WhoisDS %s — not a valid ZIP, skipping", date_str)
                    continue

                content = resp.content
                self._save_raw(content, filename)
                log.info("WhoisDS: downloaded and cached feed for %s", date_str)

            # Parse the ZIP and yield all FQDNs
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as zf:
                    log.debug("WhoisDS ZIP contains: %s", zf.namelist())
                    count = 0
                    for name in zf.namelist():
                        with zf.open(name) as fh:
                            text = fh.read().decode("utf-8", errors="replace")
                            for line in text.splitlines():
                                fqdn = line.strip().lower()
                                if not fqdn or "." not in fqdn:
                                    continue
                                if fqdn in seen:
                                    continue
                                seen.add(fqdn)
                                count += 1
                                yield fqdn
                    log.info("WhoisDS %s: %d unique FQDNs", date_str, count)
            except zipfile.BadZipFile as exc:
                log.warning("WhoisDS ZIP parse failed for %s: %s", date_str, exc)
                continue

        log.debug("WhoisDS: completed lookback — checked %d days", WHOISDS_LOOKBACK_DAYS + 1)