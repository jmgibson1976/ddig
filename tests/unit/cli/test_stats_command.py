"""Unit tests for `ddig stats` CLI command."""
from __future__ import annotations

import pytest
from typer.testing import CliRunner
from unittest.mock import patch, MagicMock

from ddig.__main__ import app

runner = CliRunner()


@pytest.fixture
def mock_store():
    with patch("ddig.__main__.DomainStore") as MockStore:
        store = MagicMock()
        MockStore.return_value = store
        yield store


def _make_stats(**kwargs) -> dict:
    defaults = dict(
        total      = 488_702,
        scored     = 488_702,                          # matches stats() key
        by_source  = {"dropcatch": 487_341, "czds": 1_332, "expireddomains": 29},
        by_tld     = {"com": 367_201, "net": 24_355, "org": 22_159},
    )
    defaults.update(kwargs)
    return defaults


# ------------------------------------------------------------------ #
# Output                                                              #
# ------------------------------------------------------------------ #

class TestStatsOutput:
    def test_exit_code_zero(self, mock_store):
        mock_store.stats.return_value = _make_stats()
        result = runner.invoke(app, ["stats"])
        assert result.exit_code == 0

    def test_shows_total_count(self, mock_store):
        mock_store.stats.return_value = _make_stats(total=12345)
        result = runner.invoke(app, ["stats"])
        assert result.exit_code == 0
        assert "12" in result.output

    def test_shows_source_names(self, mock_store):
        mock_store.stats.return_value = _make_stats(
            by_source={"dropcatch": 100, "expireddomains": 50}
        )
        result = runner.invoke(app, ["stats"])
        assert result.exit_code == 0
        assert "dropcatch"      in result.output
        assert "expireddomains" in result.output

    def test_shows_tld_names(self, mock_store):
        mock_store.stats.return_value = _make_stats(
            by_tld={"com": 100, "io": 50}
        )
        result = runner.invoke(app, ["stats"])
        assert result.exit_code == 0
        assert "com" in result.output
        assert "io"  in result.output

    def test_shows_nlp_scored(self, mock_store):
        mock_store.stats.return_value = _make_stats(scored=99999)
        result = runner.invoke(app, ["stats"])
        assert result.exit_code == 0
        assert "99" in result.output

    def test_calls_store_stats_once(self, mock_store):
        mock_store.stats.return_value = _make_stats()
        runner.invoke(app, ["stats"])
        mock_store.stats.assert_called_once()

    def test_empty_db_shows_zero(self, mock_store):
        mock_store.stats.return_value = _make_stats(
            total=0, scored=0, by_source={}, by_tld={}
        )
        result = runner.invoke(app, ["stats"])
        assert result.exit_code == 0
        assert "0" in result.output