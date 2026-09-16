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
#
# Deliberately does NOT include "repeated_sequence"/"token" outright, even
# though service._promote_confirmed_unknown_runs can now relabel a
# best-guess row to "repeated_sequence" - most repeated_sequence rows are
# NOT part of best-guess's disjoint walk (a pure tokenizer find never gets
# real positions at all - see aggregate_full_segmentation's docstring,
# dag_segmentor.py), and counting those here would double-count tokens
# against a stretch of text a real main-segmentation row already covers,
# exactly the bug this constant exists to prevent. A *promoted* row is the
# one exception - it keeps its real best-guess position, unchanged, so it's
# exactly as disjoint as any other best-guess row. `positions` is what
# distinguishes the two cases (present only for the promoted kind - see
# router.py's persistence comment, "positions is only present for words
# that came from the DAG's own ordered walk") - see is_main_segmentation_row
# below, usable by any raw-AnalysisResult caller that has `positions` in
# hand. compute_difficulty below deliberately does NOT use it - it only
# ever sees WordResult (schemas.py), which has no `positions` field to
# check - so a promoted row's Chinese-only, non-garbage content (rare: the
# DAG's per-character fallback that produces a mergeable "unknown" run
# almost always fires on non-Chinese text in the first place, which
# _contains_chinese already excludes here regardless) simply doesn't count
# toward difficulty, same as before this feature existed. Narrow known gap,
# not fixed here - revisit only if it turns out to matter in practice.
MAIN_SEGMENTATION_SOURCES = {"dag", "overlay", "unknown", "trie"}


def is_main_segmentation_row(source: str, positions) -> bool:
    """
    Whether a raw AnalysisResult row counts as part of best-guess's disjoint
    walk - true for the ordinary dag/overlay/unknown/trie sources, plus a
    "repeated_sequence"/"token" row *only* when it carries real positions
    (meaning it's a promoted merged-unknown-run, not a pure supplemental
    tokenizer find - see MAIN_SEGMENTATION_SOURCES' own comment above for
    why that distinction matters here). Only usable where `positions` is
    actually in hand (e.g. router.py's /spans endpoint, querying
    AnalysisResult directly) - see that same comment for why
    compute_difficulty below can't use this.
    """
    if source in MAIN_SEGMENTATION_SOURCES:
        return True
    return source in ("repeated_sequence", "token") and bool(positions)

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


def _is_scored(r: WordResult) -> bool:
    """
    Whether a word counts toward the actual difficulty score - a
    main-segmentation row (see MAIN_SEGMENTATION_SOURCES) that's neither
    garbage nor non-Chinese. This is also the dividing line the breakdown
    table below uses for its two columns: every word in an analysis falls
    on exactly one side of it (AnalysisResult has one row per word, never
    duplicated across sources - see its docstring, models.py), so "Main
    segmentation" and "Extra Matches" together always account for the
    whole text with no overlap and no gaps.
    """
    return r.source in MAIN_SEGMENTATION_SOURCES and not r.is_garbage and _contains_chinese(r.word)


class TokenCounts:
    """
    unique/total pair - `unique` is the number of distinct words in this
    bucket (rows), `total` is their combined occurrence count. Reported
    together everywhere in the breakdown table because they answer
    different questions ("how many different words is this?" vs. "how
    much of the text is this?") and neither alone is enough: a single very
    common unknown word can dwarf the token count of ten rare known ones.
    """

    def __init__(self, unique: int, total: int):
        self.unique = unique
        self.total = total


def _token_counts(rows: list[WordResult]) -> TokenCounts:
    return TokenCounts(unique=len(rows), total=sum(r.count for r in rows))


class SegmentationBucketBreakdown:
    """
    Plain result container for _segmentation_stats - one of these per
    "Main segmentation"/"Extra Matches" column in the breakdown table.
    known_5..known_1/unknown partition every row in this bucket by its OWN
    direct KnownWord.familiarity (never by effective_weight - see
    weighted_average_familiarity below for why the two are kept apart).
    partial_credit and weighted_average_familiarity are computed the same
    way for both columns (see _segmentation_stats) purely as an
    informational parallel - only the Main segmentation column's numbers
    actually feed the overall score/band.
    """

    def __init__(
        self,
        known_5: TokenCounts,
        known_4: TokenCounts,
        known_3: TokenCounts,
        known_2: TokenCounts,
        known_1: TokenCounts,
        unknown: TokenCounts,
        total_tokens: TokenCounts,
        partial_credit: TokenCounts,
        weighted_average_familiarity: float | None,
    ):
        self.known_5 = known_5
        self.known_4 = known_4
        self.known_3 = known_3
        self.known_2 = known_2
        self.known_1 = known_1
        self.unknown = unknown
        self.total_tokens = total_tokens
        self.partial_credit = partial_credit
        self.weighted_average_familiarity = weighted_average_familiarity


def _segmentation_stats(rows: list[WordResult], known_words: dict[str, int]) -> SegmentationBucketBreakdown:
    """
    Buckets one column's worth of rows (either the scored main-segmentation
    set or everything else - see _is_scored) by familiarity level, plus
    two summary rows:

    - partial_credit: rows whose effective_weight (familiarity +
      character-decomposition credit) exceeds their own direct familiarity
      - i.e. words the char-decomposition piece is actually helping, same
        condition compute_difficulty's old partial_credit_words used, now
        tracked with a token TOTAL alongside the unique count.
    - weighted_average_familiarity: the token-count-weighted average of
      each row's own RAW familiarity (1-5, unmarked words counting as 0) -
      deliberately NOT effective_weight. effective_weight is a [0,1]
      scoring input already discounted for character-decomposition
      credit; this row is meant to answer a different, plainer question -
      "on average, how well-known (on the 1-5 scale you already see
      everywhere else in this app) are the words in this bucket" - so it
      stays on that same familiarity scale rather than mixing two
      different numeric scales into one row. None when the bucket has no
      tokens at all.
    """
    by_familiarity: dict[int, list[WordResult]] = {n: [] for n in range(1, 6)}
    unknown_rows: list[WordResult] = []
    partial_credit_rows: list[WordResult] = []
    familiarity_weighted_sum = 0.0
    total_count = 0

    for r in rows:
        if r.familiarity in by_familiarity:
            by_familiarity[r.familiarity].append(r)
        else:
            unknown_rows.append(r)

        if effective_weight(r.word, r.familiarity, known_words) > _familiarity_weight(r.familiarity):
            partial_credit_rows.append(r)

        familiarity_weighted_sum += (r.familiarity or 0) * r.count
        total_count += r.count

    return SegmentationBucketBreakdown(
        known_5=_token_counts(by_familiarity[5]),
        known_4=_token_counts(by_familiarity[4]),
        known_3=_token_counts(by_familiarity[3]),
        known_2=_token_counts(by_familiarity[2]),
        known_1=_token_counts(by_familiarity[1]),
        unknown=_token_counts(unknown_rows),
        total_tokens=_token_counts(rows),
        partial_credit=_token_counts(partial_credit_rows),
        weighted_average_familiarity=(familiarity_weighted_sum / total_count) if total_count else None,
    )


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
        main_segmentation: SegmentationBucketBreakdown,
        extra_matches: SegmentationBucketBreakdown,
        weakest_words: list[dict],
    ):
        self.score = score
        self.band = band
        self.main_segmentation = main_segmentation
        self.extra_matches = extra_matches
        self.weakest_words = weakest_words


def compute_difficulty(
    results: list[WordResult], known_words: dict[str, int]
) -> DifficultyBreakdown | None:
    """
    Computes the overall difficulty breakdown for one analysis's results.

    Splits `results` into exactly two groups via _is_scored: the scored
    set (main-segmentation, non-garbage, Chinese words - the same set the
    score/band and "weighing your score down most" have always used) and
    everything else, labeled "Extra Matches" in the breakdown table -
    supplemental segmentation passes (extra_match/repeated_sequence,
    legacy token/longest_match_only) PLUS any main-segmentation-sourced
    row that got excluded from scoring for being garbage or non-Chinese.
    Grouping it this way means every word in the analysis lands in exactly
    one column, and "Extra Matches" means exactly what its caption says on
    the results page: tokens that may or may not be of interest to you,
    but that never counted toward your score - whether because they're a
    supplemental find or because they were never real Mandarin vocabulary
    to begin with.

    score/band are computed only from the scored set (token-weighted
    average of effective_weight, same as always). main_segmentation/
    extra_matches are full SegmentationBucketBreakdown stats computed the
    same way for both groups (see _segmentation_stats) - the Extra Matches
    side is purely informational, never used to compute score/band.

    Returns None when there are zero scored tokens (e.g. an empty text, or
    one that's entirely garbage/non-Chinese) - "not enough data" rather
    than a misleading score. A text can still have Extra Matches with no
    scored tokens at all; that also returns None, same as an empty text -
    there's nothing to score either way.
    """
    scored = [r for r in results if _is_scored(r)]
    other = [r for r in results if not _is_scored(r)]

    total_tokens = sum(r.count for r in scored)
    if total_tokens == 0:
        return None

    weighted_sum = 0.0
    weakest: list[dict] = []
    for r in scored:
        weight = effective_weight(r.word, r.familiarity, known_words)
        weighted_sum += weight * r.count
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
        main_segmentation=_segmentation_stats(scored, known_words),
        extra_matches=_segmentation_stats(other, known_words),
        weakest_words=weakest_words,
    )
