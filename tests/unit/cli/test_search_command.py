"""Unit tests for `ddig search` CLI command."""
from __future__ import annotations

import pytest
from dataclasses import replace
from typing import Any
from typer.testing import CliRunner
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from ddig.__main__ import app
from ddig.models.domain import Domain

runner = CliRunner()


def _make_domain(**kwargs: Any) -> Domain:
    domain = Domain(
        fqdn      = "forge.io",
        name      = "forge",
        tld       = "io",
        source    = "dropcatch",
        nlp_score = 0.85,
        backlinks = 1234,
        rank      = 5000,
        drop_date = datetime(2026, 4, 20, tzinfo=timezone.utc),
    )
    return replace(domain, **kwargs)


@pytest.fixture
def mock_store():
    with patch("ddig.__main__.DomainStore") as MockStore:
        store = MagicMock()
        MockStore.return_value = store
        yield store


# ------------------------------------------------------------------ #
# Output                                                              #
# ------------------------------------------------------------------ #

class TestSearchOutput:
    def test_no_results_message(self, mock_store):
        mock_store.search.return_value = []
        result = runner.invoke(app, ["search"])
        assert result.exit_code == 0
        assert "No domains" in result.output or "no" in result.output.lower()

    def test_shows_fqdn(self, mock_store):
        mock_store.search.return_value = [_make_domain()]
        result = runner.invoke(app, ["search"])
        assert result.exit_code == 0
        assert "forge.io" in result.output

    def test_shows_multiple_results(self, mock_store):
        mock_store.search.return_value = [
            _make_domain(fqdn="forge.io",  name="forge"),
            _make_domain(fqdn="pixel.dev", name="pixel", tld="dev"),
        ]
        result = runner.invoke(app, ["search"])
        assert result.exit_code == 0
        assert "forge.io"  in result.output
        assert "pixel.dev" in result.output

    def test_shows_result_count(self, mock_store):
        mock_store.search.return_value = [_make_domain()]
        result = runner.invoke(app, ["search"])
        assert result.exit_code == 0
        assert "1" in result.output

    def test_exit_code_zero_on_success(self, mock_store):
        mock_store.search.return_value = [_make_domain()]
        result = runner.invoke(app, ["search"])
        assert result.exit_code == 0

    def test_exit_code_zero_on_empty(self, mock_store):
        mock_store.search.return_value = []
        result = runner.invoke(app, ["search"])
        assert result.exit_code == 0


# ------------------------------------------------------------------ #
# Filters passed to store.search                                      #
# ------------------------------------------------------------------ #

class TestSearchFilters:
    def test_tld_passed(self, mock_store):
        mock_store.search.return_value = []
        runner.invoke(app, ["search", "--tld", "io"])
        kwargs = mock_store.search.call_args[1]
        assert kwargs["tld"] == "io"

    def test_min_score_passed(self, mock_store):
        mock_store.search.return_value = []
        runner.invoke(app, ["search", "--min-score", "0.7"])
        kwargs = mock_store.search.call_args[1]
        assert kwargs["min_score"] == pytest.approx(0.7)

    def test_within_passed(self, mock_store):
        mock_store.search.return_value = []
        runner.invoke(app, ["search", "--within", "7"])
        kwargs = mock_store.search.call_args[1]
        assert kwargs["within_days"] == 7

    def test_limit_passed(self, mock_store):
        mock_store.search.return_value = []
        runner.invoke(app, ["search", "--limit", "25"])
        kwargs = mock_store.search.call_args[1]
        assert kwargs["limit"] == 25

    def test_no_hyphens_passed(self, mock_store):
        mock_store.search.return_value = []
        runner.invoke(app, ["search", "--no-hyphens"])
        kwargs = mock_store.search.call_args[1]
        assert kwargs["no_hyphens"] is True

    def test_no_numbers_passed(self, mock_store):
        mock_store.search.return_value = []
        runner.invoke(app, ["search", "--no-numbers"])
        kwargs = mock_store.search.call_args[1]
        assert kwargs["no_numbers"] is True

    def test_real_words_passed(self, mock_store):
        mock_store.search.return_value = []
        runner.invoke(app, ["search", "--real-words"])
        kwargs = mock_store.search.call_args[1]
        assert kwargs["real_words"] is True

    def test_sort_passed(self, mock_store):
        mock_store.search.return_value = []
        runner.invoke(app, ["search", "--sort", "backlinks"])
        kwargs = mock_store.search.call_args[1]
        assert kwargs["sort"] == "backlinks"

    def test_source_passed(self, mock_store):
        mock_store.search.return_value = []
        runner.invoke(app, ["search", "--source", "dropcatch"])
        kwargs = mock_store.search.call_args[1]
        assert kwargs["source"] == "dropcatch"

    def test_max_length_passed(self, mock_store):
        mock_store.search.return_value = []
        runner.invoke(app, ["search", "--max-length", "6"])
        kwargs = mock_store.search.call_args[1]
        assert kwargs["max_length"] == 6

    def test_min_backlinks_passed(self, mock_store):
        mock_store.search.return_value = []
        runner.invoke(app, ["search", "--min-backlinks", "1000"])
        kwargs = mock_store.search.call_args[1]
        assert kwargs["min_backlinks"] == 1000

    def test_max_rank_passed(self, mock_store):
        mock_store.search.return_value = []
        runner.invoke(app, ["search", "--max-rank", "50000"])
        kwargs = mock_store.search.call_args[1]
        assert kwargs["max_rank"] == 50000

    def test_calls_store_search_once(self, mock_store):
        mock_store.search.return_value = []
        runner.invoke(app, ["search"])
        mock_store.search.assert_called_once()