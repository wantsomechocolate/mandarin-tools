"""
Standalone tests for app.modules.known_words.service - pure-function pieces
that don't need a Postgres connection. Run with:

    uv run pytest tests/known_words/test_service.py -v
"""

from app.modules.known_words.service import filter_results


SAMPLE_RESULTS = {
    "森林": {"count": 5, "source": "dag"},
    "猪": {"count": 25, "source": "dag"},
    "，": {"count": 45, "source": "unknown"},
}


class TestFilterResults:
    """
    Covers the persistence bug: familiar words used to be excluded here,
    before persistence, which meant a word marked known/familiar could never
    be found again even by widening the display filter to "show all" -
    the AnalysisResult row simply didn't exist. filter_results must now
    persist every non-garbage word regardless of familiarity.
    """

    def test_familiar_words_are_not_excluded(self):
        # "猪" is marked familiarity 5 ("mastered") - the exact scenario from
        # the bug report: this must still come back, not be silently dropped.
        known_words = {"猪": 5}
        filtered = filter_results(SAMPLE_RESULTS, known_words, garbage_words=set())

        assert "猪" in filtered
        assert filtered["猪"]["familiarity"] == 5
        assert filtered["猪"]["count"] == 25

    def test_garbage_words_are_still_excluded(self):
        # Garbage exclusion is deliberately still one-way/pre-persistence.
        filtered = filter_results(SAMPLE_RESULTS, known_words={}, garbage_words={"，"})
        assert "，" not in filtered
        assert "森林" in filtered
        assert "猪" in filtered

    def test_familiarity_is_attached_but_never_excludes(self):
        known_words = {"森林": 1, "猪": 5}
        filtered = filter_results(SAMPLE_RESULTS, known_words, garbage_words=set())

        assert len(filtered) == len(SAMPLE_RESULTS)
        assert filtered["森林"]["familiarity"] == 1
        assert filtered["猪"]["familiarity"] == 5
        assert filtered["，"]["familiarity"] is None
