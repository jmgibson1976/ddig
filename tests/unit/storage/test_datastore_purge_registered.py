"""Unit tests for DomainStore.purge_fqdns() and get_watchlist_fqdns()."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ddig.models.domain import Domain
from ddig.storage.datastore import DomainStore


def _domain(**kwargs) -> Domain:
    base = Domain(
        fqdn   = "forge.io",
        name   = "forge",
        tld    = "io",
        source = "dropcatch",
    )
    return replace(base, **kwargs)


@pytest.fixture
def store(tmp_path):
    return DomainStore(db_path=tmp_path / "test.db")


@pytest.fixture
def populated_store(store):
    domains = [
        _domain(fqdn="forge.io",   name="forge",   tld="io"),
        _domain(fqdn="atlas.me",   name="atlas",   tld="me"),
        _domain(fqdn="bright.com", name="bright",  tld="com"),
        _domain(fqdn="keep.io",    name="keep",    tld="io"),
    ]
    store.upsert_many(domains)
    store.watch_add(["keep.io"])
    return store


# ------------------------------------------------------------------
# TestPurgeFqdns
# ------------------------------------------------------------------

class TestPurgeFqdns:
    def test_deletes_matched_fqdns(self, populated_store):
        deleted = populated_store.purge_fqdns(["forge.io", "atlas.me"])
        assert deleted == 2

    def test_returns_zero_for_no_matches(self, populated_store):
        deleted = populated_store.purge_fqdns(["notindatabase.io"])
        assert deleted == 0

    def test_skips_protected_fqdns(self, populated_store):
        deleted = populated_store.purge_fqdns(
            ["forge.io", "keep.io"],
            skip=frozenset(["keep.io"]),
        )
        assert deleted == 1
        remaining = populated_store.get_all_fqdns()
        assert "keep.io" in remaining
        assert "forge.io" not in remaining

    def test_empty_input_returns_zero(self, populated_store):
        deleted = populated_store.purge_fqdns([])
        assert deleted == 0

    def test_domains_removed_from_db(self, populated_store):
        populated_store.purge_fqdns(["forge.io"])
        remaining = populated_store.get_all_fqdns()
        assert "forge.io" not in remaining

    def test_unmatched_fqdns_ignored(self, populated_store):
        deleted = populated_store.purge_fqdns(["forge.io", "ghost.xyz"])
        assert deleted == 1

    def test_large_batch(self, store):
        domains = [
            _domain(fqdn=f"domain{i}.com", name=f"domain{i}", tld="com")
            for i in range(3000)
        ]
        store.upsert_many(domains)
        fqdns   = [f"domain{i}.com" for i in range(3000)]
        deleted = store.purge_fqdns(fqdns)
        assert deleted == 3000


# ------------------------------------------------------------------
# TestGetWatchlistFqdns
# ------------------------------------------------------------------

class TestGetWatchlistFqdns:
    def test_returns_watchlisted_fqdns(self, populated_store):
        result = populated_store.get_watchlist_fqdns()
        assert "keep.io" in result

    def test_returns_frozenset(self, populated_store):
        result = populated_store.get_watchlist_fqdns()
        assert isinstance(result, frozenset)

    def test_empty_watchlist_returns_empty_frozenset(self, store):
        result = store.get_watchlist_fqdns()
        assert result == frozenset()

    def test_does_not_include_non_watchlisted(self, populated_store):
        result = populated_store.get_watchlist_fqdns()
        assert "forge.io" not in result