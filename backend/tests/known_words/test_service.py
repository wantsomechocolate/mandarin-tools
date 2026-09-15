"""
Standalone tests for app.modules.known_words.service - pure-function pieces
that don't need a Postgres connection. Run with:

    uv run pytest tests/known_words/test_service.py -v
"""

from app.modules.known_words.service import filter_results, _promote_confirmed_unknown_runs


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


class TestPromoteConfirmedUnknownRuns:
    """
    A merged "unknown" run (Segmenter._merge_unknown_runs, dag_segmentor.py)
    that the tokenizer also independently confirms as a repeated sequence
    gets relabeled in place - see _promote_confirmed_unknown_runs' own
    docstring.
    """

    def test_unknown_run_confirmed_by_tokenizer_is_relabeled(self):
        best_guess = {
            "smart": {"count": 3, "source": "unknown", "positions": [(0, 5), (10, 15), (20, 25)]},
        }
        repeated = {"smart": {"count": 3, "source": "token"}}

        _promote_confirmed_unknown_runs(best_guess, repeated)

        assert best_guess["smart"]["source"] == "repeated_sequence"
        # count/positions stay best_guess's own (from the DAG walk) -
        # nothing copied over from the tokenizer's own entry.
        assert best_guess["smart"]["count"] == 3
        assert best_guess["smart"]["positions"] == [(0, 5), (10, 15), (20, 25)]

    def test_unknown_run_not_confirmed_stays_unknown(self):
        best_guess = {"xkq": {"count": 1, "source": "unknown", "positions": [(0, 3)]}}
        repeated: dict = {}

        _promote_confirmed_unknown_runs(best_guess, repeated)

        assert best_guess["xkq"]["source"] == "unknown"

    def test_dictionary_backed_word_never_relabeled_even_if_string_collides(self):
        # Guards against accidentally promoting a real dag/overlay word just
        # because the same string also happens to show up in `repeated` -
        # promotion only ever applies to source == "unknown".
        best_guess = {"你好": {"count": 5, "source": "dag", "positions": [(0, 2)]}}
        repeated = {"你好": {"count": 5, "source": "token"}}

        _promote_confirmed_unknown_runs(best_guess, repeated)

        assert best_guess["你好"]["source"] == "dag"
