"""Majestic Million source — top 1M domains ranked by referring subnets.

Free daily CSV, no authentication required.
URL: https://downloads.majestic.com/majestic_million.csv

Columns used:
  GlobalRank   — overall rank 1–1,000,000
  Domain       — registered domain (no TLD prefix)
  TLD          — TLD without leading dot
  RefSubNets   — referring subnets (used as backlinks proxy)
"""
from __future__ import annotations

import csv
import io
import logging
from collections.abc import Iterator
from datetime import datetime, timezone

import requests
import tldextract

from ddig.models.domain import Domain
from ddig.sources.base import DomainSource

log = logging.getLogger(__name__)

CSV_URL   = "https://downloads.majestic.com/majestic_million.csv"
SOURCE    = "majestic"


class MajesticMillionSource(DomainSource):
    """Stream the Majestic Million CSV and yield Domain objects.

    Each domain carries:
      - backlinks  = RefSubNets  (referring subnets — best available proxy)
      - rank       = GlobalRank
      - source     = "majestic"

    Because every domain in the list is *registered*, this source is useful
    for enriching backlink data on domains already in the DB rather than
    for finding expired/dropping domains directly.  Use it alongside CZDS
    or DropCatch.
    """

    name = SOURCE

    def __init__(
        self,
        *,
        url:       str  = CSV_URL,
        limit:     int  = 0,          # 0 = all 1M rows
        min_rank:  int  = 0,          # skip rows with GlobalRank < min_rank
        max_rank:  int  = 0,          # 0 = no upper limit
        timeout:   int  = 120,
    ) -> None:
        self.url      = url
        self.limit    = limit
        self.min_rank = min_rank
        self.max_rank = max_rank
        self.timeout  = timeout
        self._session = requests.Session()
        self._session.headers["User-Agent"] = (
            "Mozilla/5.0 (compatible; ddig/1.0; +https://github.com/yourusername/ddig)"
        )

    # ------------------------------------------------------------------ #
    # DomainSource interface                                              #
    # ------------------------------------------------------------------ #

    def is_available(self) -> bool:
        """Always available — no credentials required."""
        return True

    def fetch(self) -> Iterator[Domain]:
        log.info("Downloading Majestic Million CSV from %s…", self.url)

        resp = self._session.get(self.url, timeout=self.timeout, stream=True)
        resp.raise_for_status()

        # Stream the response line-by-line — file is ~45 MB uncompressed
        lines   = resp.iter_lines(decode_unicode=True)
        reader  = csv.DictReader(lines)

        count   = 0
        skipped = 0

        for row in reader:
            try:
                raw_domain  = (row.get("Domain") or "").strip().lower()
                tld_raw     = (row.get("TLD")    or "").strip().lower().lstrip(".")
                rank_raw    = (row.get("GlobalRank") or "0").strip()
                refs_raw    = (row.get("RefSubNets") or "0").strip()

                if not raw_domain or not tld_raw:
                    skipped += 1
                    continue

                # Domain column is already the full domain e.g. "bit.ly"
                # Use tldextract to get the registrable name without TLD
                ext = tldextract.extract(raw_domain)
                if not ext.domain:
                    skipped += 1
                    continue

                # Rebuild fqdn from parts — don't double-append TLD
                fqdn        = raw_domain if "." in raw_domain else f"{raw_domain}.{tld_raw}"
                domain_name = ext.domain
                tld_clean   = (ext.suffix or tld_raw).lstrip(".")

                rank = _parse_int(rank_raw)
                refs = _parse_int(refs_raw)

                if self.min_rank and rank < self.min_rank:
                    skipped += 1
                    continue
                if self.max_rank and rank > self.max_rank:
                    skipped += 1
                    continue

                yield Domain(
                    name       = domain_name,
                    tld        = tld_clean,
                    fqdn       = fqdn,
                    source     = SOURCE,
                    backlinks  = refs,
                    rank       = rank,
                    fetched_at = datetime.now(timezone.utc),
                )

                count += 1
                if self.limit and count >= self.limit:
                    log.info("Reached limit of %d domains — stopping.", self.limit)
                    break

            except Exception as exc:
                log.debug("Skipping malformed row %r: %s", row, exc)
                skipped += 1
                continue

        log.info("Majestic Million: yielded %d domains, skipped %d.", count, skipped)


# ------------------------------------------------------------------ #
# Parsing helpers                                                     #
# ------------------------------------------------------------------ #

def _parse_int(value: str | None) -> int:
    """Parse an integer string, returning 0 on failure."""
    if not value:
        return 0
    try:
        return int(str(value).strip().replace(",", ""))
    except (ValueError, TypeError):
        return 0