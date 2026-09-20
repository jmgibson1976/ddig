"""
Park.io source.

Fetches expiring domains from https://park.io/domains/index/<tld>.json

Supported TLDs (18 total as of 2026):
    co, ly, gg, vc, io, sh, me, ag, us, lc, sc, pro, info, ac, je, bz, mn, red

Pagination:
    Each TLD returns up to 1000 domains across 5 pages of 200.
    The API returns nextPage: true/false — iteration stops early per TLD.

No authentication required.

Downloaded JSON responses are saved to <project_root>/data/parkio/ with a
datestamp and TLD name. If today's file already exists for a TLD it is used
directly and the download is skipped.
"""
from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import requests

from ..models.domain import Domain
from .base import DomainSource

log = logging.getLogger(__name__)

BASE_URL = "https://park.io/domains/index"

# All TLDs supported by Park.io as observed from their UI
ALL_TLDS = [
    "co", "ly", "gg", "vc", "io", "sh", "me", "ag",
    "us", "lc", "sc", "pro", "info", "ac", "je", "bz", "mn", "red",
]

DEFAULT_MAX_PAGES = 20

_PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR      = _PROJECT_ROOT / "data" / "parkio"


class ParkIOSource(DomainSource):
    """
    Fetches expiring domains from the Park.io JSON API.

    By default fetches all 18 supported TLDs, up to 20 pages (4000 domains)
    per TLD. Pass tlds=['io', 'co'] to restrict to specific TLDs.
    Pass max_pages=N to override the per-TLD page cap.

    Usage::

        # all TLDs
        source = ParkIOSource()
        for domain in source.fetch():
            print(domain)

        # specific TLDs only
        source = ParkIOSource(tlds=["io", "co", "me"])

        # increase page cap
        source = ParkIOSource(max_pages=50)
    """

    name = "parkio"

    def __init__(
        self,
        tlds: list[str] | None = None,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> None:
        self._tlds      = tlds if tlds is not None else list(ALL_TLDS)
        self._max_pages = max_pages
        self._session   = requests.Session()
        self._session.headers["User-Agent"] = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # DomainSource interface
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        try:
            url  = f"{BASE_URL}/io.json?page=1"
            resp = self._session.get(url, timeout=10)
            if not resp.text.strip():
                return False
            data = resp.json()
            return bool(data.get("success"))
        except Exception as exc:
            log.debug("Park.io availability check failed: %s", exc)
            return False

    def fetch(self) -> Iterator[Domain]:
        for tld in self._tlds:
            yield from self._fetch_tld(tld)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _local_path(self, tld: str) -> Path:
        """Return the expected cache path for today's JSON for a given TLD."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return DATA_DIR / f"parkio_{tld}_{today}.json"

    def _fetch_tld(self, tld: str) -> Iterator[Domain]:
        path = self._local_path(tld)

        if path.exists():
            log.info("Park.io: using cached file %s", path.name)
            try:
                all_domains = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                log.warning("Park.io: failed to read cache for TLD=%s: %s", tld, exc)
                path.unlink(missing_ok=True)
                yield from self._fetch_tld_from_network(tld)
                return
            for item in all_domains:
                domain = self._parse_item(item, tld)
                if domain is not None:
                    yield domain
            return

        yield from self._fetch_tld_from_network(tld)

    def _fetch_tld_from_network(self, tld: str) -> Iterator[Domain]:
        """Fetch all pages for a TLD from the network, save to cache, yield domains."""
        path        = self._local_path(tld)
        all_items:  list[dict] = []
        page        = 1

        while True:
            url = f"{BASE_URL}/{tld}.json?page={page}"
            log.info("Fetching Park.io TLD=%s page=%d", tld, page)
            try:
                resp = self._session.get(url, timeout=30)
                resp.raise_for_status()
            except Exception as exc:
                log.warning("Failed to fetch Park.io TLD=%s page=%d: %s", tld, page, exc)
                break

            if not resp.text.strip():
                log.debug("Empty response for TLD=%s page=%d", tld, page)
                break

            try:
                data = resp.json()
            except Exception:
                log.debug("Invalid JSON for TLD=%s page=%d (%d bytes) — skipping", tld, page, len(resp.content))
                break

            if not data.get("success"):
                log.warning("Park.io returned success=false for TLD=%s page=%d", tld, page)
                break

            all_items.extend(data.get("domains", []))

            if not data.get("nextPage"):
                break

            if page >= self._max_pages:
                log.warning(
                    "Park.io TLD=%s hit page cap (%d) — more pages available. "
                    "Use --pages to increase the limit.",
                    tld, self._max_pages,
                )
                break

            page += 1

        if all_items:
            path.write_text(json.dumps(all_items), encoding="utf-8")
            log.info("Park.io: saved %s (%d domains)", path.name, len(all_items))

        for item in all_items:
            domain = self._parse_item(item, tld)
            if domain is not None:
                yield domain

    def _parse_item(self, item: dict, tld: str) -> Domain | None:
        """
        Parse a single domain item from the Park.io JSON response.

        Expected fields:
            id              — internal Park.io ID (ignored)
            name            — full FQDN e.g. "example.io"
            date_available  — drop date e.g. "2026-04-19"
            date_registered — original registration date → stored as expiry_date
            tld             — TLD string e.g. "io"
        """
        fqdn = (item.get("name") or "").strip().lower()
        if not fqdn or "." not in fqdn:
            return None

        # Split fqdn → name label + tld (use API tld field as ground truth)
        api_tld  = (item.get("tld") or tld).strip().lstrip(".")
        dot_tld  = f".{api_tld}"
        if fqdn.endswith(dot_tld):
            name = fqdn[: -len(dot_tld)]
        else:
            parts = fqdn.split(".", 1)
            name  = parts[0]

        # date_available → drop_date
        drop_date: datetime | None = None
        raw_drop = (item.get("date_available") or "").strip()
        if raw_drop:
            try:
                drop_date = datetime.strptime(raw_drop, "%Y-%m-%d")
            except ValueError:
                log.debug("Could not parse date_available %r for %s", raw_drop, fqdn)

        # date_registered → expiry_date
        expiry_date: datetime | None = None
        raw_expiry = (item.get("date_registered") or "").strip()
        if raw_expiry:
            try:
                expiry_date = datetime.strptime(raw_expiry, "%Y-%m-%d")
            except ValueError:
                log.debug("Could not parse date_registered %r for %s", raw_expiry, fqdn)

        base = Domain(
            fqdn       = fqdn,
            name       = name,
            tld        = api_tld,
            source     = self.name,
            fetched_at = datetime.now(timezone.utc),
        )
        return replace(base, drop_date=drop_date, expiry_date=expiry_date)