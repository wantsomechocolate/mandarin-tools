"""
Computes a per-analysis text difficulty score from a user's familiarity
data - "how hard would this text actually be for me to read?" Resolved
fresh on every read from current KnownWord state (same reasoning as
familiarity/is_garbage/evidence_tier on WordResult - see their docstrings,
schemas.py) - never persisted, so a difficulty score reflects the user's
*current* vocabulary, not a snapshot from whenever the analysis was run.

v1 model: a token-weighted average of each counted word's "effective
weight" (how much of it the user can be assumed to get through), where a
word's weight is the greater of (a) its own familiarity and (b) - for
multi-character words - a discounted estimate from its component
characters' own familiarity. The character-decomposition piece is the
Mandarin-specific twist: an unknown compound word made of two characters
the user already knows (e.g. 希奇, unknown, built from 希 and 奇 - both
known via 希望/奇怪) is a smaller readability hit than a word built from
totally unfamiliar characters, even though both are equally "unknown" as
whole words.

Deliberately NOT included in v1 (see DIFFICULTY_SCORING.md at the repo
root for the full research writeup and why): corpus-frequency-based
severity weighting, and phonetic/semantic radical inference.

The FAMILIARITY_WEIGHTS/CHAR_DECOMPOSITION_DISCOUNT/DIFFICULTY_BANDS
constants below are placeholders seeded from general L2-reading research
(Hu & Nation 2000; Laufer & Ravenhorst-Kalovski 2010) that was done on
English, not Mandarin - they're deliberately easy to find and retune in
one place once real usage data (see DIFFICULTY_SCORING.md's deferred
calibration-feedback-loop item) says otherwise.
"""

import re
from typing import Literal

from app.modules.known_words.schemas import WordResult

# A word counts as "Chinese" for scoring purposes if it contains at least
# one CJK ideograph - the exact same range the results page's own
# Non-Chinese bucket already tests (containsChinese, analyze/[id]/
# +page.svelte: /[一-鿿]/), so a word excluded from scoring here is
# exactly the set a user can already see bucketed as "Non-Chinese" in the
# table. A lone English letter/word has no Mandarin familiarity to score
# in the first place, and left uncounted was actively distorting the score
# - see compute_difficulty's docstring.
_CJK_RE = re.compile(r"[一-鿿]")


def _contains_chinese(word: str) -> bool:
    return bool(_CJK_RE.search(word))


# AnalysisResult.source values that make up the "Main segmentation" bucket -
# the DAG's own disjoint best-guess walk, as opposed to the supplemental
# "extra_match"/"repeated_sequence" (and legacy "token"/"longest_match_only")
# passes layered on top of it. Canonical home for this constant - router.py
# imports it from here rather than defining its own copy, since both the
# reading-view spans endpoint and this module need exactly the same
# definition of "one pass over the actual text, with no double-counting."
MAIN_SEGMENTATION_SOURCES = {"dag", "overlay", "unknown", "trie"}

# Familiarity (1-5, see KnownWord.familiarity) -> a [0,1] "how much of this
# word can the reader be assumed to get through" weight. Unmarked/None is
# 0.0, handled separately below rather than living in this dict. Not
# linear: comprehension research treats recognition as closer to a
# threshold effect than a smooth ramp, so 5 sits close to "fully known"
# and 1-2 close to "not known," with 3 as the genuine gray zone.
FAMILIARITY_WEIGHTS: dict[int, float] = {
    1: 0.1,
    2: 0.3,
    3: 0.55,
    4: 0.8,
    5: 1.0,
}

# A word's own familiarity weight, if known well enough to count as
# "known" for the known_tokens/unknown_tokens split below.
KNOWN_WEIGHT_CUTOFF = 0.55

# How much credit recognizing a word's component characters is worth,
# relative to actually knowing the word itself - always a discount, never
# full credit, since a compositional guess is not the same as knowing what
# 希奇 means.
CHAR_DECOMPOSITION_DISCOUNT = 0.5

# Five ordered (cutoff, band) pairs, checked highest-first. Seeded from the
# two literature-backed anchors (98% "optimal", 95% "minimal" comprehension
# coverage - Laufer & Ravenhorst-Kalovski 2010) with a symmetric band added
# on each end so `manageable` sits as a true middle band rather than a
# catch-all top bucket. See this module's docstring for why none of these
# five cutoffs should be treated as precise yet.
DifficultyBand = Literal["very_easy", "easy", "manageable", "difficult", "very_difficult"]
DIFFICULTY_BANDS: list[tuple[float, DifficultyBand]] = [
    (0.99, "very_easy"),
    (0.98, "easy"),
    (0.95, "manageable"),
    (0.90, "difficult"),
    (0.0, "very_difficult"),
]


def _familiarity_weight(familiarity: int | None) -> float:
    if familiarity is None:
        return 0.0
    return FAMILIARITY_WEIGHTS.get(familiarity, 0.0)


def _char_decomposition_weight(word: str, known_words: dict[str, int]) -> float:
    """
    Estimates how much a multi-character word's own component characters'
    familiarity should count toward reading it, even though the word
    itself has no (or low) familiarity of its own. Only ever called for
    len(word) > 1 - a single character has no smaller unit to decompose
    into.

    known_char_count/total_char_count scales the credit down for a word
    where only some characters are recognized (1-of-3 known scores lower
    than 2-of-3, even at the same average weight among the known ones) -
    averaging only over recognized characters, rather than counting an
    unmarked character as a hard 0 in the average, so the "how well do I
    know the characters I DO recognize" signal isn't diluted by characters
    that simply have no data yet.
    """
    chars = list(word)
    char_weights = [_familiarity_weight(known_words.get(c)) for c in chars if c in known_words]
    if not char_weights:
        return 0.0

    known_fraction = len(char_weights) / len(chars)
    mean_known_weight = sum(char_weights) / len(char_weights)
    return CHAR_DECOMPOSITION_DISCOUNT * known_fraction * mean_known_weight


def effective_weight(word: str, familiarity: int | None, known_words: dict[str, int]) -> float:
    """
    A word's effective weight for scoring: the greater of its own direct
    familiarity and (for multi-character words only) the credit its
    component characters' own familiarity earns it. Never scores a word
    worse than its own direct familiarity - character decomposition can
    only ever help.
    """
    direct = _familiarity_weight(familiarity)
    if len(word) <= 1:
        return direct
    return max(direct, _char_decomposition_weight(word, known_words))


def _band_for(score: float) -> DifficultyBand:
    for cutoff, band in DIFFICULTY_BANDS:
        if score >= cutoff:
            return band
    return "very_difficult"  # unreachable - DIFFICULTY_BANDS' last cutoff is 0.0


class DifficultyBreakdown:
    """
    Plain result container for compute_difficulty - router.py converts
    this 1:1 into the schemas.DifficultyBreakdown response model. Kept as
    a separate plain class (not the pydantic response model itself) so
    this module stays free of any FastAPI/response-shape concerns and is
    trivially constructible in tests.
    """

    def __init__(
        self,
        score: float,
        band: DifficultyBand,
        counted_tokens: int,
        known_tokens: int,
        unknown_tokens: int,
        partial_credit_words: int,
        weakest_words: list[dict],
    ):
        self.score = score
        self.band = band
        self.counted_tokens = counted_tokens
        self.known_tokens = known_tokens
        self.unknown_tokens = unknown_tokens
        self.partial_credit_words = partial_credit_words
        self.weakest_words = weakest_words


def compute_difficulty(
    results: list[WordResult], known_words: dict[str, int]
) -> DifficultyBreakdown | None:
    """
    Computes the overall difficulty breakdown for one analysis's results.

    Only counts rows whose source is in MAIN_SEGMENTATION_SOURCES -
    supplemental rows (extra_match/repeated_sequence, legacy
    token/longest_match_only) annotate ranges a main-segmentation row
    already covers, so counting them too would double-count tokens
    against the same stretch of text.

    is_garbage rows and non-Chinese words (see _contains_chinese) are
    excluded from the count entirely. v1 originally counted garbage words
    on the reasoning that "marked garbage" isn't "costs nothing to read" -
    but real usage showed the actual problem: a text mixing in English
    words (each its own zero-familiarity "word" with no Mandarin
    vocabulary to know in the first place) tanked the score on words that
    were never a Mandarin-reading obstacle at all, and dominated "weighing
    your score down most" with single English letters instead of real
    unknown Chinese vocabulary. Garbage words are excluded for the same
    reason once non-Chinese ones are: numbers/punctuation are exactly the
    other "not really Mandarin vocabulary" case GarbageWord exists to
    flag, and the whole point of building this exclusion for non-Chinese
    text was to stop scoring things that were never a reading-comprehension
    signal to begin with.

    Returns None when there are zero counted tokens (e.g. an empty text,
    or one that's entirely garbage/non-Chinese) - "not enough data" rather
    than a misleading score.
    """
    counted = [
        r for r in results
        if r.source in MAIN_SEGMENTATION_SOURCES and not r.is_garbage and _contains_chinese(r.word)
    ]
    total_tokens = sum(r.count for r in counted)
    if total_tokens == 0:
        return None

    known_tokens = 0
    unknown_tokens = 0
    partial_credit_words = 0
    weighted_sum = 0.0
    weakest: list[dict] = []

    for r in counted:
        weight = effective_weight(r.word, r.familiarity, known_words)
        weighted_sum += weight * r.count

        if weight >= KNOWN_WEIGHT_CUTOFF:
            known_tokens += r.count
        else:
            unknown_tokens += r.count

        if len(r.word) > 1 and weight > _familiarity_weight(r.familiarity):
            partial_credit_words += 1

        weakest.append({"word": r.word, "count": r.count, "effective_weight": weight})

    score = weighted_sum / total_tokens
    band = _band_for(score)

    # Lowest effective_weight first, ties broken by count desc (a frequent
    # weak word is more worth surfacing than a rare one at the same
    # weight) - top 10 gives the UI something concrete to point to without
    # dumping every unknown word in the text.
    weakest.sort(key=lambda w: (w["effective_weight"], -w["count"]))
    weakest_words = weakest[:10]

    return DifficultyBreakdown(
        score=score,
        band=band,
        counted_tokens=total_tokens,
        known_tokens=known_tokens,
        unknown_tokens=unknown_tokens,
        partial_credit_words=partial_credit_words,
        weakest_words=weakest_words,
    )
