"""Unit tests for `ddig watch` CLI subcommands."""
from __future__ import annotations

import pytest
from typer.testing import CliRunner
from unittest.mock import patch, MagicMock

from ddig.__main__ import app
from ddig.models.domain import Domain

runner = CliRunner()


@pytest.fixture
def mock_store():
    with patch("ddig.__main__.DomainStore") as MockStore:
        store = MagicMock()
        MockStore.return_value = store
        yield store


# ------------------------------------------------------------------ #
# watch add                                                           #
# ------------------------------------------------------------------ #

class TestWatchAddCommand:
    def test_add_single_domain(self, mock_store):
        mock_store.watch_add.return_value = ["forge.io"]
        result = runner.invoke(app, ["watch", "add", "forge.io"])
        assert result.exit_code == 0
        assert "forge.io" in result.output

    def test_add_multiple_domains(self, mock_store):
        mock_store.watch_add.return_value = ["forge.io", "pixel.dev"]
        result = runner.invoke(app, ["watch", "add", "forge.io", "pixel.dev"])
        assert result.exit_code == 0
        assert "forge.io"  in result.output
        assert "pixel.dev" in result.output

    def test_already_watching_message(self, mock_store):
        mock_store.watch_add.return_value = []
        result = runner.invoke(app, ["watch", "add", "forge.io"])
        assert result.exit_code == 0
        assert "Already watching" in result.output

    def test_calls_store_watch_add(self, mock_store):
        mock_store.watch_add.return_value = ["forge.io"]
        runner.invoke(app, ["watch", "add", "forge.io"])
        mock_store.watch_add.assert_called_once_with(["forge.io"])

    def test_partial_add_shows_both_messages(self, mock_store):
        mock_store.watch_add.return_value = ["pixel.dev"]  # forge.io already watched
        result = runner.invoke(app, ["watch", "add", "forge.io", "pixel.dev"])
        assert result.exit_code == 0
        assert "pixel.dev"       in result.output
        assert "Already watching" in result.output


# ------------------------------------------------------------------ #
# watch remove                                                        #
# ------------------------------------------------------------------ #

class TestWatchRemoveCommand:
    def test_remove_existing(self, mock_store):
        mock_store.watch_remove.return_value = ["forge.io"]
        result = runner.invoke(app, ["watch", "remove", "forge.io"])
        assert result.exit_code == 0
        assert "forge.io" in result.output

    def test_remove_not_found(self, mock_store):
        mock_store.watch_remove.return_value = []
        result = runner.invoke(app, ["watch", "remove", "forge.io"])
        assert result.exit_code == 0
        assert "Not in watchlist" in result.output

    def test_remove_multiple(self, mock_store):
        mock_store.watch_remove.return_value = ["forge.io", "pixel.dev"]
        result = runner.invoke(app, ["watch", "remove", "forge.io", "pixel.dev"])
        assert result.exit_code == 0
        assert "forge.io"  in result.output
        assert "pixel.dev" in result.output

    def test_calls_store_watch_remove(self, mock_store):
        mock_store.watch_remove.return_value = ["forge.io"]
        runner.invoke(app, ["watch", "remove", "forge.io"])
        mock_store.watch_remove.assert_called_once_with(["forge.io"])


# ------------------------------------------------------------------ #
# watch list                                                          #
# ------------------------------------------------------------------ #

class TestWatchListCommand:
    def test_empty_watchlist(self, mock_store):
        mock_store.watch_list.return_value = []
        result = runner.invoke(app, ["watch", "list"])
        assert result.exit_code == 0
        assert "empty" in result.output.lower()

    def test_shows_fqdn(self, mock_store):
        mock_store.watch_list.return_value = [{
            "fqdn":     "forge.io",
            "added_at": "2026-04-15T00:00:00+00:00",
            "domain":   None,
        }]
        result = runner.invoke(app, ["watch", "list"])
        assert result.exit_code == 0
        assert "forge.io" in result.output

    def test_shows_dashes_when_domain_not_in_db(self, mock_store):
        mock_store.watch_list.return_value = [{
            "fqdn":     "forge.io",
            "added_at": "2026-04-15T00:00:00+00:00",
            "domain":   None,
        }]
        result = runner.invoke(app, ["watch", "list"])
        assert result.exit_code == 0
        assert "—" in result.output

    def test_shows_score_when_domain_in_db(self, mock_store):
        domain = Domain(
            fqdn      = "forge.io",
            name      = "forge",
            tld       = "io",
            source    = "dropcatch",
            nlp_score = 0.85,
        )
        mock_store.watch_list.return_value = [{
            "fqdn":     "forge.io",
            "added_at": "2026-04-15T00:00:00+00:00",
            "domain":   domain,
        }]
        result = runner.invoke(app, ["watch", "list"])
        assert result.exit_code == 0
        assert "0.85" in result.output

    def test_shows_count(self, mock_store):
        mock_store.watch_list.return_value = [
            {"fqdn": "forge.io",  "added_at": "2026-04-15T00:00:00+00:00", "domain": None},
            {"fqdn": "pixel.dev", "added_at": "2026-04-15T00:00:00+00:00", "domain": None},
        ]
        result = runner.invoke(app, ["watch", "list"])
        assert result.exit_code == 0
        assert "2" in result.output

    def test_calls_store_watch_list(self, mock_store):
        mock_store.watch_list.return_value = []
        runner.invoke(app, ["watch", "list"])
        mock_store.watch_list.assert_called_once()


# ------------------------------------------------------------------ #
# watch clear                                                         #
# ------------------------------------------------------------------ #

class TestWatchClearCommand:
    def test_clear_with_yes_flag(self, mock_store):
        mock_store.watch_clear.return_value = 3
        result = runner.invoke(app, ["watch", "clear", "--yes"])
        assert result.exit_code == 0
        assert "3" in result.output

    def test_clear_prompts_without_yes(self, mock_store):
        mock_store.watch_clear.return_value = 0
        result = runner.invoke(app, ["watch", "clear"], input="y\n")
        assert result.exit_code == 0

    def test_clear_aborts_on_no(self, mock_store):
        result = runner.invoke(app, ["watch", "clear"], input="n\n")
        assert result.exit_code != 0
        mock_store.watch_clear.assert_not_called()

    def test_calls_store_watch_clear(self, mock_store):
        mock_store.watch_clear.return_value = 0
        runner.invoke(app, ["watch", "clear", "--yes"])
        mock_store.watch_clear.assert_called_once()

    def test_shows_count_cleared(self, mock_store):
        mock_store.watch_clear.return_value = 5
        result = runner.invoke(app, ["watch", "clear", "--yes"])
        assert result.exit_code == 0
        assert "5" in result.output