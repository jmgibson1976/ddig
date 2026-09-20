"""Unit tests for `ddig purge-registered` CLI command."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from ddig.__main__ import app

runner = CliRunner()


# ------------------------------------------------------------------
# fixtures
# ------------------------------------------------------------------

@pytest.fixture
def mock_store():
    with patch("ddig.__main__.DomainStore") as MockStore:
        store = MagicMock()
        store.get_all_fqdns.return_value     = frozenset(["forge.io", "atlas.me", "keep.com"])
        store.get_watchlist_fqdns.return_value = frozenset(["keep.com"])
        store.purge_fqdns.return_value       = 2
        MockStore.return_value = store
        yield MockStore, store


@pytest.fixture
def mock_nrd_source():
    with patch("ddig.__main__.NRDSource") as MockSrc:
        src = MagicMock()
        src.fetch.return_value = iter(["forge.io", "atlas.me"])
        MockSrc.return_value = src
        yield MockSrc, src


@pytest.fixture
def mock_nrd_empty():
    with patch("ddig.__main__.NRDSource") as MockSrc:
        src = MagicMock()
        src.fetch.return_value = iter([])
        MockSrc.return_value = src
        yield MockSrc, src


# ------------------------------------------------------------------
# TestPurgeRegisteredBasic
# ------------------------------------------------------------------

class TestPurgeRegisteredBasic:
    def test_exits_zero_on_success(self, mock_store, mock_nrd_source):
        result = runner.invoke(app, ["purge-registered"])
        assert result.exit_code == 0

    def test_calls_purge_fqdns(self, mock_store, mock_nrd_source):
        _, store = mock_store
        runner.invoke(app, ["purge-registered"])
        store.purge_fqdns.assert_called_once()

    def test_skips_watchlisted_domains(self, mock_store, mock_nrd_source):
        _, store = mock_store
        runner.invoke(app, ["purge-registered"])
        call_args = store.purge_fqdns.call_args
        skip_arg  = call_args[1].get("skip") or call_args[0][1]
        assert "keep.com" in skip_arg

    def test_no_matches_exits_zero(self, mock_store, mock_nrd_empty):
        result = runner.invoke(app, ["purge-registered"])
        assert result.exit_code == 0

    def test_output_shows_deleted_count(self, mock_store, mock_nrd_source):
        result = runner.invoke(app, ["purge-registered"])
        assert "2" in result.output


# ------------------------------------------------------------------
# TestPurgeRegisteredDryRun
# ------------------------------------------------------------------

class TestPurgeRegisteredDryRun:
    def test_dry_run_does_not_call_purge_fqdns(self, mock_store, mock_nrd_source):
        _, store = mock_store
        runner.invoke(app, ["purge-registered", "--dry-run"])
        store.purge_fqdns.assert_not_called()

    def test_dry_run_output_says_dry_run(self, mock_store, mock_nrd_source):
        result = runner.invoke(app, ["purge-registered", "--dry-run"])
        assert "DRY RUN" in result.output or "dry" in result.output.lower()

    def test_dry_run_exits_zero(self, mock_store, mock_nrd_source):
        result = runner.invoke(app, ["purge-registered", "--dry-run"])
        assert result.exit_code == 0


# ------------------------------------------------------------------
# TestPurgeRegisteredOptions
# ------------------------------------------------------------------

class TestPurgeRegisteredOptions:
    def test_default_source_is_all(self, mock_store, mock_nrd_source):
        MockSrc, _ = mock_nrd_source
        runner.invoke(app, ["purge-registered"])
        kwargs = MockSrc.call_args[1]
        assert kwargs["sources"] == ["nrd", "whoisds"]

    def test_source_nrd_only(self, mock_store, mock_nrd_source):
        MockSrc, _ = mock_nrd_source
        runner.invoke(app, ["purge-registered", "--source", "nrd"])
        kwargs = MockSrc.call_args[1]
        assert kwargs["sources"] == ["nrd"]

    def test_source_whoisds_only(self, mock_store, mock_nrd_source):
        MockSrc, _ = mock_nrd_source
        runner.invoke(app, ["purge-registered", "--source", "whoisds"])
        kwargs = MockSrc.call_args[1]
        assert kwargs["sources"] == ["whoisds"]

    def test_invalid_source_exits_nonzero(self, mock_store, mock_nrd_source):
        result = runner.invoke(app, ["purge-registered", "--source", "badvalue"])
        assert result.exit_code != 0