"""Unit tests for DomainStore.upsert_many() — the only write path."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from typing import Any

from ddig.models.domain import Domain
from ddig.storage.datastore import DomainStore


@pytest.fixture
def store(tmp_path):
    return DomainStore(db_path=tmp_path / "test.db")


def _domain(**kwargs) -> Domain:
    defaults: dict[str, Any] = dict(
        fqdn   = "forge.io",
        name   = "forge",
        tld    = "io",
        source = "dropcatch",
    )
    defaults.update(kwargs)
    return Domain(**defaults)


# ------------------------------------------------------------------ #
# Basic insert                                                        #
# ------------------------------------------------------------------ #

class TestUpsertInsert:
    def test_insert_single(self, store):
        store.upsert_many([_domain()])
        results = store.search()
        assert len(results) == 1

    def test_insert_multiple(self, store):
        store.upsert_many([
            _domain(fqdn="forge.io",  name="forge",  tld="io"),
            _domain(fqdn="pixel.dev", name="pixel",  tld="dev"),
            _domain(fqdn="atlas.app", name="atlas",  tld="app"),
        ])
        results = store.search()
        assert len(results) == 3

    def test_insert_empty_list(self, store):
        store.upsert_many([])
        assert store.search() == []

    def test_inserted_fqdn_correct(self, store):
        store.upsert_many([_domain(fqdn="forge.io")])
        results = store.search()
        assert results[0].fqdn == "forge.io"

    def test_inserted_name_correct(self, store):
        store.upsert_many([_domain(name="forge")])
        results = store.search()
        assert results[0].name == "forge"

    def test_inserted_tld_correct(self, store):
        store.upsert_many([_domain(tld="io")])
        results = store.search()
        assert results[0].tld == "io"

    def test_inserted_source_correct(self, store):
        store.upsert_many([_domain(source="dropcatch")])
        results = store.search()
        assert results[0].source == "dropcatch"

    def test_inserted_nlp_score(self, store):
        store.upsert_many([_domain(nlp_score=0.75)])
        results = store.search()
        assert results[0].nlp_score == pytest.approx(0.75)

    def test_inserted_backlinks(self, store):
        store.upsert_many([_domain(backlinks=5000)])
        results = store.search()
        assert results[0].backlinks == 5000

    def test_inserted_rank(self, store):
        store.upsert_many([_domain(rank=1234)])
        results = store.search()
        assert results[0].rank == 1234

    def test_inserted_drop_date(self, store):
        dt = datetime(2026, 4, 20, tzinfo=timezone.utc)
        store.upsert_many([_domain(drop_date=dt)])
        results = store.search()
        assert results[0].drop_date is not None
        assert results[0].drop_date.year == 2026

    def test_inserted_registrar(self, store):
        store.upsert_many([_domain(registrar="GoDaddy")])
        results = store.search()
        assert results[0].registrar == "GoDaddy"


# ------------------------------------------------------------------ #
# Upsert — deduplication by fqdn                                     #
# ------------------------------------------------------------------ #

class TestUpsertDeduplication:
    def test_duplicate_fqdn_does_not_create_new_row(self, store):
        store.upsert_many([_domain()])
        store.upsert_many([_domain()])
        assert len(store.search()) == 1

    def test_different_fqdns_create_separate_rows(self, store):
        store.upsert_many([_domain(fqdn="forge.io", name="forge", tld="io")])
        store.upsert_many([_domain(fqdn="pixel.dev", name="pixel", tld="dev")])
        assert len(store.search()) == 2

    def test_batch_deduplication(self, store):
        store.upsert_many([
            _domain(fqdn="forge.io", name="forge", tld="io"),
            _domain(fqdn="forge.io", name="forge", tld="io"),
        ])
        assert len(store.search()) == 1


# ------------------------------------------------------------------ #
# Upsert — source accumulation                                       #
# ------------------------------------------------------------------ #

class TestUpsertSourceAccumulation:
    def test_source_accumulates_on_re_fetch(self, store):
        store.upsert_many([_domain(source="dropcatch")])
        store.upsert_many([_domain(source="czds")])
        results = store.search()
        assert "dropcatch" in results[0].source
        assert "czds"      in results[0].source

    def test_source_not_duplicated(self, store):
        store.upsert_many([_domain(source="dropcatch")])
        store.upsert_many([_domain(source="dropcatch")])
        results = store.search()
        assert results[0].source.count("dropcatch") == 1

    def test_source_accumulates_across_three_sources(self, store):
        store.upsert_many([_domain(source="dropcatch")])
        store.upsert_many([_domain(source="czds")])
        store.upsert_many([_domain(source="majestic")])
        results = store.search()
        src = results[0].source
        assert "dropcatch" in src
        assert "czds"      in src
        assert "majestic"  in src


# ------------------------------------------------------------------ #
# Upsert — NLP score preservation                                    #
# ------------------------------------------------------------------ #

class TestUpsertNlpPreservation:
    def test_nlp_score_not_overwritten_on_refetch(self, store):
        store.upsert_many([_domain(nlp_score=0.85)])
        store.upsert_many([_domain(nlp_score=None)])
        results = store.search()
        assert results[0].nlp_score == pytest.approx(0.85)

    def test_nlp_score_written_when_previously_null(self, store):
        store.upsert_many([_domain(nlp_score=None)])
        store.upsert_many([_domain(nlp_score=0.75)])
        results = store.search()
        assert results[0].nlp_score == pytest.approx(0.75)

    def test_is_real_word_preserved_when_nlp_already_scored(self, store):
        # NLP fields are gated on nlp_score being null — once nlp_score is set
        # they are frozen. First upsert sets nlp_score + is_real_word.
        # Second upsert has no nlp_score — nlp_score guard keeps existing value.
        store.upsert_many([_domain(nlp_score=0.8, is_real_word=True)])
        store.upsert_many([_domain(nlp_score=None, is_real_word=False)])
        results = store.search()
        assert results[0].is_real_word is True

    def test_is_pronounceable_preserved_when_nlp_already_scored(self, store):
        store.upsert_many([_domain(nlp_score=0.8, is_pronounceable=True)])
        store.upsert_many([_domain(nlp_score=None, is_pronounceable=False)])
        results = store.search()
        assert results[0].is_pronounceable is True

    def test_word_frequency_preserved_when_nlp_already_scored(self, store):
        store.upsert_many([_domain(nlp_score=0.8, word_frequency=0.9)])
        store.upsert_many([_domain(nlp_score=None, word_frequency=0.1)])
        results = store.search()
        assert results[0].word_frequency == pytest.approx(0.9)

    def test_is_real_word_written_when_previously_null(self, store):
        store.upsert_many([_domain(nlp_score=None, is_real_word=None)])
        store.upsert_many([_domain(nlp_score=0.8,  is_real_word=True)])
        results = store.search()
        assert results[0].is_real_word is True

    def test_is_pronounceable_written_when_previously_null(self, store):
        store.upsert_many([_domain(nlp_score=None, is_pronounceable=None)])
        store.upsert_many([_domain(nlp_score=0.8,  is_pronounceable=True)])
        results = store.search()
        assert results[0].is_pronounceable is True

    def test_word_frequency_written_when_previously_null(self, store):
        store.upsert_many([_domain(nlp_score=None, word_frequency=None)])
        store.upsert_many([_domain(nlp_score=0.8,  word_frequency=0.9)])
        results = store.search()
        assert results[0].word_frequency == pytest.approx(0.9)


# ------------------------------------------------------------------ #
# Upsert — backlinks keeps highest value                             #
# ------------------------------------------------------------------ #

class TestUpsertBacklinks:
    def test_higher_backlinks_overwrites_lower(self, store):
        store.upsert_many([_domain(backlinks=1000)])
        store.upsert_many([_domain(backlinks=5000)])
        results = store.search()
        assert results[0].backlinks == 5000

    def test_lower_backlinks_does_not_overwrite_higher(self, store):
        store.upsert_many([_domain(backlinks=5000)])
        store.upsert_many([_domain(backlinks=1000)])
        results = store.search()
        assert results[0].backlinks == 5000

    def test_backlinks_written_when_previously_null(self, store):
        store.upsert_many([_domain(backlinks=None)])
        store.upsert_many([_domain(backlinks=1000)])
        results = store.search()
        assert results[0].backlinks == 1000

    def test_null_backlinks_does_not_overwrite_existing(self, store):
        store.upsert_many([_domain(backlinks=1000)])
        store.upsert_many([_domain(backlinks=None)])
        results = store.search()
        assert results[0].backlinks == 1000


# ------------------------------------------------------------------ #
# Upsert — drop_date updated                                         #
# ------------------------------------------------------------------ #

class TestUpsertDropDate:
    def test_drop_date_updated_on_refetch(self, store):
        dt1 = datetime(2026, 4, 20, tzinfo=timezone.utc)
        dt2 = datetime(2026, 4, 25, tzinfo=timezone.utc)
        store.upsert_many([_domain(drop_date=dt1)])
        store.upsert_many([_domain(drop_date=dt2)])
        results = store.search()
        assert results[0].drop_date is not None
        assert results[0].drop_date.day == 25

    def test_drop_date_written_when_previously_null(self, store):
        dt = datetime(2026, 4, 20, tzinfo=timezone.utc)
        store.upsert_many([_domain(drop_date=None)])
        store.upsert_many([_domain(drop_date=dt)])
        results = store.search()
        assert results[0].drop_date is not None


# ------------------------------------------------------------------ #
# get_all_fqdns                                                       #
# ------------------------------------------------------------------ #

class TestGetAllFqdns:
    def test_returns_frozenset(self, store):
        store.upsert_many([_domain(fqdn="forge.io", name="forge", tld="io")])
        result = store.get_all_fqdns()
        assert isinstance(result, frozenset)

    def test_contains_inserted_fqdns(self, store):
        store.upsert_many([
            _domain(fqdn="forge.io",  name="forge",  tld="io"),
            _domain(fqdn="pixel.dev", name="pixel",  tld="dev"),
        ])
        fqdns = store.get_all_fqdns()
        assert "forge.io"  in fqdns
        assert "pixel.dev" in fqdns

    def test_empty_store_returns_empty_frozenset(self, store):
        assert store.get_all_fqdns() == frozenset()