"""Unit tests for `ddig export` CLI command."""
from __future__ import annotations

import csv
import json
import pytest
from pathlib import Path
from typer.testing import CliRunner
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from ddig.__main__ import app
from ddig.models.domain import Domain

runner = CliRunner()


def _make_domain(**kwargs) -> Domain:
    defaults: dict = dict(
        fqdn      = "forge.io",
        name      = "forge",
        tld       = "io",
        source    = "dropcatch",
        nlp_score = 0.85,
        backlinks = 1234,
        rank      = 5000,
        drop_date = datetime(2026, 4, 20, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return Domain(**defaults)


@pytest.fixture
def mock_store():
    with patch("ddig.__main__.DomainStore") as MockStore:
        store = MagicMock()
        MockStore.return_value = store
        yield store


# ------------------------------------------------------------------ #
# stdout output                                                       #
# ------------------------------------------------------------------ #

class TestExportStdout:
    def test_csv_to_stdout(self, mock_store):
        mock_store.search.return_value = [_make_domain()]
        result = runner.invoke(app, ["export", "--format", "csv"])
        assert result.exit_code == 0
        assert "forge.io" in result.output

    def test_json_to_stdout(self, mock_store):
        mock_store.search.return_value = [_make_domain()]
        result = runner.invoke(app, ["export", "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output.strip())
        assert any(d["fqdn"] == "forge.io" for d in data)

    def test_no_results_exits_cleanly(self, mock_store):
        mock_store.search.return_value = []
        result = runner.invoke(app, ["export"])
        assert result.exit_code == 0
        assert "No results" in result.output

    def test_unknown_format_exits_nonzero(self, mock_store):
        mock_store.search.return_value = [_make_domain()]
        result = runner.invoke(app, ["export", "--format", "xml"])
        assert result.exit_code != 0


# ------------------------------------------------------------------ #
# file output                                                         #
# ------------------------------------------------------------------ #

class TestExportFile:
    def test_csv_written_to_file(self, mock_store, tmp_path):
        mock_store.search.return_value = [_make_domain()]
        out = tmp_path / "results.csv"
        result = runner.invoke(app, ["export", "--format", "csv", str(out)])
        assert result.exit_code == 0
        assert out.exists()
        rows = list(csv.DictReader(out.read_text().splitlines()))
        assert rows[0]["fqdn"] == "forge.io"

    def test_json_written_to_file(self, mock_store, tmp_path):
        mock_store.search.return_value = [_make_domain()]
        out = tmp_path / "results.json"
        result = runner.invoke(app, ["export", "--format", "json", str(out)])
        assert result.exit_code == 0
        assert out.exists()
        data = json.loads(out.read_text())
        assert data[0]["fqdn"] == "forge.io"

    def test_success_message_shown_for_file(self, mock_store, tmp_path):
        mock_store.search.return_value = [_make_domain()]
        out = tmp_path / "results.csv"
        result = runner.invoke(app, ["export", "--format", "csv", str(out)])
        assert result.exit_code == 0
        assert "results.csv" in result.output

    def test_csv_has_correct_headers(self, mock_store, tmp_path):
        mock_store.search.return_value = [_make_domain()]
        out = tmp_path / "results.csv"
        runner.invoke(app, ["export", "--format", "csv", str(out)])
        reader = csv.DictReader(out.read_text().splitlines())
        assert set(reader.fieldnames or []) >= {
            "fqdn", "name", "tld", "nlp_score", "composite_score",
            "backlinks", "rank", "drop_date", "source",
        }


# ------------------------------------------------------------------ #
# CSV field values                                                    #
# ------------------------------------------------------------------ #

class TestExportFieldValues:
    def test_drop_date_serialised(self, mock_store, tmp_path):
        mock_store.search.return_value = [
            _make_domain(drop_date=datetime(2026, 4, 20, tzinfo=timezone.utc))
        ]
        out = tmp_path / "results.csv"
        runner.invoke(app, ["export", "--format", "csv", str(out)])
        rows = list(csv.DictReader(out.read_text().splitlines()))
        assert "2026-04-20" in rows[0]["drop_date"]

    def test_null_drop_date_is_empty_string(self, mock_store, tmp_path):
        mock_store.search.return_value = [_make_domain(drop_date=None)]
        out = tmp_path / "results.csv"
        runner.invoke(app, ["export", "--format", "csv", str(out)])
        rows = list(csv.DictReader(out.read_text().splitlines()))
        assert rows[0]["drop_date"] == ""

    def test_tags_pipe_separated(self, mock_store, tmp_path):
        d = _make_domain()
        d.tags = ["short", "real_word"]
        mock_store.search.return_value = [d]
        out = tmp_path / "results.csv"
        runner.invoke(app, ["export", "--format", "csv", str(out)])
        rows = list(csv.DictReader(out.read_text().splitlines()))
        assert rows[0]["tags"] == "short|real_word"

    def test_multiple_rows(self, mock_store, tmp_path):
        mock_store.search.return_value = [
            _make_domain(fqdn="forge.io",  name="forge"),
            _make_domain(fqdn="pixel.dev", name="pixel", tld="dev"),
            _make_domain(fqdn="atlas.app", name="atlas", tld="app"),
        ]
        out = tmp_path / "results.csv"
        runner.invoke(app, ["export", "--format", "csv", str(out)])
        rows = list(csv.DictReader(out.read_text().splitlines()))
        assert len(rows) == 3
        fqdns = {r["fqdn"] for r in rows}
        assert fqdns == {"forge.io", "pixel.dev", "atlas.app"}


# ------------------------------------------------------------------ #
# filters passed to store.search                                      #
# ------------------------------------------------------------------ #

class TestExportFilters:
    def test_tld_passed_to_search(self, mock_store):
        mock_store.search.return_value = []
        runner.invoke(app, ["export", "--tld", "com"])
        call_kwargs = mock_store.search.call_args[1]
        assert call_kwargs["tld"] == "com"

    def test_min_score_passed_to_search(self, mock_store):
        mock_store.search.return_value = []
        runner.invoke(app, ["export", "--min-score", "0.7"])
        call_kwargs = mock_store.search.call_args[1]
        assert call_kwargs["min_score"] == pytest.approx(0.7)

    def test_within_passed_to_search(self, mock_store):
        mock_store.search.return_value = []
        runner.invoke(app, ["export", "--within", "7"])
        call_kwargs = mock_store.search.call_args[1]
        assert call_kwargs["within_days"] == 7

    def test_limit_passed_to_search(self, mock_store):
        mock_store.search.return_value = []
        runner.invoke(app, ["export", "--limit", "500"])
        call_kwargs = mock_store.search.call_args[1]
        assert call_kwargs["limit"] == 500

    def test_no_hyphens_passed_to_search(self, mock_store):
        mock_store.search.return_value = []
        runner.invoke(app, ["export", "--no-hyphens"])
        call_kwargs = mock_store.search.call_args[1]
        assert call_kwargs["no_hyphens"] is True

    def test_sort_passed_to_search(self, mock_store):
        mock_store.search.return_value = []
        runner.invoke(app, ["export", "--sort", "backlinks"])
        call_kwargs = mock_store.search.call_args[1]
        assert call_kwargs["sort"] == "backlinks"