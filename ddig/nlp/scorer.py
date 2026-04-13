"""
NLP-based domain name quality scorer.

Scoring weights (English, v1):
    - Real English word         30%
    - Word frequency rank       20%
    - Length (shorter = better) 15%
    - Pronounceability          15%
    - No hyphens                10%
    - No numbers                10%
"""
from __future__ import annotations

import logging
import time
from functools import lru_cache
from multiprocessing import Pool, cpu_count
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models.domain import Domain

log = logging.getLogger(__name__)

_wordfreq  = None
_nltk_words = None


def _get_wordfreq():
    global _wordfreq
    if _wordfreq is None:
        import wordfreq as wf
        _wordfreq = wf
    return _wordfreq


def _get_nltk_words() -> set[str]:
    global _nltk_words
    if _nltk_words is None:
        try:
            import nltk
            try:
                from nltk.corpus import words as nltk_word_corpus
                _nltk_words = set(w.lower() for w in nltk_word_corpus.words())
            except LookupError:
                log.info("Downloading NLTK 'words' corpus…")
                nltk.download("words", quiet=True)
                from nltk.corpus import words as nltk_word_corpus
                _nltk_words = set(w.lower() for w in nltk_word_corpus.words())
        except Exception as exc:
            log.warning("NLTK words corpus unavailable: %s", exc)
            _nltk_words = set()
    return _nltk_words


# ---------------------------------------------------------------------------
# Individual scoring components
# ---------------------------------------------------------------------------

@lru_cache(maxsize=32_768)
def _score_real_word(name: str, language: str = "en") -> tuple[bool, float]:
    """Returns (is_real_word, frequency_score 0–1)."""
    import math
    wf   = _get_wordfreq()
    freq = wf.word_frequency(name, language)

    if freq > 0:
        score = max(0.0, min(1.0, (math.log10(freq) + 7) / 4))
        return True, score

    is_word = name in _get_nltk_words()
    return is_word, 0.1 if is_word else 0.0


@lru_cache(maxsize=32_768)
def _score_pronounceability(name: str) -> float:
    """Heuristic pronounceability score 0–1."""
    if not name:
        return 0.0

    vowels      = set("aeiou")
    vowel_count = sum(1 for c in name if c in vowels)
    vowel_ratio = vowel_count / len(name)

    max_consonant_run = 0
    current_run = 0
    for c in name:
        if c.isalpha() and c not in vowels:
            current_run += 1
            max_consonant_run = max(max_consonant_run, current_run)
        else:
            current_run = 0

    ratio_score = 1.0 - abs(vowel_ratio - 0.40) * 2
    ratio_score = max(0.0, min(1.0, ratio_score))

    consonant_penalty = max(0.0, 1.0 - (max_consonant_run - 2) * 0.25)

    return (ratio_score + consonant_penalty) / 2


def _score_length(name: str) -> float:
    """Short domains score higher. Sweet spot 4–8 chars."""
    n = len(name)
    if n <= 3:
        return 0.6   # too short, possibly already taken or meaningless
    if n <= 6:
        return 1.0
    if n <= 9:
        return 0.8
    if n <= 12:
        return 0.5
    return max(0.0, 0.5 - (n - 12) * 0.05)


# ---------------------------------------------------------------------------
# Main scorer class
# ---------------------------------------------------------------------------

WEIGHTS = {
    "real_word":       0.30,
    "word_frequency":  0.20,
    "length":          0.15,
    "pronounceable":   0.15,
    "no_hyphen":       0.10,
    "no_numbers":      0.10,
}


class DomainScorer:
    """
    Scores domain names for quality using NLP heuristics.

    Usage::

        scorer = DomainScorer(language="en")
        scored_domains = scorer.score_many(domains)
    """

    def __init__(self, language: str = "en") -> None:
        self.language = language

    def score(self, domain: "Domain") -> "Domain":
        """Score a single domain in-place and return it."""
        name = domain.name.lower()

        # Component scores
        is_real, freq_score = _score_real_word(name, self.language)
        length_score        = _score_length(name)
        pronounce_score     = _score_pronounceability(name)
        no_hyphen_score     = 0.0 if domain.has_hyphen else 1.0
        no_numbers_score    = 0.0 if domain.has_numbers else 1.0

        # Weighted sum
        final = (
            is_real      * WEIGHTS["real_word"]
            + freq_score * WEIGHTS["word_frequency"]
            + length_score       * WEIGHTS["length"]
            + pronounce_score    * WEIGHTS["pronounceable"]
            + no_hyphen_score    * WEIGHTS["no_hyphen"]
            + no_numbers_score   * WEIGHTS["no_numbers"]
        )

        domain.nlp_score       = round(final, 4)
        domain.is_real_word    = is_real
        domain.word_frequency  = round(freq_score, 6)
        domain.is_pronounceable = pronounce_score >= 0.5

        # Tags
        if is_real:
            domain.tags.append("real-word")
        if not domain.has_hyphen:
            domain.tags.append("no-hyphen")
        if not domain.has_numbers:
            domain.tags.append("no-numbers")
        if len(name) <= 6:
            domain.tags.append("short")

        return domain

    def score_many(self, domains: list["Domain"]) -> list["Domain"]:
        """Score a list of domains, sorted by score descending."""
        for d in domains:
            self.score(d)
        return sorted(domains, key=lambda d: d.nlp_score or 0.0, reverse=True)