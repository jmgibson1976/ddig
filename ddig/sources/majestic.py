"""Majestic Million source — top 1M domains ranked by referring subnets.

Free daily CSV, no authentication required.
URL: https://downloads.majestic.com/majestic_million.csv

Columns used:
  GlobalRank   — overall rank 1–1,000,000
  Domain       — full FQDN e.g. "google.com" (NOT just the SLD — do not append TLD)
  TLD          — TLD without leading dot e.g. "com"
  RefSubNets   — referring subnets (used as backlinks proxy)

Note: fqdn = Domain column as-is. Constructing f"{Domain}.{TLD}" produces
duplicates like "google.com.com" — the Domain column already includes the TLD.

Downloaded files are saved to <project_root>/data/majestic/ with a datestamp.
If today's file already exists it is used directly and the download is skipped.
"""
from __future__ import annotations

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import requests

from ddig.models.domain import Domain
from ddig.sources.base import DomainSource
from ddig.storage.datastore import DomainStore

log = logging.getLogger(__name__)

CSV_URL = "https://downloads.majestic.com/majestic_million.csv"
SOURCE  = "majestic"
UA      = "ddig/1.0 (+https://github.com/your-org/ddig)"

_PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR      = _PROJECT_ROOT / "data" / "majestic"


class MajesticMillionSource(DomainSource):
    """Majestic Million CSV — enrichment-only, never creates new records."""

    name = SOURCE

    def __init__(
        self,
        *,
        url:      str = CSV_URL,
        limit:    int = 0,
        min_rank: int = 0,
        max_rank: int = 0,
        timeout:  int = 120,
    ) -> None:
        self.url      = url
        self.limit    = limit
        self.min_rank = min_rank
        self.max_rank = max_rank
        self.timeout  = timeout
        self._session = requests.Session()
        self._session.headers["User-Agent"] = UA
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    def is_available(self) -> bool:
        return True

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _local_path(self) -> Path:
        """Return the expected cache path for today's CSV."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return DATA_DIR / f"majestic_million_{today}.csv"

    def _get_lines(self) -> Iterator[str]:
        """
        Yield raw lines from today's Majestic Million CSV.

        If a cached file for today already exists, reads from disk.
        Otherwise streams from the network, saves to disk, then yields lines.
        """
        path = self._local_path()

        if path.exists():
            log.info("Majestic: using cached file %s", path.name)
            with path.open(encoding="utf-8", errors="replace") as fh:
                yield from (line.rstrip("\n") for line in fh)
            return

        log.info("Majestic: downloading CSV from %s", self.url)
        resp = self._session.get(self.url, timeout=self.timeout, stream=True)
        resp.raise_for_status()

        lines = list(resp.iter_lines(decode_unicode=True))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        log.info("Majestic: saved %s (%d bytes)", path.name, path.stat().st_size)
        yield from lines

    # ------------------------------------------------------------------
    # public
    # ------------------------------------------------------------------

    def fetch(self) -> Iterator[Domain]:
        """
        Enrich existing domains with backlinks and rank from Majestic Million.
        Never creates new records — only yields domains already in the store.
        """
        store          = DomainStore()
        existing_fqdns = store.get_all_fqdns()

        reader = csv.DictReader(self._get_lines())

        count = 0
        for row in reader:
            domain_col = row.get("Domain", "").lower().strip()
            tld        = row.get("TLD",    "").lower().strip()
            if not domain_col or not tld:
                continue

            fqdn = domain_col
            name = domain_col[: domain_col.rfind(".")] if "." in domain_col else domain_col

            if fqdn not in existing_fqdns:
                continue

            rank      = _parse_int(row.get("GlobalRank"))
            backlinks = _parse_int(row.get("RefSubNets"))

            if self.min_rank and rank < self.min_rank:
                continue
            if self.max_rank and rank > self.max_rank:
                continue

            yield Domain(
                name      = name,
                tld       = tld,
                fqdn      = fqdn,
                source    = SOURCE,
                backlinks = backlinks or None,
                rank      = rank      or None,
            )

            count += 1
            if self.limit and count >= self.limit:
                break


def _parse_int(value: str | None) -> int:
    if not value:
        return 0
    try:
        return int(str(value).strip().replace(",", ""))
    except (ValueError, TypeError):
        return 0