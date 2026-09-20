"""
SnapNames source.

Fetches expiring and deleting domains from the SnapNames CSV download interface.

No authentication required.

Available feeds:
    allexpiring   — all expiring domains (default, ~thousands)
    deleting      — deleting in next 5 days - full list (default)

Feed filenames map to:
    https://www.snapnames.com/file_dl.sn?file=<filename>.csv

CSV format (after 2 preamble lines):
    Domain name, Current bid, Auction end date

Downloaded files are saved to <project_root>/data/snapnames/ with a datestamp.
If today's file already exists it is used directly and the download is skipped.
"""
from __future__ import annotations

import csv
import io
import logging
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import requests

from ..models.domain import Domain
from .base import DomainSource

log = logging.getLogger(__name__)

BASE_URL = "https://www.snapnames.com"

# Default feeds fetched when no --feed is specified
DEFAULT_FEEDS = [
    "allexpiring_list",  # all expiring domains
    "deletinglist",      # deleting in next 5 days - full
]

# Human-readable feed name → CSV filename stem
FEED_ALIASES: dict[str, str] = {
    "allexpiring": "allexpiring_list",
    "deleting":    "deletinglist",
}

_PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR      = _PROJECT_ROOT / "data" / "snapnames"


class SnapNamesSource(DomainSource):
    """
    Fetches expiring/deleting domains from SnapNames CSV feeds.

    By default fetches two feeds:
    - allexpiring_list  (all expiring domains)
    - deletinglist      (deleting within next 5 days, full list)

    Pass feed='allexpiring' or feed='deleting' (or the raw filename stem)
    to fetch a single specific feed.

    Usage::

        source = SnapNamesSource()
        for domain in source.fetch():
            print(domain)

        # single feed
        source = SnapNamesSource(feed="deleting")
    """

    name = "snapnames"

    def __init__(
        self,
        feed: str | None = None,
    ) -> None:
        """
        Args:
            feed: feed alias or raw filename stem to fetch.
                  If None, both DEFAULT_FEEDS are fetched.
        """
        self._feed = feed
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": BASE_URL + "/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # DomainSource interface
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        try:
            resp = self._session.head(BASE_URL, timeout=10)
            return resp.status_code < 500
        except Exception as exc:
            log.debug("SnapNames availability check failed: %s", exc)
            return False

    def fetch(self) -> Iterator[Domain]:
        feeds = self._resolve_feeds()
        seen: set[str] = set()
        for filename in feeds:
            yield from self._fetch_feed(filename, seen)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _resolve_feeds(self) -> list[str]:
        """Resolve the feed argument to a list of CSV filename stems."""
        if self._feed is None:
            return list(DEFAULT_FEEDS)
        return [FEED_ALIASES.get(self._feed, self._feed)]

    def _local_path(self, filename: str) -> Path:
        """Return the expected cache path for today's CSV for a given feed."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return DATA_DIR / f"snapnames_{filename}_{today}.csv"

    def _get_feed_text(self, filename: str) -> str | None:
        """
        Return raw CSV text for a feed.

        If today's file already exists on disk, reads from cache.
        Otherwise downloads, saves, and returns the text.
        Returns None on network error.
        """
        path = self._local_path(filename)

        if path.exists():
            log.info("SnapNames: using cached file %s", path.name)
            return path.read_text(encoding="utf-8", errors="replace")

        url = f"{BASE_URL}/file_dl.sn?file={filename}.csv"
        log.info("Fetching SnapNames feed: %s", url)
        try:
            resp = self._session.get(url, timeout=60)
            resp.raise_for_status()
        except Exception as exc:
            log.warning("Failed to fetch feed %r: %s", filename, exc)
            return None

        if not resp.text.strip():
            log.warning("Empty response for feed %r", filename)
            return None

        path.write_text(resp.text, encoding="utf-8")
        log.info("SnapNames: saved %s (%d bytes)", path.name, path.stat().st_size)
        return resp.text

    def _fetch_feed(self, filename: str, seen: set[str]) -> Iterator[Domain]:
        text = self._get_feed_text(filename)
        if not text:
            return

        # The CSV has 2 preamble lines before the real header:
        #   line 0: disclaimer text
        #   line 1: blank
        #   line 2: "Domain name,Current bid,Auction end date"
        lines = text.splitlines()
        skip = 0
        for i, line in enumerate(lines):
            if line.strip().lower().startswith("domain"):
                skip = i
                break

        csv_text = "\n".join(lines[skip:])
        if not csv_text.strip():
            log.warning("No data rows found in feed %r", filename)
            return

        reader = csv.DictReader(io.StringIO(csv_text))
        for row in reader:
            domain = self._parse_row(row)
            if domain is None:
                continue
            if domain.fqdn in seen:
                continue
            seen.add(domain.fqdn)
            yield domain

    def _parse_row(self, row: dict[str, str]) -> Domain | None:
        """
        Parse a single CSV row into a Domain.

        Confirmed columns from live SnapNames feed:
            Domain name, Current bid, Auction end date
        """
        row = {k.strip().lower().replace(" ", "").replace("_", ""): v.strip() for k, v in row.items() if k}

        fqdn = (
            row.get("domainname")
            or row.get("domain")
            or row.get("name")
            or row.get("fqdn")
            or ""
        ).strip().lower()

        if not fqdn or "." not in fqdn:
            return None

        parts = fqdn.split(".", 1)
        name  = parts[0]
        tld   = parts[1] if len(parts) > 1 else ""

        drop_date: datetime | None = None
        raw_date = (
            row.get("auctionenddate")
            or row.get("dateavailable")
            or row.get("date")
            or row.get("dropdate")
            or row.get("availabledate")
            or row.get("expirydate")
            or row.get("expiry")
            or ""
        )
        if raw_date:
            for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
                try:
                    drop_date = datetime.strptime(raw_date, fmt)
                    break
                except ValueError:
                    continue

        base = Domain(
            fqdn       = fqdn,
            name       = name,
            tld        = tld,
            source     = self.name,
            fetched_at = datetime.now(timezone.utc),
        )
        return replace(base, drop_date=drop_date)