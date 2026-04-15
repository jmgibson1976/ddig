"""Unit tests for `ddig score` CLI command."""
from __future__ import annotations

import pytest
from typer.testing import CliRunner
from unittest.mock import patch, MagicMock
from dataclasses import replace

from ddig.__main__ import app
from ddig.models.domain import Domain

runner = CliRunner()


def _domain(**kwargs) -> Domain:
    base = Domain(
        fqdn   = "forge.io",
        name   = "forge",
        tld    = "io",
        source = "dropcatch",
    )
    return replace(base, **kwargs)


@pytest.fixture
def mock_store():
    with patch("ddig.__main__.DomainStore") as MockStore:
        store = MagicMock()
        MockStore.return_value = store
        yield store


@pytest.fixture
def mock_scorer():
    with patch("ddig.__main__.DomainScorer") as MockScorer:
        scorer = MagicMock()
        MockScorer.return_value = scorer
        yield scorer


# ------------------------------------------------------------------ #
# Empty DB                                                            #
# ------------------------------------------------------------------ #

class TestScoreEmptyDb:
    def test_all_scored_message_when_nothing_to_score(self, mock_store, mock_scorer):
        mock_store.search.return_value = [
            _domain(nlp_score=0.85),
            _domain(fqdn="pixel.dev", name="pixel", tld="dev", nlp_score=0.75),
        ]
        result = runner.invoke(app, ["score"])
        assert result.exit_code == 0
        assert "already scored" in result.output.lower()

    def test_scorer_not_called_when_nothing_to_score(self, mock_store, mock_scorer):
        mock_store.search.return_value = [_domain(nlp_score=0.85)]
        runner.invoke(app, ["score"])
        mock_scorer.score_many.assert_not_called()

    def test_upsert_not_called_when_nothing_to_score(self, mock_store, mock_scorer):
        mock_store.search.return_value = [_domain(nlp_score=0.85)]
        runner.invoke(app, ["score"])
        mock_store.upsert_many.assert_not_called()

    def test_exit_code_zero_on_empty_db(self, mock_store, mock_scorer):
        mock_store.search.return_value = []
        result = runner.invoke(app, ["score"])
        assert result.exit_code == 0
        assert "already scored" in result.output.lower()


# ------------------------------------------------------------------ #
# Scoring behaviour                                                   #
# ------------------------------------------------------------------ #

class TestScoreBehaviour:
    def test_scores_unscored_domains(self, mock_store, mock_scorer):
        unscored = [_domain()]
        scored   = [_domain(nlp_score=0.85)]
        mock_store.search.return_value = unscored
        mock_scorer.score_many.return_value = scored
        result = runner.invoke(app, ["score"])
        assert result.exit_code == 0
        mock_scorer.score_many.assert_called_once_with(unscored)

    def test_upserts_scored_domains(self, mock_store, mock_scorer):
        unscored = [_domain()]
        scored   = [_domain(nlp_score=0.85)]
        mock_store.search.return_value = unscored
        mock_scorer.score_many.return_value = scored
        runner.invoke(app, ["score"])
        mock_store.upsert_many.assert_called_once_with(scored)

    def test_only_unscored_domains_passed_to_scorer(self, mock_store, mock_scorer):
        domains = [
            _domain(fqdn="forge.io",  name="forge",               nlp_score=0.85),
            _domain(fqdn="pixel.dev", name="pixel", tld="dev"),
            _domain(fqdn="atlas.app", name="atlas", tld="app"),
        ]
        mock_store.search.return_value = domains
        mock_scorer.score_many.return_value = [
            _domain(fqdn="pixel.dev", name="pixel", tld="dev", nlp_score=0.75),
            _domain(fqdn="atlas.app", name="atlas", tld="app", nlp_score=0.80),
        ]
        runner.invoke(app, ["score"])
        passed = mock_scorer.score_many.call_args[0][0]
        assert len(passed) == 2
        fqdns = {d.fqdn for d in passed}
        assert fqdns == {"pixel.dev", "atlas.app"}

    def test_shows_total_count_in_output(self, mock_store, mock_scorer):
        unscored = [
            _domain(fqdn="forge.io",  name="forge"),
            _domain(fqdn="pixel.dev", name="pixel", tld="dev"),
        ]
        mock_store.search.return_value = unscored
        mock_scorer.score_many.return_value = [
            _domain(fqdn="forge.io",  name="forge",              nlp_score=0.85),
            _domain(fqdn="pixel.dev", name="pixel", tld="dev",   nlp_score=0.75),
        ]
        result = runner.invoke(app, ["score"])
        assert result.exit_code == 0
        assert "2" in result.output

    def test_calls_store_search_first(self, mock_store, mock_scorer):
        mock_store.search.return_value = []
        runner.invoke(app, ["score"])
        mock_store.search.assert_called_once()

    def test_exit_code_zero_on_success(self, mock_store, mock_scorer):
        unscored = [_domain()]
        mock_store.search.return_value = unscored
        mock_scorer.score_many.return_value = [_domain(nlp_score=0.85)]
        result = runner.invoke(app, ["score"])
        assert result.exit_code == 0


# ------------------------------------------------------------------ #
# Batching                                                            #
# ------------------------------------------------------------------ #

class TestScoreBatching:
    def test_large_set_batched_correctly(self, mock_store, mock_scorer):
        unscored = [
            _domain(fqdn=f"domain{i}.com", name=f"domain{i}", tld="com")
            for i in range(25)
        ]
        mock_store.search.return_value = unscored
        mock_scorer.score_many.side_effect = lambda batch: [
            replace(d, nlp_score=0.5) for d in batch
        ]
        result = runner.invoke(app, ["score", "--batch-size", "10"])
        assert result.exit_code == 0
        assert mock_scorer.score_many.call_count == 3

    def test_batch_size_option_accepted(self, mock_store, mock_scorer):
        mock_store.search.return_value = []
        result = runner.invoke(app, ["score", "--batch-size", "500"])
        assert result.exit_code == 0


# ------------------------------------------------------------------ #
# Options                                                             #
# ------------------------------------------------------------------ #

class TestScoreOptions:
    def test_language_option_passed_to_scorer(self, mock_store):
        with patch("ddig.__main__.DomainScorer") as MockScorer:
            scorer = MagicMock()
            MockScorer.return_value = scorer
            mock_store.search.return_value = []
            runner.invoke(app, ["score", "--language", "en"])
            MockScorer.assert_called_once_with(language="en")

    def test_db_option_passed_to_store(self, tmp_path):
        with patch("ddig.__main__.DomainStore") as MockStore:
            store = MagicMock()
            store.search.return_value = []
            MockStore.return_value = store
            runner.invoke(app, ["score", "--db", str(tmp_path / "test.db")])
            MockStore.assert_called_once_with(db_path=tmp_path / "test.db")

    def test_verbose_flag_accepted(self, mock_store, mock_scorer):
        mock_store.search.return_value = []
        result = runner.invoke(app, ["score", "--verbose"])
        assert result.exit_code == 0