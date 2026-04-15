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
import math
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


# ---------------------------------------------------------------------------
# English letter bigram frequency table
# Frequencies derived from large English text corpora, normalised to 0–1.
# Common pairs (th, he, in) → high scores; rare pairs (xk, zb) → low scores.
# ---------------------------------------------------------------------------

_BIGRAM_SCORES: dict[str, float] = {
    "th": 1.00, "he": 0.97, "in": 0.95, "er": 0.93, "an": 0.91,
    "re": 0.90, "on": 0.89, "en": 0.88, "at": 0.87, "es": 0.86,
    "ed": 0.85, "or": 0.84, "ti": 0.83, "hi": 0.82, "st": 0.81,
    "ar": 0.80, "nd": 0.79, "to": 0.78, "nt": 0.77, "is": 0.76,
    "it": 0.76, "ng": 0.75, "ou": 0.74, "al": 0.73, "se": 0.72,
    "le": 0.71, "co": 0.70, "de": 0.69, "li": 0.68, "ne": 0.67,
    "io": 0.67, "ve": 0.66, "ra": 0.65, "ro": 0.64, "ri": 0.63,
    "ic": 0.62, "me": 0.61, "te": 0.60, "la": 0.59, "lo": 0.58,
    "ma": 0.57, "si": 0.56, "no": 0.56, "un": 0.55, "ca": 0.54,
    "pe": 0.53, "pr": 0.52, "tr": 0.51, "pl": 0.50, "cl": 0.49,
    "fl": 0.48, "bl": 0.47, "cr": 0.46, "gr": 0.45, "fr": 0.44,
    "dr": 0.43, "br": 0.42, "sp": 0.41, "sl": 0.40, "sc": 0.39,
    "sk": 0.38, "sm": 0.37, "sn": 0.36, "sw": 0.35, "gl": 0.34,
    "ex": 0.33, "ly": 0.32, "ry": 0.31, "ty": 0.30, "ky": 0.29,
    "ny": 0.28, "my": 0.27, "fy": 0.26, "py": 0.25, "gy": 0.24,
    "ul": 0.32, "ur": 0.33, "us": 0.31, "um": 0.30, "ix": 0.20,
    "ox": 0.19, "ax": 0.18, "ux": 0.22, "ex": 0.33, "xi": 0.12,
    "xu": 0.10, "xo": 0.10, "xa": 0.10, "xk": 0.03, "xz": 0.02,
    "zb": 0.02, "zg": 0.02, "zx": 0.02, "zq": 0.01, "qx": 0.01,
    "qz": 0.01, "kz": 0.02, "vx": 0.02, "wx": 0.02, "wz": 0.02,
}

_VOWELS = frozenset("aeiou")


def _bigram_score(name: str) -> float:
    """
    Score a name by averaging its letter bigram frequencies.
    Single-character names return 1.0 (can't penalise).
    """
    if len(name) < 2:
        return 1.0
    bigrams = [name[i : i + 2] for i in range(len(name) - 1)]
    scores  = [_BIGRAM_SCORES.get(bg, 0.15) for bg in bigrams]
    return sum(scores) / len(scores)


@lru_cache(maxsize=32_768)
def _score_pronounceability(name: str) -> float:
    """
    Pronounceability score 0–1 combining:
      - 70% bigram frequency model
      - 30% vowel ratio heuristic (sweet spot ~40% vowels)
    """
    if not name:
        return 0.0

    # Bigram component
    bigram = _bigram_score(name)

    # Vowel ratio component
    vowel_count = sum(1 for c in name if c in _VOWELS)
    vowel_ratio = vowel_count / len(name)
    vowel       = max(0.0, min(1.0, 1.0 - abs(vowel_ratio - 0.40) * 2))

    return round(bigram * 0.70 + vowel * 0.30, 4)


@lru_cache(maxsize=32_768)
def _score_length(name: str) -> float:
    """
    Score based on domain name length.
    Sweet spot is 3–6 characters.
    """
    n = len(name)
    if n <= 3:  return 1.0
    if n == 4:  return 1.0
    if n == 5:  return 0.9
    if n == 6:  return 0.8
    if n == 7:  return 0.7
    if n == 8:  return 0.6
    if n == 9:  return 0.5
    if n == 10: return 0.4
    if n <= 12: return 0.3
    if n <= 15: return 0.2
    return 0.1


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

# Composite score weights
COMPOSITE_WEIGHTS = {
    "nlp_score":  0.50,
    "backlinks":  0.30,
    "rank":       0.20,
}

# Normalisation ceilings
_BACKLINK_CEIL = 1_000_000   # log10 ceiling for backlinks
_RANK_CEIL     = 1_000_000   # log10 ceiling for rank


def _normalise_backlinks(backlinks: int | None) -> float:
    """Log-normalise backlinks to 0–1. Missing → 0."""
    if backlinks is None or backlinks <= 0:
        return 0.0
    return min(math.log10(backlinks + 1) / math.log10(_BACKLINK_CEIL), 1.0)


def _normalise_rank(rank: int | None) -> float:
    """
    Inverse log-normalise Majestic rank to 0–1.
    Rank 1 → 1.0, rank 1_000_000 → 0.0, missing → 0.0.
    Lower rank number = more linked = higher score.
    """
    if rank is None or rank <= 0:
        return 0.0
    return max(1.0 - math.log10(rank) / math.log10(_RANK_CEIL), 0.0)


def compute_composite(
    nlp_score: float | None,
    backlinks: int   | None,
    rank:      int   | None,
) -> float:
    """Compute composite score from NLP score, backlinks, and rank."""
    nlp  = nlp_score if nlp_score is not None else 0.0
    bl   = _normalise_backlinks(backlinks)
    rnk  = _normalise_rank(rank)

    return round(
        nlp  * COMPOSITE_WEIGHTS["nlp_score"]
      + bl   * COMPOSITE_WEIGHTS["backlinks"]
      + rnk  * COMPOSITE_WEIGHTS["rank"],
        4,
    )


class DomainScorer:
    """
    Scores domain names for quality using NLP heuristics.

    Usage::

        scorer = DomainScorer(language="en")
        scored_domains = scorer.score_many(domains)
    """

    def __init__(self, language: str = "en") -> None:
        self.language = language

    def score(self, domain: Domain) -> Domain:
        """Score a single domain in-place and return it."""
        name = domain.name.lower()

        is_real, freq_score  = _score_real_word(name, self.language)
        length_score         = _score_length(name)
        pronounce_score      = _score_pronounceability(name)
        no_hyphen_score      = 0.0 if domain.has_hyphen  else 1.0
        no_numbers_score     = 0.0 if domain.has_numbers else 1.0
        is_pronounceable     = bool(pronounce_score >= 0.5)

        final = (
              is_real          * WEIGHTS["real_word"]
            + freq_score       * WEIGHTS["word_frequency"]
            + length_score     * WEIGHTS["length"]
            + pronounce_score  * WEIGHTS["pronounceable"]
            + no_hyphen_score  * WEIGHTS["no_hyphen"]
            + no_numbers_score * WEIGHTS["no_numbers"]
        )

        domain.nlp_score        = round(final, 4)
        domain.is_real_word     = is_real
        domain.word_frequency   = round(freq_score, 6)
        domain.is_pronounceable = is_pronounceable
        domain.composite_score  = compute_composite(
            domain.nlp_score,
            domain.backlinks,
            domain.rank,
        )

        domain.tags = self._build_tags(
            domain,
            is_real_word     = is_real,
            is_pronounceable = is_pronounceable,
        )

        return domain

    def score_many(self, domains: list["Domain"]) -> list["Domain"]:
        """Score a list of domains, sorted by score descending."""
        for d in domains:
            self.score(d)
        return sorted(domains, key=lambda d: d.nlp_score or 0.0, reverse=True)

    def _build_tags(self, domain: "Domain", is_real_word: bool, is_pronounceable: bool) -> list[str]:
        """Build a deduplicated tag list."""
        tags: set[str] = set(domain.tags)

        if is_real_word:
            tags.add("english-word")
        if is_pronounceable:
            tags.add("pronounceable")
        if not domain.has_hyphen:
            tags.add("no-hyphen")
        if not domain.has_numbers:
            tags.add("no-numbers")
        if domain.length <= 4:
            tags.add("ultra-short")
        elif domain.length <= 6:
            tags.add("short")

        return sorted(tags)