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
    Covers the persistence bug: familiar words (and, later, garbage words)
    used to be excluded here, before persistence, which meant a word marked
    known/familiar or garbage could never be found again even by
    widening/toggling the display filter to "show all" - the AnalysisResult
    row simply didn't exist. filter_results must now persist every word
    regardless of familiarity or garbage status, annotating both instead -
    the analysis results are meant to be a faithful representation of the
    full contents of the analyzed text.
    """

    def test_familiar_words_are_not_excluded(self):
        # "猪" is marked familiarity 5 ("mastered") - the exact scenario from
        # the bug report: this must still come back, not be silently dropped.
        known_words = {"猪": 5}
        filtered = filter_results(SAMPLE_RESULTS, known_words, garbage_words=set())

        assert "猪" in filtered
        assert filtered["猪"]["familiarity"] == 5
        assert filtered["猪"]["count"] == 25

    def test_garbage_words_are_annotated_but_not_excluded(self):
        # Garbage words are flagged, not excluded - display-time filtering
        # only (mirrors familiarity), same as every other word.
        filtered = filter_results(SAMPLE_RESULTS, known_words={}, garbage_words={"，"})
        assert "，" in filtered
        assert filtered["，"]["is_garbage"] is True
        assert filtered["森林"]["is_garbage"] is False
        assert filtered["猪"]["is_garbage"] is False

    def test_familiarity_is_attached_but_never_excludes(self):
        known_words = {"森林": 1, "猪": 5}
        filtered = filter_results(SAMPLE_RESULTS, known_words, garbage_words=set())

        assert len(filtered) == len(SAMPLE_RESULTS)
        assert filtered["森林"]["familiarity"] == 1
        assert filtered["猪"]["familiarity"] == 5
        assert filtered["，"]["familiarity"] is None
