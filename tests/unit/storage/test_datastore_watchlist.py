"""Unit tests for DomainStore watchlist methods."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone

from ddig.storage.datastore import DomainStore


@pytest.fixture
def store(tmp_path):
    return DomainStore(db_path=tmp_path / "test.db")


# ------------------------------------------------------------------ #
# watch_add                                                           #
# ------------------------------------------------------------------ #

class TestWatchAdd:
    def test_add_single(self, store):
        added = store.watch_add(["forge.io"])
        assert added == ["forge.io"]

    def test_add_multiple(self, store):
        added = store.watch_add(["forge.io", "pixel.dev", "atlas.app"])
        assert set(added) == {"forge.io", "pixel.dev", "atlas.app"}

    def test_add_lowercases_fqdn(self, store):
        added = store.watch_add(["FORGE.IO"])
        assert added == ["forge.io"]

    def test_add_strips_whitespace(self, store):
        added = store.watch_add(["  forge.io  "])
        assert added == ["forge.io"]

    def test_add_duplicate_is_noop(self, store):
        store.watch_add(["forge.io"])
        added = store.watch_add(["forge.io"])
        assert added == []

    def test_add_returns_only_newly_added(self, store):
        store.watch_add(["forge.io"])
        added = store.watch_add(["forge.io", "pixel.dev"])
        assert added == ["pixel.dev"]

    def test_add_empty_list(self, store):
        added = store.watch_add([])
        assert added == []


# ------------------------------------------------------------------ #
# watch_remove                                                        #
# ------------------------------------------------------------------ #

class TestWatchRemove:
    def test_remove_existing(self, store):
        store.watch_add(["forge.io"])
        removed = store.watch_remove(["forge.io"])
        assert removed == ["forge.io"]

    def test_remove_not_in_watchlist(self, store):
        removed = store.watch_remove(["forge.io"])
        assert removed == []

    def test_remove_multiple(self, store):
        store.watch_add(["forge.io", "pixel.dev", "atlas.app"])
        removed = store.watch_remove(["forge.io", "pixel.dev"])
        assert set(removed) == {"forge.io", "pixel.dev"}

    def test_remove_leaves_others(self, store):
        store.watch_add(["forge.io", "pixel.dev"])
        store.watch_remove(["forge.io"])
        entries = store.watch_list()
        fqdns = [e["fqdn"] for e in entries]
        assert "forge.io"  not in fqdns
        assert "pixel.dev" in     fqdns

    def test_remove_empty_list(self, store):
        removed = store.watch_remove([])
        assert removed == []


# ------------------------------------------------------------------ #
# watch_list                                                          #
# ------------------------------------------------------------------ #

class TestWatchList:
    def test_empty_watchlist(self, store):
        assert store.watch_list() == []

    def test_list_returns_all_added(self, store):
        store.watch_add(["forge.io", "pixel.dev"])
        entries = store.watch_list()
        assert len(entries) == 2

    def test_list_entry_has_fqdn(self, store):
        store.watch_add(["forge.io"])
        entries = store.watch_list()
        assert entries[0]["fqdn"] == "forge.io"

    def test_list_entry_has_added_at(self, store):
        store.watch_add(["forge.io"])
        entries = store.watch_list()
        assert "added_at" in entries[0]
        assert entries[0]["added_at"] is not None

    def test_list_entry_domain_is_none_when_not_in_domains(self, store):
        store.watch_add(["forge.io"])
        entries = store.watch_list()
        assert entries[0]["domain"] is None

    def test_list_entry_domain_populated_when_in_domains(self, store, tmp_path):
        from ddig.models.domain import Domain
        domain = Domain(
            fqdn      = "forge.io",
            name      = "forge",
            tld       = "io",
            source    = "dropcatch",
            nlp_score = 0.85,
        )
        store.upsert_many([domain])
        store.watch_add(["forge.io"])
        entries = store.watch_list()
        assert entries[0]["domain"] is not None
        assert entries[0]["domain"].fqdn == "forge.io"
        assert entries[0]["domain"].nlp_score == pytest.approx(0.85)

    def test_list_ordered_most_recent_first(self, store):
        store.watch_add(["first.io"])
        store.watch_add(["second.io"])
        entries = store.watch_list()
        fqdns = [e["fqdn"] for e in entries]
        assert fqdns[0] == "second.io"
        assert fqdns[1] == "first.io"


# ------------------------------------------------------------------ #
# watch_clear                                                         #
# ------------------------------------------------------------------ #

class TestWatchClear:
    def test_clear_returns_count(self, store):
        store.watch_add(["forge.io", "pixel.dev", "atlas.app"])
        removed = store.watch_clear()
        assert removed == 3

    def test_clear_empties_watchlist(self, store):
        store.watch_add(["forge.io", "pixel.dev"])
        store.watch_clear()
        assert store.watch_list() == []

    def test_clear_empty_watchlist(self, store):
        removed = store.watch_clear()
        assert removed == 0

    def test_clear_then_add_works(self, store):
        store.watch_add(["forge.io"])
        store.watch_clear()
        added = store.watch_add(["forge.io"])
        assert added == ["forge.io"]