"""Unit tests for DomainStore.purge_no_drop_date()."""
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
def store(tmp_path: Path) -> DomainStore:
    return DomainStore(db_path=tmp_path / "test.db")


@pytest.fixture
def populated_store(store: DomainStore) -> DomainStore:
    store.upsert_many([
        _domain(fqdn="keep-me.com",   name="keep-me",   tld="com",
                drop_date=datetime(2026, 5, 1, tzinfo=timezone.utc)),
        _domain(fqdn="keep-me-2.com", name="keep-me-2", tld="com",
                drop_date=datetime(2026, 5, 2, tzinfo=timezone.utc)),
        _domain(fqdn="no-date-1.com", name="no-date-1", tld="com"),
        _domain(fqdn="no-date-2.com", name="no-date-2", tld="com"),
        _domain(fqdn="no-date-3.net", name="no-date-3", tld="net"),
    ])
    return store


class TestPurgeNoDropDate:
    def test_returns_correct_count(self, populated_store: DomainStore) -> None:
        count = populated_store.purge_no_drop_date()
        assert count == 3

    def test_removes_only_null_drop_date(self, populated_store: DomainStore) -> None:
        populated_store.purge_no_drop_date()
        remaining = populated_store.search(limit=100)
        fqdns = {d.fqdn for d in remaining}
        assert "keep-me.com"   in fqdns
        assert "keep-me-2.com" in fqdns

    def test_does_not_remove_domains_with_drop_date(self, populated_store: DomainStore) -> None:
        populated_store.purge_no_drop_date()
        assert populated_store.count() == 2

    def test_purged_domains_gone(self, populated_store: DomainStore) -> None:
        populated_store.purge_no_drop_date()
        remaining = populated_store.search(limit=100)
        fqdns = {d.fqdn for d in remaining}
        assert "no-date-1.com" not in fqdns
        assert "no-date-2.com" not in fqdns
        assert "no-date-3.net" not in fqdns

    def test_empty_store_returns_zero(self, store: DomainStore) -> None:
        assert store.purge_no_drop_date() == 0

    def test_all_have_drop_date_returns_zero(self, store: DomainStore) -> None:
        store.upsert_many([
            _domain(fqdn="a.com", name="a", tld="com",
                    drop_date=datetime(2026, 5, 1, tzinfo=timezone.utc)),
            _domain(fqdn="b.com", name="b", tld="com",
                    drop_date=datetime(2026, 5, 2, tzinfo=timezone.utc)),
        ])
        assert store.purge_no_drop_date() == 0

    def test_idempotent(self, populated_store: DomainStore) -> None:
        populated_store.purge_no_drop_date()
        assert populated_store.purge_no_drop_date() == 0