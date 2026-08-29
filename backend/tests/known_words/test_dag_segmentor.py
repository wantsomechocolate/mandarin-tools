"""
Standalone tests for the DAG+DP segmenter using a small synthetic
dictionary - no Postgres connection required. Run with:

    uv run pytest tests/known_words/test_dag_segmentor.py -v

These check the specific property longest-matching lacks: that the segmenter
picks the *globally* best-scoring path through a sentence, not just the
locally longest match at each position.
"""

import pytest

from app.modules.known_words.trie import Trie
from app.modules.known_words.dag_segmentor import Segmenter, UserOverlay, aggregate_segments
from app.modules.known_words.segmentor import longest_matching


# A small hand-built dictionary covering the classic ambiguous case
# (研究生命起源 -> should split as 研究/生命/起源, not 研究生/命/起源)
# plus a few other common jieba README examples for sanity.
SAMPLE_FREQ = {
    "我": 50000,
    "来到": 3000,
    "北京": 8000,
    "清华": 2000,
    "清华大学": 5000,
    "华大": 100,
    "大学": 6000,
    "研究": 4000,
    "研究生": 3500,
    "生命": 3000,
    "命": 800,
    "起源": 1500,
}


@pytest.fixture
def trie() -> Trie:
    t = Trie()
    for word in SAMPLE_FREQ:
        t.insert(word)
    return t


@pytest.fixture
def segmenter(trie: Trie) -> Segmenter:
    return Segmenter(trie=trie, freq_dict=dict(SAMPLE_FREQ))


def words(results) -> list[str]:
    return [r.word for r in results]


class TestDagSegmenterBasics:
    def test_simple_sentence(self, segmenter: Segmenter):
        result = segmenter.segment("我来到北京清华大学")
        assert words(result) == ["我", "来到", "北京", "清华大学"]

    def test_empty_string(self, segmenter: Segmenter):
        assert segmenter.segment("") == []

    def test_unknown_characters_fall_back_to_singletons(self, segmenter: Segmenter):
        # "谊" isn't in the dictionary at all
        result = segmenter.segment("谊")
        assert words(result) == ["谊"]
        assert result[0].in_dictionary is False


class TestDagVsLongestMatch:
    """
    The core case DAG+DP is supposed to fix: longest-matching greedily grabs
    研究生 (the longest match starting at position 0), which then forces an
    awkward split of 命 and 起源 from what should be 生命起源. DAG+DP should
    prefer 研究/生命/起源 instead, since that path scores higher overall even
    though 研究生 alone is a "longer" individual match.
    """

    def test_dag_prefers_globally_better_split(self, segmenter: Segmenter, trie: Trie):
        text = "研究生命起源"

        dag_result = words(segmenter.segment(text))
        lm_result_raw = longest_matching(text, trie, stopwords=set())
        lm_result = list(lm_result_raw.keys())

        assert dag_result == ["研究", "生命", "起源"]
        # Demonstrate the difference actually exists in this fixture -
        # if longest-matching happened to agree, this test wouldn't be
        # proving anything about the DP's benefit.
        assert lm_result != dag_result


class TestUserOverlay:
    def test_overlay_word_wins_over_default_split(self, segmenter: Segmenter):
        # Without an overlay, "清华" + "大学" or "清华大学" both exist in the
        # base dictionary already, so pick a case where the overlay word
        # genuinely isn't segmentable correctly without it.
        overlay = UserOverlay()
        overlay.add_word("研究生命", freq=None, dominance_floor=segmenter.dominance_floor())

        result = segmenter.segment("研究生命起源", overlay=overlay)
        assert words(result) == ["研究生命", "起源"]
        assert result[0].from_overlay is True

    def test_overlay_none_behaves_like_no_overlay(self, segmenter: Segmenter):
        with_none = segmenter.segment("我来到北京", overlay=None)
        without_arg = segmenter.segment("我来到北京")
        assert words(with_none) == words(without_arg)

    def test_overlay_does_not_mutate_shared_segmenter(self, segmenter: Segmenter):
        original_freq_count = len(segmenter.freq)
        overlay = UserOverlay()
        overlay.add_word("研究生命", freq=None, dominance_floor=segmenter.dominance_floor())
        segmenter.segment("研究生命起源", overlay=overlay)

        assert len(segmenter.freq) == original_freq_count
        assert "研究生命" not in segmenter.freq


class TestAggregateSegments:
    def test_counts_repeats_and_labels_source(self, segmenter: Segmenter):
        result = segmenter.segment("我来到北京我来到北京")
        agg = aggregate_segments(result)
        assert agg["我"]["count"] == 2
        assert agg["我"]["source"] == "dag"

    def test_unknown_source_label(self, segmenter: Segmenter):
        result = segmenter.segment("谊")
        agg = aggregate_segments(result)
        assert agg["谊"]["source"] == "unknown"

    def test_overlay_source_label(self, segmenter: Segmenter):
        overlay = UserOverlay()
        overlay.add_word("研究生命", freq=None, dominance_floor=segmenter.dominance_floor())
        result = segmenter.segment("研究生命起源", overlay=overlay)
        agg = aggregate_segments(result)
        assert agg["研究生命"]["source"] == "overlay"


class TestAffixDiscount:
    """
    Covers the 森林/森林里 case from real usage: a rare compound ending in a
    common locative suffix (里) can out-score splitting into stem+suffix
    purely because it clears the DP's "more than chance co-occurrence" bar,
    even though it's a compositional string, not real vocabulary. The
    numbers here are small synthetic stand-ins for the real
    freq(森林)=627,741 / freq(里)=19,397,088 / freq(森林里)=13,177 case, tuned
    so the same qualitative flip happens: undiscounted the compound wins,
    discounted it loses to the split.
    """

    def test_rare_compound_merges_without_discount(self):
        freq = {"森林": 6000, "里": 100000, "森林里": 8000}
        trie = Trie()
        for w in freq:
            trie.insert(w)
        segmenter = Segmenter(trie=trie, freq_dict=freq)  # no suffix_discounts

        assert words(segmenter.segment("森林里")) == ["森林里"]

    def test_rare_compound_splits_with_discount(self):
        freq = {"森林": 6000, "里": 100000, "森林里": 8000}
        trie = Trie()
        for w in freq:
            trie.insert(w)
        segmenter = Segmenter(trie=trie, freq_dict=freq, suffix_discounts={"里": 0.1})

        assert words(segmenter.segment("森林里")) == ["森林", "里"]

    def test_common_compound_stays_merged_despite_discount(self):
        # 这里-style: a compound common enough that even a 10x discount
        # doesn't bring it below the split alternative.
        freq = {"这": 50000, "里": 100000, "这里": 300000}
        trie = Trie()
        for w in freq:
            trie.insert(w)
        segmenter = Segmenter(trie=trie, freq_dict=freq, suffix_discounts={"里": 0.1})

        assert words(segmenter.segment("这里")) == ["这里"]

    def test_bare_affix_character_is_never_discounted(self):
        freq = {"森林": 6000, "里": 100000, "森林里": 8000}
        trie = Trie()
        for w in freq:
            trie.insert(w)
        segmenter = Segmenter(trie=trie, freq_dict=freq, suffix_discounts={"里": 0.1})

        # word == affix, not longer than it - discount must not apply
        assert segmenter._affix_discount("里") == 1.0
        # a genuine compound ending in the affix does get discounted
        assert segmenter._affix_discount("森林里") == 0.1

    def test_exemption_protects_a_word_from_discount(self):
        freq = {"森林": 6000, "里": 100000, "森林里": 8000}
        trie = Trie()
        for w in freq:
            trie.insert(w)
        segmenter = Segmenter(
            trie=trie,
            freq_dict=freq,
            suffix_discounts={"里": 0.1},
            exemptions={"森林里"},
        )

        # Same numbers as test_rare_compound_splits_with_discount, but this
        # time the word is exempted, so it should merge like the undiscounted case.
        assert words(segmenter.segment("森林里")) == ["森林里"]


class TestCombinedAnalysis:
    """
    Covers the 大风车 case directly: a word missing from the dictionary
    entirely has no DAG path, but longest_matching's overlapping-match scan
    can still surface fragments of it. The combined view should never let
    those fragments silently override or hide what the DAG already decided,
    only supplement it.
    """

    def test_longest_match_only_words_are_tagged_supplemental(self):
        from app.modules.known_words.segmentor import longest_matching
        from app.modules.known_words.dag_segmentor import aggregate_segments

        freq = {"大风": 1000, "风车": 800, "车": 500, "快速": 2000, "转动": 1500}
        trie = Trie()
        for w in freq:
            trie.insert(w)
        segmenter = Segmenter(trie=trie, freq_dict=freq)

        text = "大风车快速转动"
        dag_merged = aggregate_segments(segmenter.segment(text))
        lm_merged = longest_matching(text, trie, stopwords=set())

        combined = dict(dag_merged)
        for word, data in lm_merged.items():
            if word not in combined:
                combined[word] = {**data, "source": "longest_match_only"}

        # DAG's own picks are untouched
        assert combined["快速"]["source"] == "dag"
        assert combined["转动"]["source"] == "dag"
        # 风车 only came from longest_matching's overlapping scan - present,
        # but clearly marked as lower-confidence rather than silently primary
        assert "风车" in combined
        assert combined["风车"]["source"] == "longest_match_only"
        # words the DAG did find are never demoted even if longest_matching
        # also happens to report them
        assert combined["大风"]["source"] == "dag"
