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
"""
from __future__ import annotations

import csv
import logging
from datetime import datetime, timezone
from typing import Iterator

import requests

from ddig.models.domain import Domain
from ddig.sources.base import DomainSource
from ddig.storage.datastore import DomainStore

log = logging.getLogger(__name__)

CSV_URL = "https://downloads.majestic.com/majestic_million.csv"
SOURCE  = "majestic"
UA      = "ddig/1.0 (+https://github.com/your-org/ddig)"


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

    def is_available(self) -> bool:
        return True

    def fetch(self) -> Iterator[Domain]:
        """
        Enrich existing domains with backlinks and rank from Majestic Million.
        Never creates new records — only yields domains already in the store.
        """
        store          = DomainStore()
        existing_fqdns = store.get_all_fqdns()

        resp = self._session.get(self.url, timeout=self.timeout, stream=True)
        resp.raise_for_status()

        count  = 0
        reader = csv.DictReader(resp.iter_lines(decode_unicode=True))
        for row in reader:
            domain_col = row.get("Domain", "").lower().strip()
            tld        = row.get("TLD",    "").lower().strip()
            if not domain_col or not tld:
                continue

            # Domain column is already the full FQDN (e.g. "google.com")
            # TLD column is just the TLD (e.g. "com")
            # name = everything before the first dot
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