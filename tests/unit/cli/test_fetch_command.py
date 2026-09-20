"""Unit tests for `ddig fetch` CLI command."""
from __future__ import annotations

import pytest
from dataclasses import replace
from typer.testing import CliRunner
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from ddig.__main__ import app
from ddig.models.domain import Domain

runner = CliRunner()


def _domain(**kwargs) -> Domain:
    base = Domain(
        fqdn      = "forge.io",
        name      = "forge",
        tld       = "io",
        source    = "dropcatch",
        drop_date = datetime(2026, 4, 20, tzinfo=timezone.utc),
    )
    return replace(base, **kwargs)


@pytest.fixture
def mock_store():
    with patch("ddig.__main__.DomainStore") as MockStore:
        store = MagicMock()
        store.upsert_many.return_value = 1
        MockStore.return_value = store
        yield store


@pytest.fixture
def mock_dropcatch():
    with patch("ddig.__main__.DropCatchSource") as MockSrc:
        src = MagicMock()
        src.fetch.return_value = iter([_domain()])
        MockSrc.return_value = src
        yield MockSrc, src


@pytest.fixture
def mock_expireddomains():
    with patch("ddig.__main__.ExpiredDomainsSource") as MockSrc:
        src = MagicMock()
        src.fetch.return_value = iter([_domain(source="expireddomains")])
        MockSrc.return_value = src
        yield MockSrc, src


@pytest.fixture
def mock_czds():
    with patch("ddig.__main__.CZDSSource") as MockSrc:
        src = MagicMock()
        src.fetch.return_value = iter([_domain(source="czds")])
        MockSrc.return_value = src
        yield MockSrc, src


@pytest.fixture
def mock_majestic():
    with patch("ddig.__main__.MajesticMillionSource") as MockSrc:
        src = MagicMock()
        src.fetch.return_value = iter([_domain(source="majestic")])
        MockSrc.return_value = src
        yield MockSrc, src


@pytest.fixture
def mock_snapnames():
    with patch("ddig.__main__.SnapNamesSource") as MockSrc:
        src = MagicMock()
        src.fetch.return_value = iter([_domain(source="snapnames")])
        MockSrc.return_value = src
        yield MockSrc, src


@pytest.fixture
def mock_parkio():
    with patch("ddig.__main__.ParkIOSource") as MockSrc:
        src = MagicMock()
        src.fetch.return_value = iter([_domain(source="parkio")])
        MockSrc.return_value = src
        yield MockSrc, src


# ------------------------------------------------------------------ #
# Source routing                                                      #
# ------------------------------------------------------------------ #

class TestFetchSourceRouting:
    def test_dropcatch_source_used(self, mock_store, mock_dropcatch):
        MockSrc, src = mock_dropcatch
        result = runner.invoke(app, ["fetch", "--source", "dropcatch"])
        assert result.exit_code == 0
        MockSrc.assert_called_once()

    def test_expireddomains_source_used(self, mock_store, mock_expireddomains):
        MockSrc, src = mock_expireddomains
        result = runner.invoke(app, ["fetch", "--source", "expireddomains"])
        assert result.exit_code == 0
        MockSrc.assert_called_once()

    def test_czds_source_used(self, mock_store, mock_czds):
        MockSrc, src = mock_czds
        result = runner.invoke(app, ["fetch", "--source", "czds"])
        assert result.exit_code == 0
        MockSrc.assert_called_once()

    def test_majestic_source_used(self, mock_store, mock_majestic):
        MockSrc, src = mock_majestic
        result = runner.invoke(app, ["fetch", "--source", "majestic"])
        assert result.exit_code == 0
        MockSrc.assert_called_once()

    def test_snapnames_source_used(self, mock_store, mock_snapnames):
        MockSrc, src = mock_snapnames
        result = runner.invoke(app, ["fetch", "--source", "snapnames"])
        assert result.exit_code == 0
        MockSrc.assert_called_once()

    def test_unknown_source_exits_nonzero(self, mock_store):
        result = runner.invoke(app, ["fetch", "--source", "unknown"])
        assert result.exit_code != 0

    def test_unknown_source_shows_error(self, mock_store):
        result = runner.invoke(app, ["fetch", "--source", "unknown"])
        assert "unknown" in result.output.lower() or "Unknown" in result.output


# ------------------------------------------------------------------ #
# dropcatch options                                                   #
# ------------------------------------------------------------------ #

class TestFetchDropcatchOptions:
    def test_default_feed_is_dropping_today(self, mock_store, mock_dropcatch):
        MockSrc, src = mock_dropcatch
        runner.invoke(app, ["fetch", "--source", "dropcatch"])
        kwargs = MockSrc.call_args[1]
        assert kwargs["feed"] == "dropping-today"

    def test_custom_feed_passed(self, mock_store, mock_dropcatch):
        MockSrc, src = mock_dropcatch
        runner.invoke(app, ["fetch", "--source", "dropcatch", "--feed", "dropping-soon"])
        kwargs = MockSrc.call_args[1]
        assert kwargs["feed"] == "dropping-soon"


# ------------------------------------------------------------------ #
# expireddomains options                                              #
# ------------------------------------------------------------------ #

class TestFetchExpiredDomainsOptions:
    def test_default_feed_is_deleted(self, mock_store, mock_expireddomains):
        MockSrc, src = mock_expireddomains
        runner.invoke(app, ["fetch", "--source", "expireddomains"])
        kwargs = MockSrc.call_args[1]
        assert kwargs["list_name"] == "deleted"

    def test_pages_passed(self, mock_store, mock_expireddomains):
        MockSrc, src = mock_expireddomains
        runner.invoke(app, ["fetch", "--source", "expireddomains", "--pages", "3"])
        kwargs = MockSrc.call_args[1]
        assert kwargs["max_pages"] == 3

    def test_tld_passed(self, mock_store, mock_expireddomains):
        MockSrc, src = mock_expireddomains
        runner.invoke(app, ["fetch", "--source", "expireddomains", "--tld", "com"])
        kwargs = MockSrc.call_args[1]
        assert kwargs["tld"] == "com"

    def test_headless_default_is_true(self, mock_store, mock_expireddomains):
        MockSrc, src = mock_expireddomains
        runner.invoke(app, ["fetch", "--source", "expireddomains"])
        kwargs = MockSrc.call_args[1]
        assert kwargs["headless"] is True

    def test_no_headless_flag(self, mock_store, mock_expireddomains):
        MockSrc, src = mock_expireddomains
        runner.invoke(app, ["fetch", "--source", "expireddomains", "--no-headless"])
        kwargs = MockSrc.call_args[1]
        assert kwargs["headless"] is False


# ------------------------------------------------------------------ #
# czds options                                                        #
# ------------------------------------------------------------------ #

class TestFetchCzdsOptions:
    def test_tlds_parsed_as_list(self, mock_store, mock_czds):
        MockSrc, src = mock_czds
        runner.invoke(app, ["fetch", "--source", "czds", "--tlds", "app,dev,io"])
        kwargs = MockSrc.call_args[1]
        assert kwargs["tlds"] == ["app", "dev", "io"]

    def test_no_tlds_passes_none(self, mock_store, mock_czds):
        MockSrc, src = mock_czds
        runner.invoke(app, ["fetch", "--source", "czds"])
        kwargs = MockSrc.call_args[1]
        assert kwargs["tlds"] is None

    def test_max_tlds_passed(self, mock_store, mock_czds):
        MockSrc, src = mock_czds
        runner.invoke(app, ["fetch", "--source", "czds", "--max-tlds", "5"])
        kwargs = MockSrc.call_args[1]
        assert kwargs["max_tlds"] == 5


# ------------------------------------------------------------------ #
# majestic options                                                    #
# ------------------------------------------------------------------ #

class TestFetchMajesticOptions:
    def test_limit_passed(self, mock_store, mock_majestic):
        MockSrc, src = mock_majestic
        runner.invoke(app, ["fetch", "--source", "majestic", "--limit", "10000"])
        kwargs = MockSrc.call_args[1]
        assert kwargs["limit"] == 10000

    def test_min_rank_passed(self, mock_store, mock_majestic):
        MockSrc, src = mock_majestic
        runner.invoke(app, ["fetch", "--source", "majestic", "--min-rank", "100000"])
        kwargs = MockSrc.call_args[1]
        assert kwargs["min_rank"] == 100000

    def test_max_rank_passed(self, mock_store, mock_majestic):
        MockSrc, src = mock_majestic
        runner.invoke(app, ["fetch", "--source", "majestic", "--max-rank", "500000"])
        kwargs = MockSrc.call_args[1]
        assert kwargs["max_rank"] == 500000


# ------------------------------------------------------------------ #
# parkio options                                                      #
# ------------------------------------------------------------------ #

class TestFetchParkIOOptions:
    def test_no_tlds_passes_none(self, mock_store, mock_parkio):
        MockSrc, src = mock_parkio
        runner.invoke(app, ["fetch", "--source", "parkio"])
        kwargs = MockSrc.call_args[1]
        assert kwargs["tlds"] is None

    def test_tlds_parsed_as_list(self, mock_store, mock_parkio):
        MockSrc, src = mock_parkio
        runner.invoke(app, ["fetch", "--source", "parkio", "--tlds", "io,co,me"])
        kwargs = MockSrc.call_args[1]
        assert kwargs["tlds"] == ["io", "co", "me"]


# ------------------------------------------------------------------ #
# snapnames options                                                   #
# ------------------------------------------------------------------ #

class TestFetchSnapNamesOptions:
    def test_feed_passed(self, mock_store, mock_snapnames):
        MockSrc, src = mock_snapnames
        runner.invoke(app, ["fetch", "--source", "snapnames", "--feed", "allexpiring"])
        kwargs = MockSrc.call_args[1]
        assert kwargs["feed"] == "allexpiring"

    def test_no_feed_passes_none(self, mock_store, mock_snapnames):
        MockSrc, src = mock_snapnames
        runner.invoke(app, ["fetch", "--source", "snapnames"])
        kwargs = MockSrc.call_args[1]
        assert kwargs["feed"] is None

# ------------------------------------------------------------------ #
# --score flag                                                        #
# ------------------------------------------------------------------ #

class TestFetchScoreFlag:
    def test_score_flag_triggers_scoring(self, mock_store, mock_dropcatch):
        _, src = mock_dropcatch
        with patch("ddig.__main__.DomainScorer") as MockScorer:
            scorer = MagicMock()
            scorer.score_many.return_value = [_domain(nlp_score=0.85)]
            MockScorer.return_value = scorer
            result = runner.invoke(app, ["fetch", "--source", "dropcatch", "--score"])
            assert result.exit_code == 0
            scorer.score_many.assert_called_once()

    def test_no_score_flag_skips_scoring(self, mock_store, mock_dropcatch):
        _, src = mock_dropcatch
        with patch("ddig.__main__.DomainScorer") as MockScorer:
            scorer = MagicMock()
            MockScorer.return_value = scorer
            runner.invoke(app, ["fetch", "--source", "dropcatch"])
            scorer.score_many.assert_not_called()

    def test_score_not_called_on_empty_fetch(self, mock_store, mock_dropcatch):
        MockSrc, src = mock_dropcatch
        src.fetch.return_value = iter([])
        with patch("ddig.__main__.DomainScorer") as MockScorer:
            scorer = MagicMock()
            MockScorer.return_value = scorer
            runner.invoke(app, ["fetch", "--source", "dropcatch", "--score"])
            scorer.score_many.assert_not_called()


# ------------------------------------------------------------------ #
# Store interaction                                                   #
# ------------------------------------------------------------------ #

class TestFetchStoreInteraction:
    def test_upsert_many_called(self, mock_store, mock_dropcatch):
        result = runner.invoke(app, ["fetch", "--source", "dropcatch"])
        assert result.exit_code == 0
        mock_store.upsert_many.assert_called_once()

    def test_domains_passed_to_upsert(self, mock_store, mock_dropcatch):
        MockSrc, src = mock_dropcatch
        domains = [
            _domain(fqdn="forge.io",  name="forge"),
            _domain(fqdn="pixel.dev", name="pixel", tld="dev"),
        ]
        src.fetch.return_value = iter(domains)
        runner.invoke(app, ["fetch", "--source", "dropcatch"])
        passed = mock_store.upsert_many.call_args[0][0]
        fqdns = {d.fqdn for d in passed}
        assert fqdns == {"forge.io", "pixel.dev"}

    def test_db_option_passed_to_store(self, tmp_path, mock_dropcatch):
        with patch("ddig.__main__.DomainStore") as MockStore:
            store = MagicMock()
            store.upsert_many.return_value = 0
            MockStore.return_value = store
            runner.invoke(app, ["fetch", "--source", "dropcatch", "--db", str(tmp_path / "test.db")])
            MockStore.assert_called_once_with(db_path=tmp_path / "test.db")


# ------------------------------------------------------------------ #
# Output                                                              #
# ------------------------------------------------------------------ #

class TestFetchOutput:
    def test_shows_fetch_count(self, mock_store, mock_dropcatch):
        MockSrc, src = mock_dropcatch
        src.fetch.return_value = iter([
            _domain(),
            _domain(fqdn="pixel.dev", name="pixel", tld="dev"),
        ])
        result = runner.invoke(app, ["fetch", "--source", "dropcatch"])
        assert result.exit_code == 0
        assert "2" in result.output

    def test_shows_source_name(self, mock_store, mock_dropcatch):
        result = runner.invoke(app, ["fetch", "--source", "dropcatch"])
        assert result.exit_code == 0
        assert "dropcatch" in result.output

    def test_verbose_flag_accepted(self, mock_store, mock_dropcatch):
        result = runner.invoke(app, ["fetch", "--source", "dropcatch", "--verbose"])
        assert result.exit_code == 0