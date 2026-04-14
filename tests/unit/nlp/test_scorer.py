"""Unit tests for the DomainScorer."""
from __future__ import annotations

import pytest

from ddig.models.domain import Domain
from ddig.nlp.scorer import (
    DomainScorer,
    _normalise_backlinks,
    _normalise_rank,
    _score_length,
    _score_pronounceability,
    _score_real_word,
    compute_composite,
)

class TestScoreLength:
    def test_3_char_scores_1(self):
        assert _score_length("bit") == 1.0

    def test_2_char_scores_1(self):
        assert _score_length("io") == 1.0

    def test_1_char_scores_1(self):
        assert _score_length("x") == 1.0

    def test_4_char_scores_1(self):
        assert _score_length("flux") == 1.0

    def test_5_char_scores_09(self):
        assert _score_length("forge") == 0.9

    def test_6_char_scores_08(self):
        assert _score_length("github") == 0.8

    def test_long_name_scores_low(self):
        assert _score_length("averylongdomainname") == 0.1

    def test_scores_decrease_with_length(self):
        scores = [_score_length("x" * n) for n in range(1, 16)]
        assert scores == sorted(scores, reverse=True)


class TestBuildTags:
    def _make_domain(self, name: str, tags: list[str] | None = None) -> Domain:
        return Domain(name=name, tld="com", fqdn=f"{name}.com", tags=tags or [])

    def test_no_duplicate_tags_on_rescore(self):
        scorer = DomainScorer()
        domain = self._make_domain("apple", tags=["no-hyphen", "no-numbers"])
        tags   = scorer._build_tags(domain, is_real_word=True, is_pronounceable=True)
        assert len(tags) == len(set(tags))

    def test_existing_tags_preserved(self):
        scorer = DomainScorer()
        domain = self._make_domain("apple", tags=["no-hyphen"])
        tags   = scorer._build_tags(domain, is_real_word=True, is_pronounceable=False)
        assert "no-hyphen" in tags

    def test_english_word_tag_added(self):
        scorer = DomainScorer()
        domain = self._make_domain("apple")
        tags   = scorer._build_tags(domain, is_real_word=True, is_pronounceable=False)
        assert "english-word" in tags

    def test_ultra_short_tag_for_4_chars(self):
        scorer = DomainScorer()
        domain = self._make_domain("flux")
        tags   = scorer._build_tags(domain, is_real_word=False, is_pronounceable=True)
        assert "ultra-short" in tags

    def test_short_tag_for_5_6_chars(self):
        scorer = DomainScorer()
        for name in ("forge", "github"):
            domain = self._make_domain(name)
            tags   = scorer._build_tags(domain, is_real_word=False, is_pronounceable=True)
            assert "short" in tags

    def test_no_short_tag_for_long_name(self):
        scorer = DomainScorer()
        domain = self._make_domain("averylongname")
        tags   = scorer._build_tags(domain, is_real_word=False, is_pronounceable=False)
        assert "short"       not in tags
        assert "ultra-short" not in tags

    def test_tags_are_sorted(self):
        scorer = DomainScorer()
        domain = self._make_domain("apple")
        tags   = scorer._build_tags(domain, is_real_word=True, is_pronounceable=True)
        assert tags == sorted(tags)

    def test_rescore_does_not_grow_tags(self):
        """Scoring twice should not add duplicate tags."""
        scorer = DomainScorer()
        domain = self._make_domain("apple")
        first  = scorer._build_tags(domain, is_real_word=True, is_pronounceable=True)
        domain.tags = first
        second = scorer._build_tags(domain, is_real_word=True, is_pronounceable=True)
        assert first == second


class TestNormaliseBacklinks:
    def test_none_returns_0(self):
        assert _normalise_backlinks(None) == 0.0

    def test_zero_returns_0(self):
        assert _normalise_backlinks(0) == 0.0

    def test_1_million_returns_1(self):
        assert _normalise_backlinks(1_000_000) == pytest.approx(1.0, abs=0.01)

    def test_increases_with_backlinks(self):
        assert _normalise_backlinks(10_000) > _normalise_backlinks(1_000)

    def test_capped_at_1(self):
        assert _normalise_backlinks(999_999_999) == 1.0


class TestNormaliseRank:
    def test_none_returns_0(self):
        assert _normalise_rank(None) == 0.0

    def test_zero_returns_0(self):
        assert _normalise_rank(0) == 0.0

    def test_rank_1_returns_1(self):
        assert _normalise_rank(1) == pytest.approx(1.0, abs=0.01)

    def test_rank_1_million_returns_0(self):
        assert _normalise_rank(1_000_000) == pytest.approx(0.0, abs=0.01)

    def test_lower_rank_scores_higher(self):
        assert _normalise_rank(100) > _normalise_rank(10_000)

    def test_never_negative(self):
        assert _normalise_rank(999_999_999) >= 0.0


class TestComputeComposite:
    def test_all_none_returns_0(self):
        assert compute_composite(None, None, None) == 0.0

    def test_nlp_only_capped_at_50_percent(self):
        result = compute_composite(1.0, None, None)
        assert result == pytest.approx(0.5, abs=0.01)

    def test_full_signals_near_1(self):
        result = compute_composite(1.0, 1_000_000, 1)
        assert result > 0.95

    def test_increases_with_backlinks(self):
        low  = compute_composite(0.8, 100,     None)
        high = compute_composite(0.8, 100_000, None)
        assert high > low

    def test_increases_with_better_rank(self):
        poor = compute_composite(0.8, None, 100_000)
        good = compute_composite(0.8, None, 10)
        assert good > poor

    def test_result_between_0_and_1(self):
        for nlp, bl, rank in [
            (0.5, 1000, 500),
            (0.9, None, None),
            (None, 50000, 75),
            (0.0, 0, 0),
        ]:
            result = compute_composite(nlp, bl, rank)
            assert 0.0 <= result <= 1.0

    def test_result_rounded_to_4dp(self):
        result = compute_composite(0.7531, 12345, 6789)
        assert result == round(result, 4)