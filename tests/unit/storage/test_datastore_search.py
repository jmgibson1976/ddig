"""Unit tests for DomainStore.search() filters."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from ddig.models.domain import Domain
from ddig.storage.datastore import DomainStore


# ------------------------------------------------------------------ #
# Fixtures                                                            #
# ------------------------------------------------------------------ #

@pytest.fixture
def store(tmp_path: Path) -> DomainStore:
    return DomainStore(db_path=tmp_path / "test.db")


@pytest.fixture
def populated_store(store: DomainStore) -> DomainStore:
    """Store pre-loaded with a known set of domains."""
    now = datetime.now(timezone.utc)
    domains = [
        Domain(name="apple",    tld="com",  fqdn="apple.com",    source="dropcatch",
               nlp_score=0.9,  is_real_word=True,  backlinks=5000,  rank=100,
               drop_date=now + timedelta(days=5)),
        Domain(name="banana",   tld="com",  fqdn="banana.com",   source="dropcatch",
               nlp_score=0.8,  is_real_word=True,  backlinks=3000,  rank=200,
               drop_date=now + timedelta(days=15)),
        Domain(name="xyz123",   tld="com",  fqdn="xyz123.com",   source="majestic",
               nlp_score=0.3,  is_real_word=False, backlinks=100,   rank=50000,
               drop_date=None),
        Domain(name="cool-app", tld="io",   fqdn="cool-app.io",  source="majestic",
               nlp_score=0.7,  is_real_word=False, backlinks=800,   rank=5000,
               drop_date=now + timedelta(days=3)),
        Domain(name="forge",    tld="io",   fqdn="forge.io",     source="czds",
               nlp_score=0.85, is_real_word=True,  backlinks=9000,  rank=75,
               drop_date=None),
        Domain(name="pixel",    tld="dev",  fqdn="pixel.dev",    source="czds",
               nlp_score=0.75, is_real_word=True,  backlinks=2000,  rank=300,
               drop_date=now + timedelta(days=60)),
        Domain(name="bit",      tld="ly",   fqdn="bit.ly",       source="majestic",
               nlp_score=0.6,  is_real_word=True,  backlinks=50000, rank=33,
               drop_date=None),
        Domain(name="a2z",      tld="net",  fqdn="a2z.net",      source="dropcatch",
               nlp_score=0.4,  is_real_word=False, backlinks=None,  rank=None,
               drop_date=now + timedelta(days=2)),
    ]
    store.upsert_many(domains)
    return store


# ------------------------------------------------------------------ #
# No filters — returns all up to limit                               #
# ------------------------------------------------------------------ #

class TestSearchNoFilters:
    def test_returns_all_domains(self, populated_store: DomainStore):
        results = populated_store.search(limit=100)
        assert len(results) == 8

    def test_respects_limit(self, populated_store: DomainStore):
        results = populated_store.search(limit=3)
        assert len(results) == 3

    def test_default_sort_is_nlp_score_desc(self, populated_store: DomainStore):
        results = populated_store.search(limit=100)
        scores  = [r.nlp_score for r in results if r.nlp_score is not None]
        assert scores == sorted(scores, reverse=True)

    def test_none_scores_sorted_last(self, populated_store: DomainStore):
        results = populated_store.search(limit=100)
        scores  = [r.nlp_score for r in results]
        none_indices = [i for i, s in enumerate(scores) if s is None]
        non_none     = [i for i, s in enumerate(scores) if s is not None]
        if none_indices and non_none:
            assert max(non_none) < min(none_indices)

    def test_returns_domain_objects(self, populated_store: DomainStore):
        results = populated_store.search(limit=10)
        assert all(isinstance(r, Domain) for r in results)

    def test_empty_store_returns_empty_list(self, store: DomainStore):
        results = store.search()
        assert results == []


# ------------------------------------------------------------------ #
# name filter                                                         #
# ------------------------------------------------------------------ #

class TestSearchName:
    def test_exact_match(self, populated_store: DomainStore):
        results = populated_store.search(name="apple")
        assert len(results) == 1
        assert results[0].fqdn == "apple.com"

    def test_partial_match(self, populated_store: DomainStore):
        results = populated_store.search(name="an")   # banana
        fqdns   = {r.fqdn for r in results}
        assert "banana.com" in fqdns

    def test_case_insensitive(self, populated_store: DomainStore):
        results = populated_store.search(name="APPLE")
        assert len(results) == 1
        assert results[0].name == "apple"

    def test_no_match_returns_empty(self, populated_store: DomainStore):
        results = populated_store.search(name="zzznomatch")
        assert results == []


# ------------------------------------------------------------------ #
# tld filter                                                          #
# ------------------------------------------------------------------ #

class TestSearchTld:
    def test_filters_by_tld(self, populated_store: DomainStore):
        results = populated_store.search(tld="io", limit=100)
        assert all(r.tld == "io" for r in results)
        assert len(results) == 2

    def test_tld_strips_leading_dot(self, populated_store: DomainStore):
        results = populated_store.search(tld=".com", limit=100)
        assert all(r.tld == "com" for r in results)

    def test_tld_no_match(self, populated_store: DomainStore):
        results = populated_store.search(tld="xyz")
        assert results == []


# ------------------------------------------------------------------ #
# source filter                                                       #
# ------------------------------------------------------------------ #

class TestSearchSource:
    def test_filters_by_source(self, populated_store: DomainStore):
        results = populated_store.search(source="czds", limit=100)
        assert all("czds" in r.source for r in results)
        assert len(results) == 2

    def test_source_case_insensitive(self, populated_store: DomainStore):
        results = populated_store.search(source="CZDS", limit=100)
        assert len(results) == 2

    def test_source_partial_match(self, populated_store: DomainStore):
        results = populated_store.search(source="drop", limit=100)
        assert all("dropcatch" in r.source for r in results)

    def test_source_no_match(self, populated_store: DomainStore):
        results = populated_store.search(source="nonexistent")
        assert results == []


# ------------------------------------------------------------------ #
# min_score filter                                                    #
# ------------------------------------------------------------------ #

class TestSearchMinScore:
    def test_filters_below_threshold(self, populated_store: DomainStore):
        results = populated_store.search(min_score=0.8, limit=100)
        assert all(r.nlp_score is not None and r.nlp_score >= 0.8 for r in results)

    def test_exact_threshold_included(self, populated_store: DomainStore):
        results = populated_store.search(min_score=0.9, limit=100)
        fqdns   = {r.fqdn for r in results}
        assert "apple.com" in fqdns

    def test_high_threshold_returns_fewer(self, populated_store: DomainStore):
        all_results  = populated_store.search(limit=100)
        high_results = populated_store.search(min_score=0.85, limit=100)
        assert len(high_results) < len(all_results)


# ------------------------------------------------------------------ #
# max_length filter                                                   #
# ------------------------------------------------------------------ #

class TestSearchMaxLength:
    def test_filters_long_names(self, populated_store: DomainStore):
        results = populated_store.search(max_length=3, limit=100)
        assert all(len(r.name) <= 3 for r in results)

    def test_exact_length_included(self, populated_store: DomainStore):
        results = populated_store.search(max_length=3, limit=100)
        fqdns   = {r.fqdn for r in results}
        assert "bit.ly" in fqdns      # "bit" = 3 chars

    def test_length_5_excludes_banana(self, populated_store: DomainStore):
        results = populated_store.search(max_length=5, limit=100)
        fqdns   = {r.fqdn for r in results}
        assert "banana.com" not in fqdns   # "banana" = 6 chars


# ------------------------------------------------------------------ #
# min_backlinks filter                                                #
# ------------------------------------------------------------------ #

class TestSearchMinBacklinks:
    def test_filters_below_threshold(self, populated_store: DomainStore):
        results = populated_store.search(min_backlinks=5000, limit=100)
        assert all(r.backlinks is not None and r.backlinks >= 5000 for r in results)

    def test_exact_threshold_included(self, populated_store: DomainStore):
        results = populated_store.search(min_backlinks=5000, limit=100)
        fqdns   = {r.fqdn for r in results}
        assert "apple.com" in fqdns

    def test_null_backlinks_excluded(self, populated_store: DomainStore):
        results = populated_store.search(min_backlinks=1, limit=100)
        fqdns   = {r.fqdn for r in results}
        assert "a2z.net" not in fqdns

    def test_high_threshold(self, populated_store: DomainStore):
        results = populated_store.search(min_backlinks=10000, limit=100)
        fqdns   = {r.fqdn for r in results}
        assert "bit.ly"    in fqdns
        assert "apple.com" not in fqdns


# ------------------------------------------------------------------ #
# min_rank / max_rank filters                                        #
# ------------------------------------------------------------------ #

class TestSearchRankFilters:
    def test_max_rank_filters(self, populated_store: DomainStore):
        results = populated_store.search(max_rank=100, limit=100)
        assert all(r.rank is not None and r.rank <= 100 for r in results)

    def test_max_rank_excludes_null(self, populated_store: DomainStore):
        results = populated_store.search(max_rank=100, limit=100)
        fqdns   = {r.fqdn for r in results}
        assert "a2z.net" not in fqdns

    def test_min_rank_filters(self, populated_store: DomainStore):
        results = populated_store.search(min_rank=1000, limit=100)
        assert all(r.rank is not None and r.rank >= 1000 for r in results)

    def test_min_and_max_rank_combined(self, populated_store: DomainStore):
        results = populated_store.search(min_rank=100, max_rank=500, limit=100)
        for r in results:
            assert r.rank is not None
            assert 100 <= r.rank <= 500

    def test_rank_33_in_top_100(self, populated_store: DomainStore):
        results = populated_store.search(max_rank=100, limit=100)
        fqdns   = {r.fqdn for r in results}
        assert "bit.ly"   in fqdns
        assert "forge.io" in fqdns


# ------------------------------------------------------------------ #
# within_days filter                                                  #
# ------------------------------------------------------------------ #

class TestSearchWithinDays:
    def test_within_7_days(self, populated_store: DomainStore):
        results = populated_store.search(within_days=7, limit=100)
        fqdns   = {r.fqdn for r in results}
        assert "apple.com"   in fqdns   # drops in 5 days
        assert "cool-app.io" in fqdns   # drops in 3 days
        assert "a2z.net"     in fqdns   # drops in 2 days
        assert "banana.com"  not in fqdns  # drops in 15 days

    def test_no_drop_date_excluded(self, populated_store: DomainStore):
        results = populated_store.search(within_days=30, limit=100)
        fqdns   = {r.fqdn for r in results}
        assert "forge.io" not in fqdns  # drop_date=None
        assert "bit.ly"   not in fqdns  # drop_date=None

    def test_within_1_day(self, populated_store: DomainStore):
        results = populated_store.search(within_days=1, limit=100)
        fqdns   = {r.fqdn for r in results}
        assert "a2z.net" not in fqdns    # drops in 2 days — outside 1 day window
        assert "pixel.dev" not in fqdns  # drops in 60 days


# ------------------------------------------------------------------ #
# real_words filter                                                   #
# ------------------------------------------------------------------ #

class TestSearchRealWords:
    def test_only_real_words_returned(self, populated_store: DomainStore):
        results = populated_store.search(real_words=True, limit=100)
        assert all(r.is_real_word is True for r in results)

    def test_non_real_word_excluded(self, populated_store: DomainStore):
        results = populated_store.search(real_words=True, limit=100)
        fqdns   = {r.fqdn for r in results}
        assert "xyz123.com"  not in fqdns
        assert "cool-app.io" not in fqdns

    def test_real_words_included(self, populated_store: DomainStore):
        results = populated_store.search(real_words=True, limit=100)
        fqdns   = {r.fqdn for r in results}
        assert "apple.com"  in fqdns
        assert "banana.com" in fqdns
        assert "forge.io"   in fqdns


# ------------------------------------------------------------------ #
# no_hyphens filter                                                   #
# ------------------------------------------------------------------ #

class TestSearchNoHyphens:
    def test_excludes_hyphenated(self, populated_store: DomainStore):
        results = populated_store.search(no_hyphens=True, limit=100)
        fqdns   = {r.fqdn for r in results}
        assert "cool-app.io" not in fqdns

    def test_non_hyphenated_included(self, populated_store: DomainStore):
        results = populated_store.search(no_hyphens=True, limit=100)
        fqdns   = {r.fqdn for r in results}
        assert "apple.com" in fqdns
        assert "forge.io"  in fqdns


# ------------------------------------------------------------------ #
# no_numbers filter                                                   #
# ------------------------------------------------------------------ #

class TestSearchNoNumbers:
    def test_excludes_domains_with_numbers(self, populated_store: DomainStore):
        results = populated_store.search(no_numbers=True, limit=100)
        fqdns   = {r.fqdn for r in results}
        assert "xyz123.com" not in fqdns
        assert "a2z.net"    not in fqdns

    def test_clean_domains_included(self, populated_store: DomainStore):
        results = populated_store.search(no_numbers=True, limit=100)
        fqdns   = {r.fqdn for r in results}
        assert "apple.com"  in fqdns
        assert "forge.io"   in fqdns
        assert "bit.ly"     in fqdns


# ------------------------------------------------------------------ #
# combined filters                                                    #
# ------------------------------------------------------------------ #

class TestSearchCombinedFilters:
    def test_tld_and_min_score(self, populated_store: DomainStore):
        results = populated_store.search(tld="com", min_score=0.8, limit=100)
        assert all(r.tld == "com" for r in results)
        assert all(r.nlp_score is not None and r.nlp_score >= 0.8 for r in results)

    def test_real_words_no_hyphens_no_numbers(self, populated_store: DomainStore):
        results = populated_store.search(
            real_words=True, no_hyphens=True, no_numbers=True, limit=100
        )
        for r in results:
            assert r.is_real_word is True
            assert "-" not in r.name
            assert not any(c.isdigit() for c in r.name)

    def test_max_length_and_min_backlinks(self, populated_store: DomainStore):
        results = populated_store.search(max_length=5, min_backlinks=1000, limit=100)
        for r in results:
            assert len(r.name) <= 5
            assert r.backlinks is not None
            assert r.backlinks >= 1000

    def test_all_filters_combined(self, populated_store: DomainStore):
        results = populated_store.search(
            tld           = "com",
            min_score     = 0.7,
            max_length    = 6,
            no_hyphens    = True,
            no_numbers    = True,
            real_words    = True,
            min_backlinks = 1000,
            limit         = 100,
        )
        for r in results:
            assert r.tld          == "com"
            assert r.nlp_score    is not None and r.nlp_score >= 0.7
            assert len(r.name)    <= 6
            assert "-"            not in r.name
            assert not any(c.isdigit() for c in r.name)
            assert r.is_real_word is True
            assert r.backlinks    is not None and r.backlinks >= 1000


# ------------------------------------------------------------------ #
# search sort                                                         #
# ------------------------------------------------------------------ #

class TestSearchSort:
    def test_default_sort_is_score(self, populated_store: DomainStore):
        results = populated_store.search(limit=100)
        scores  = [r.nlp_score for r in results if r.nlp_score is not None]
        assert scores == sorted(scores, reverse=True)

    def test_sort_score_explicit(self, populated_store: DomainStore):
        results = populated_store.search(sort="score", limit=100)
        scores  = [r.nlp_score for r in results if r.nlp_score is not None]
        assert scores == sorted(scores, reverse=True)

    def test_sort_rank_asc(self, populated_store: DomainStore):
        results = populated_store.search(sort="rank", limit=100)
        ranks   = [r.rank for r in results if r.rank is not None]
        assert ranks == sorted(ranks)

    def test_sort_backlinks_desc(self, populated_store: DomainStore):
        results = populated_store.search(sort="backlinks", limit=100)
        bl      = [r.backlinks for r in results if r.backlinks is not None]
        assert bl == sorted(bl, reverse=True)

    def test_sort_drop_asc(self, populated_store: DomainStore):
        results = populated_store.search(sort="drop", limit=100)
        drops   = [r.drop_date for r in results if r.drop_date is not None]
        assert drops == sorted(drops)

    def test_sort_rank_nulls_last(self, populated_store: DomainStore):
        results = populated_store.search(sort="rank", limit=100)
        ranks   = [r.rank for r in results]
        none_indices    = [i for i, r in enumerate(ranks) if r is None]
        non_none_indices = [i for i, r in enumerate(ranks) if r is not None]
        if none_indices and non_none_indices:
            assert max(non_none_indices) < min(none_indices)

    def test_sort_backlinks_nulls_last(self, populated_store: DomainStore):
        results = populated_store.search(sort="backlinks", limit=100)
        bls     = [r.backlinks for r in results]
        none_indices     = [i for i, b in enumerate(bls) if b is None]
        non_none_indices = [i for i, b in enumerate(bls) if b is not None]
        if none_indices and non_none_indices:
            assert max(non_none_indices) < min(none_indices)