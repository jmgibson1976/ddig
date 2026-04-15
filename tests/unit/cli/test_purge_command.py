"""Unit tests for `ddig purge` CLI command."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from ddig.__main__ import app

runner = CliRunner()


@pytest.fixture
def mock_store():
    with patch("ddig.__main__.DomainStore") as MockStore:
        store = MagicMock()
        MockStore.return_value = store
        yield store


class TestPurgeCommand:
    def test_dry_run_shows_count(self, tmp_path: Path) -> None:
        with patch("ddig.__main__.DomainStore") as MockStore:
            store = MagicMock()
            store.engine.connect.return_value.__enter__ = MagicMock(
                return_value=MagicMock(
                    execute=MagicMock(return_value=MagicMock(scalar=MagicMock(return_value=2)))
                )
            )
            store.engine.connect.return_value.__exit__ = MagicMock(return_value=False)
            MockStore.return_value = store
            result = runner.invoke(app, ["purge", "--db", str(tmp_path / "test.db"), "--dry-run"])
        assert result.exit_code == 0
        assert "dry-run" in result.output
        assert "2" in result.output

    def test_dry_run_does_not_call_purge(self, tmp_path: Path) -> None:
        with patch("ddig.__main__.DomainStore") as MockStore:
            store = MagicMock()
            store.engine.connect.return_value.__enter__ = MagicMock(
                return_value=MagicMock(
                    execute=MagicMock(return_value=MagicMock(scalar=MagicMock(return_value=0)))
                )
            )
            store.engine.connect.return_value.__exit__ = MagicMock(return_value=False)
            MockStore.return_value = store
            runner.invoke(app, ["purge", "--db", str(tmp_path / "test.db"), "--dry-run"])
            store.purge_no_drop_date.assert_not_called()

    def test_purge_calls_purge_no_drop_date(self, mock_store: MagicMock) -> None:
        mock_store.purge_no_drop_date.return_value = 5
        result = runner.invoke(app, ["purge"])
        assert result.exit_code == 0
        mock_store.purge_no_drop_date.assert_called_once()

    def test_purge_shows_count_in_output(self, mock_store: MagicMock) -> None:
        mock_store.purge_no_drop_date.return_value = 42
        result = runner.invoke(app, ["purge"])
        assert result.exit_code == 0
        assert "42" in result.output

    def test_purge_zero_shows_zero(self, mock_store: MagicMock) -> None:
        mock_store.purge_no_drop_date.return_value = 0
        result = runner.invoke(app, ["purge"])
        assert result.exit_code == 0
        assert "0" in result.output

    def test_db_option_passed_to_store(self, tmp_path: Path) -> None:
        with patch("ddig.__main__.DomainStore") as MockStore:
            store = MagicMock()
            store.purge_no_drop_date.return_value = 0
            MockStore.return_value = store
            runner.invoke(app, ["purge", "--db", str(tmp_path / "test.db")])
            MockStore.assert_called_once_with(db_path=tmp_path / "test.db")

    def test_verbose_flag_accepted(self, mock_store: MagicMock) -> None:
        mock_store.purge_no_drop_date.return_value = 0
        result = runner.invoke(app, ["purge", "--verbose"])
        assert result.exit_code == 0