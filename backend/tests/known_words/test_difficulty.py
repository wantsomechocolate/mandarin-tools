"""
Standalone tests for app.modules.known_words.difficulty - pure-function
pieces that don't need a Postgres connection. Run with:

    uv run pytest tests/known_words/test_difficulty.py -v
"""

from app.modules.known_words.difficulty import (
    compute_difficulty,
    effective_weight,
    _band_for,
    FAMILIARITY_WEIGHTS,
)
from app.modules.known_words.schemas import WordResult


def _wr(word: str, count: int, source: str = "dag", familiarity: int | None = None, is_garbage: bool = False) -> WordResult:
    return WordResult(word=word, count=count, source=source, familiarity=familiarity, is_garbage=is_garbage)


class TestEffectiveWeight:
    def test_direct_familiarity_mapping(self):
        for level, expected in FAMILIARITY_WEIGHTS.items():
            assert effective_weight("的", level, known_words={}) == expected

    def test_unmarked_word_is_zero(self):
        assert effective_weight("陌生", None, known_words={}) == 0.0

    def test_character_decomposition_gives_partial_credit(self):
        # 希奇 is itself unmarked, but both of its characters are known via
        # 希望/奇怪 (familiarity 5 each) - this is the motivating case from
        # the brainstorm: recognizing both characters should meaningfully
        # reduce the readability hit versus a totally unfamiliar word, but
        # never fully replace actually knowing 希奇 means "strange/rare".
        known_words = {"希": 5, "奇": 5}
        weight = effective_weight("希奇", None, known_words)
        assert 0.0 < weight < 1.0
        assert weight == FAMILIARITY_WEIGHTS[5] * 0.5  # discount * full known_fraction * mean weight

    def test_partial_character_knowledge_scores_lower_than_full(self):
        both_known = effective_weight("希奇", None, {"希": 5, "奇": 5})
        one_known = effective_weight("希奇", None, {"希": 5})
        assert one_known < both_known
        assert one_known > 0.0

    def test_decomposition_never_used_for_single_characters(self):
        # No smaller unit to decompose into - a single character's weight
        # is always just its own direct familiarity.
        assert effective_weight("的", None, known_words={"的": 5}) == 0.0

    def test_decomposition_never_scores_below_direct_familiarity(self):
        # A word that already has its own (higher) direct familiarity is
        # never dragged down by weak/absent character data.
        weight = effective_weight("希奇", 5, known_words={})
        assert weight == FAMILIARITY_WEIGHTS[5]


class TestComputeDifficulty:
    def test_all_known_scores_near_one(self):
        results = [_wr("我们", 10, familiarity=5), _wr("知道", 5, familiarity=5)]
        breakdown = compute_difficulty(results, known_words={})
        assert breakdown.score == 1.0
        assert breakdown.band == "very_easy"

    def test_all_unknown_scores_zero_and_very_difficult(self):
        results = [_wr("陌生", 10), _wr("生词", 5)]
        breakdown = compute_difficulty(results, known_words={})
        assert breakdown.score == 0.0
        assert breakdown.band == "very_difficult"

    def test_garbage_words_are_excluded_from_score_and_main_segmentation(self):
        # Garbage rows drag score down on words that were never real
        # Mandarin vocabulary - excluded from scoring, and from the Main
        # segmentation column, landing in Extra Matches instead (see
        # compute_difficulty's docstring on why "Extra Matches" absorbs
        # excluded main-segmentation rows, not just supplemental sources).
        clean_only = compute_difficulty([_wr("我们", 10, familiarity=5)], known_words={})
        with_garbage = compute_difficulty(
            [_wr("我们", 10, familiarity=5), _wr("陌生", 10, is_garbage=True)],
            known_words={},
        )
        assert with_garbage.score == clean_only.score
        assert with_garbage.main_segmentation.total_tokens.total == clean_only.main_segmentation.total_tokens.total
        assert with_garbage.extra_matches.total_tokens.total == 10
        assert with_garbage.extra_matches.total_tokens.unique == 1

    def test_non_chinese_words_are_excluded_from_score_and_main_segmentation(self):
        # A lone English word has no Mandarin familiarity to score - it
        # must not affect the score, and (same as garbage above) shows up
        # under Extra Matches instead of vanishing entirely.
        clean_only = compute_difficulty([_wr("我们", 10, familiarity=5)], known_words={})
        with_english = compute_difficulty(
            [_wr("我们", 10, familiarity=5), _wr("hello", 10)],
            known_words={},
        )
        assert with_english.score == clean_only.score
        assert with_english.main_segmentation.total_tokens.total == clean_only.main_segmentation.total_tokens.total
        assert "hello" not in [w["word"] for w in with_english.weakest_words]
        assert with_english.extra_matches.total_tokens.total == 10

    def test_mixed_chinese_and_non_chinese_word_still_scored(self):
        # Only words with ZERO CJK characters are excluded - a word mixing
        # Chinese with a digit/letter still counts toward Main segmentation
        # and the score, mirroring the results page's own Non-Chinese
        # bucket (containsChinese) exactly.
        breakdown = compute_difficulty([_wr("生词A", 5)], known_words={})
        assert breakdown is not None
        assert breakdown.main_segmentation.total_tokens.total == 5

    def test_extra_match_source_rows_land_in_extra_matches_not_main_segmentation(self):
        # extra_match/longest_match_only annotate a range a main-segmentation
        # row already covers - counting both toward the score would
        # double-count tokens, so they're scored as 0 contribution and
        # bucketed under Extra Matches instead.
        results = [
            _wr("我们", 10, source="dag", familiarity=5),
            _wr("们", 3, source="longest_match_only", familiarity=1),
        ]
        breakdown = compute_difficulty(results, known_words={})
        assert breakdown.main_segmentation.total_tokens.total == 10
        assert breakdown.score == 1.0
        assert breakdown.extra_matches.total_tokens.total == 3
        assert breakdown.extra_matches.total_tokens.unique == 1

    def test_empty_results_returns_none(self):
        assert compute_difficulty([], known_words={}) is None

    def test_only_non_main_segmentation_results_returns_none(self):
        results = [_wr("们", 3, source="longest_match_only", familiarity=1)]
        assert compute_difficulty(results, known_words={}) is None

    def test_only_garbage_and_non_chinese_results_returns_none(self):
        results = [_wr("999", 3, is_garbage=True), _wr("OK", 2)]
        assert compute_difficulty(results, known_words={}) is None

    def test_familiarity_level_buckets_partition_main_segmentation(self):
        results = [
            _wr("甲", 10, familiarity=5),
            _wr("乙", 7, familiarity=4),
            _wr("丙", 5, familiarity=3),
            _wr("丁", 3, familiarity=2),
            _wr("戊", 2, familiarity=1),
            _wr("己", 1),  # unmarked -> unknown
        ]
        m = compute_difficulty(results, known_words={}).main_segmentation
        assert (m.known_5.unique, m.known_5.total) == (1, 10)
        assert (m.known_4.unique, m.known_4.total) == (1, 7)
        assert (m.known_3.unique, m.known_3.total) == (1, 5)
        assert (m.known_2.unique, m.known_2.total) == (1, 3)
        assert (m.known_1.unique, m.known_1.total) == (1, 2)
        assert (m.unknown.unique, m.unknown.total) == (1, 1)
        assert (m.total_tokens.unique, m.total_tokens.total) == (6, 28)

    def test_partial_credit_bucket_counts_unique_and_total(self):
        results = [
            _wr("希奇", 4),  # boosted via character decomposition below
            _wr("我们", 6, familiarity=5),  # not boosted - already fully known
        ]
        m = compute_difficulty(results, known_words={"希": 5, "奇": 5}).main_segmentation
        assert (m.partial_credit.unique, m.partial_credit.total) == (1, 4)

    def test_weighted_average_familiarity_uses_raw_familiarity_not_effective_weight(self):
        # Two words at familiarity 4 and 2, weighted by count (3 and 1):
        # (4*3 + 2*1) / 4 = 3.5 - plain familiarity scale, unaffected by
        # any character-decomposition credit either word might also get.
        results = [_wr("甲乙", 3, familiarity=4), _wr("丙丁", 1, familiarity=2)]
        m = compute_difficulty(results, known_words={}).main_segmentation
        assert m.weighted_average_familiarity == 3.5

    def test_weighted_average_familiarity_treats_unmarked_as_zero(self):
        results = [_wr("甲", 1, familiarity=5), _wr("乙", 1)]
        m = compute_difficulty(results, known_words={}).main_segmentation
        assert m.weighted_average_familiarity == 2.5  # (5*1 + 0*1) / 2

    def test_weighted_average_familiarity_none_when_bucket_empty(self):
        breakdown = compute_difficulty([_wr("甲", 1, familiarity=5)], known_words={})
        assert breakdown.extra_matches.total_tokens.total == 0
        assert breakdown.extra_matches.weighted_average_familiarity is None

    def test_weakest_words_sorted_lowest_weight_first_ties_by_count(self):
        # weakest_words is every scored word ordered lowest-weight-first
        # (not filtered to "unknown" ones) - with only 3 distinct words
        # here, the fully-known one still appears, just last.
        results = [
            _wr("常见", 20),  # unknown, high count
            _wr("罕见", 2),  # unknown, low count
            _wr("我们", 5, familiarity=5),  # known - highest weight, sorts last
        ]
        breakdown = compute_difficulty(results, known_words={})
        weakest_words_in_order = [w["word"] for w in breakdown.weakest_words]
        assert weakest_words_in_order[0] == "常见"  # same (zero) weight, higher count first
        assert weakest_words_in_order[1] == "罕见"
        assert weakest_words_in_order[2] == "我们"

    def test_weakest_words_truncated_to_ten(self):
        results = [_wr(f"生词{i}", 1) for i in range(15)]
        breakdown = compute_difficulty(results, known_words={})
        assert len(breakdown.weakest_words) == 10


class TestBandCutoffs:
    def test_all_five_boundaries(self):
        assert _band_for(1.0) == "very_easy"
        assert _band_for(0.99) == "very_easy"
        assert _band_for(0.989) == "easy"
        assert _band_for(0.98) == "easy"
        assert _band_for(0.979) == "manageable"
        assert _band_for(0.95) == "manageable"
        assert _band_for(0.949) == "difficult"
        assert _band_for(0.90) == "difficult"
        assert _band_for(0.899) == "very_difficult"
        assert _band_for(0.0) == "very_difficult"
