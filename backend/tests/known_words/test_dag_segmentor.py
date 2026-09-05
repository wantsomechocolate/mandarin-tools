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
from app.modules.known_words.dag_segmentor import Segmenter, UserOverlay, aggregate_segments, aggregate_full_segmentation


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


class TestDictionaryOnlyWords:
    """
    Covers the in_dictionary bug fix: a word can be a real trie hit (backed
    by HSK/CC-CEDICT alone, in the real dictionary_words data) with no
    frequency row at all - self.freq (segmenter_loader._build_segmenter) is
    deliberately restricted to rows with usable frequency, while the trie
    is built from every dictionary_words row regardless. in_dictionary must
    key off trie membership, not `word in self.freq`, or a legitimate
    dictionary word the DAG walked straight through gets mislabeled
    "unknown".
    """

    def test_trie_contains_matches_inserted_words(self):
        trie = Trie()
        trie.insert("你好")
        assert trie.contains("你好") is True
        assert trie.contains("你") is False  # prefix only, never inserted as its own word
        assert trie.contains("再见") is False  # not in the trie at all

    def test_word_with_no_frequency_row_still_counts_as_in_dictionary(self):
        # "谊" is in the trie (as it would be via an HSK/CC-CEDICT-only
        # dictionary_words row) but deliberately absent from freq_dict -
        # freq_dict must stay non-empty for Segmenter's own validation.
        trie = Trie()
        trie.insert("我")
        trie.insert("谊")
        segmenter = Segmenter(trie=trie, freq_dict={"我": 50000})

        result = segmenter.segment("我谊")
        assert words(result) == ["我", "谊"]
        yi_result = next(r for r in result if r.word == "谊")
        assert yi_result.in_dictionary is True

        agg = aggregate_segments(result)
        assert agg["谊"]["source"] == "dag"  # not "unknown"


class TestDagChoosesGloballyBetterSplit:
    """
    The core benefit DP scoring provides over any greedy/local matching
    approach: 研究生 is a real dictionary word startable at position 0, but
    taking it forces an awkward split of 命/起源 from what should be
    生命/起源. The DP should prefer 研究/生命/起源 instead, since that path
    scores higher overall - even though 研究生 alone is a "longer"
    individual match at that position.
    """

    def test_dag_prefers_globally_better_split(self, segmenter: Segmenter):
        text = "研究生命起源"
        assert words(segmenter.segment(text)) == ["研究", "生命", "起源"]

    def test_unchosen_local_alternative_still_appears_in_full_segmentation(self, segmenter: Segmenter):
        # Proves the DP genuinely chose between real alternatives, not that
        # 研究生 was somehow unreachable - it's still there as a considered-
        # but-passed-over candidate, just never in best-guess.
        text = "研究生命起源"
        dag = segmenter.build_dag(text, overlay=None)
        best_guess = aggregate_segments(segmenter.segment(text, dag=dag))
        full = aggregate_full_segmentation(text, dag)

        assert "研究生" not in best_guess
        assert "研究生" in full


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


class TestFloorBasedUserWords:
    """
    Covers the affects_dag=false rewrite: a UserWord scoped to not affect
    segmentation is no longer excluded from the overlay entirely - it's
    still inserted into the trie (so it's always a real candidate) but
    never given a competitive frequency (see UserOverlay.add_word's
    docstring), so it essentially never wins best-guess while still
    surfacing via full segmentation. affects_dag=true keeps behaving
    exactly as before (regression check, alongside
    TestUserOverlay.test_overlay_word_wins_over_default_split above).
    """

    def test_affects_dag_true_still_reliably_wins_best_guess(self, segmenter: Segmenter):
        overlay = UserOverlay()
        overlay.add_word("研究生命", freq=None, dominance_floor=segmenter.dominance_floor(), affects_dag=True)

        assert "研究生命" in overlay.freq
        result = segmenter.segment("研究生命起源", overlay=overlay)
        assert words(result) == ["研究生命", "起源"]

    def test_affects_dag_false_is_trie_resident_but_not_in_freq(self, segmenter: Segmenter):
        overlay = UserOverlay()
        overlay.add_word("生命起源", freq=None, dominance_floor=segmenter.dominance_floor(), affects_dag=False)

        assert overlay.trie.contains("生命起源") is True
        assert "生命起源" not in overlay.freq

    def test_affects_dag_false_essentially_never_wins_best_guess(self, segmenter: Segmenter):
        # Without the overlay, "生命"/"起源" (both real, decently-frequent
        # dictionary words) already split cleanly - a personal word with no
        # real frequency shouldn't be able to out-score that real
        # alternative just by existing in the trie.
        overlay = UserOverlay()
        overlay.add_word("生命起源", freq=None, dominance_floor=segmenter.dominance_floor(), affects_dag=False)

        result = segmenter.segment("生命起源", overlay=overlay)
        assert words(result) == ["生命", "起源"]

    def test_affects_dag_false_still_appears_in_full_segmentation(self, segmenter: Segmenter):
        # The actual point: "don't drive segmentation" must not mean
        # "invisible" - it should still surface as a real, findable
        # candidate (an "extra match" once merged in service.analyze_text).
        overlay = UserOverlay()
        overlay.add_word("生命起源", freq=None, dominance_floor=segmenter.dominance_floor(), affects_dag=False)

        text = "生命起源"
        dag = segmenter.build_dag(text, overlay=overlay)
        best_guess = aggregate_segments(segmenter.segment(text, overlay=overlay, dag=dag))
        full = aggregate_full_segmentation(text, dag)

        assert "生命起源" not in best_guess
        assert "生命起源" in full


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

    def test_positions_recorded_per_occurrence(self, segmenter: Segmenter):
        # "我来到北京我来到北京" -> 我/来到/北京/我/来到/北京
        result = segmenter.segment("我来到北京我来到北京")
        agg = aggregate_segments(result)
        assert agg["我"]["positions"] == [(0, 1), (5, 6)]
        assert agg["来到"]["positions"] == [(1, 3), (6, 8)]
        assert agg["北京"]["positions"] == [(3, 5), (8, 10)]

    def test_positions_recorded_for_unknown_and_overlay_sources(self, segmenter: Segmenter):
        # Positions come from the DAG's own ordered walk, so they're
        # available regardless of which source label a word ends up with -
        # not just for plain "dag" words.
        unknown_result = segmenter.segment("谊")
        assert aggregate_segments(unknown_result)["谊"]["positions"] == [(0, 1)]

        overlay = UserOverlay()
        overlay.add_word("研究生命", freq=None, dominance_floor=segmenter.dominance_floor())
        overlay_result = segmenter.segment("研究生命起源", overlay=overlay)
        assert aggregate_segments(overlay_result)["研究生命"]["positions"] == [(0, 4)]


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


class TestFullSegmentation:
    """
    Covers the 风车 case directly - this used to require segmentor.py's
    longest_matching (its overlapping-match scan happened to stumble onto
    风车 even though the DAG's own chosen route skips over it: "大风"
    starting at position 0 already spans past position 1, so best-guess's
    route never independently visits it). Full segmentation has no such
    blind spot: it walks every position's own candidates regardless of
    whether the DP's chosen route ever passes through that position, so a
    real trie hit like 风车 (startable at position 1) shows up on its own,
    with no separate algorithm needed - this is what fully replaces
    longest_matching's role as a dictionary-coverage safety net.
    """

    def test_full_segmentation_finds_words_best_guess_route_skips_over(self):
        freq = {"大风": 1000, "风车": 800, "车": 500, "快速": 2000, "转动": 1500}
        trie = Trie()
        for w in freq:
            trie.insert(w)
        segmenter = Segmenter(trie=trie, freq_dict=freq)

        text = "大风车快速转动"
        dag = segmenter.build_dag(text, overlay=None)
        best_guess = aggregate_segments(segmenter.segment(text, dag=dag))
        full = aggregate_full_segmentation(text, dag)

        # best-guess's own picks, untouched
        assert best_guess["大风"]["source"] == "dag"
        assert best_guess["快速"]["source"] == "dag"
        assert best_guess["转动"]["source"] == "dag"
        # 风车 was never part of best-guess's chosen route...
        assert "风车" not in best_guess
        # ...but full segmentation isn't blind to a position best-guess's
        # route happened to skip over - it's a real trie hit either way.
        assert "风车" in full
        assert full["风车"]["positions"] == [(1, 3)]


class TestStopwordsInDag:
    """
    Stopwords now reach the DAG itself (build_dag), not just the two
    supplementary passes - covers the direct fix for a stopword character
    (e.g. an opening quotation mark) fusing onto an adjacent word.
    """

    def test_stopword_character_blocks_a_word_from_starting_there(self):
        freq = {"小猪": 900}
        trie = Trie()
        trie.insert("小猪")
        segmenter = Segmenter(trie=trie, freq_dict=freq)

        # "「" immediately precedes "小猪" - without stopword-awareness in
        # build_dag, nothing would actually glue them (「 isn't a trie
        # prefix), but the dag must still never offer 「 as part of any
        # multi-character candidate, and segment() must drop it entirely.
        result = segmenter.segment("「小猪", stopwords={"「"})
        assert words(result) == ["小猪"]

    def test_stopword_character_blocks_a_word_from_extending_through_it(self):
        # A word that WOULD span across a stopword character if the DAG
        # walk ignored it - the direct "gluing" case. 小猪「大 isn't a real
        # word, so use a synthetic trie word that spans exactly where the
        # stopword sits, to prove the walk actually stops there rather than
        # continuing through by coincidence.
        freq = {"小猪大": 900, "小猪": 800}
        trie = Trie()
        trie.insert("小猪大")
        trie.insert("小猪")
        segmenter = Segmenter(trie=trie, freq_dict=freq)

        result = segmenter.segment("小猪「大", stopwords={"「"})
        # "小猪大" must never be offered as a candidate - the walk from
        # position 0 has to stop before consuming "「". "「" itself is
        # dropped entirely (see the next test class), leaving "小猪" and
        # the lone trailing "大" (never itself a dictionary word here).
        assert words(result) == ["小猪", "大"]

    def test_stopword_never_appears_as_its_own_row(self):
        freq = {"你好": 900}
        trie = Trie()
        trie.insert("你好")
        segmenter = Segmenter(trie=trie, freq_dict=freq)

        result = segmenter.segment("你好，", stopwords={"，"})
        assert words(result) == ["你好"]

        agg = aggregate_segments(result)
        assert "，" not in agg

    def test_stopword_never_appears_in_full_segmentation_either(self):
        freq = {"你好": 900}
        trie = Trie()
        trie.insert("你好")
        segmenter = Segmenter(trie=trie, freq_dict=freq)

        text = "你好，"
        dag = segmenter.build_dag(text, overlay=None, stopwords={"，"})
        full = aggregate_full_segmentation(text, dag, stopwords={"，"})
        assert "，" not in full

    def test_stopword_still_gets_a_route_so_the_dp_never_breaks(self):
        # Even though it's dropped from the final output, position i must
        # still get a real (if unused) DAG edge, or the DP route table
        # would have a gap.
        freq = {"你好": 900}
        trie = Trie()
        trie.insert("你好")
        segmenter = Segmenter(trie=trie, freq_dict=freq)
        dag = segmenter.build_dag("你好，", overlay=None, stopwords={"，"})
        assert dag[2] == [(2, False)]
