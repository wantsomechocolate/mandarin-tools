"""
Standalone tests for app.modules.known_words.tokenizer - no Postgres
connection required. Run with:

    uv run pytest tests/known_words/test_tokenizer.py -v
"""

from app.modules.known_words.trie import Trie
from app.modules.known_words.tokenizer import tokenize


class TestOverlayAwareDictionaryCheck:
    """
    A user word is now always trie-resident regardless of its affects_dag
    setting (see UserOverlay.add_word, dag_segmentor.py), so tokenize()
    must check the overlay trie too when deciding whether a repeated
    sequence is "already a dictionary word" - otherwise a user word would
    get double-counted here as a "repeated sequence" on top of already
    being a full-segmentation candidate.
    """

    def test_overlay_word_is_excluded_like_a_global_dictionary_word(self):
        trie = Trie()  # empty global dictionary - nothing pre-existing
        overlay_trie = Trie()
        overlay_trie.insert("张三")

        # Repeated 3+ times so it would otherwise clear the tokenizer's own
        # min_count bar and be reported as a "repeated sequence".
        text = "张三来了张三走了张三又来了"
        result = tokenize(text, stopwords=set(), trie=trie, overlay_trie=overlay_trie, min_count=2)

        assert "张三" not in result

    def test_repeated_sequence_not_in_either_trie_is_still_found(self):
        trie = Trie()
        overlay_trie = Trie()
        overlay_trie.insert("张三")  # unrelated word, shouldn't affect this

        text = "李四来了李四走了李四又来了"
        result = tokenize(text, stopwords=set(), trie=trie, overlay_trie=overlay_trie, min_count=2)

        assert "李四" in result
        assert result["李四"]["source"] == "token"

    def test_overlay_trie_none_behaves_like_no_overlay(self):
        trie = Trie()
        text = "李四来了李四走了李四又来了"

        with_none = tokenize(text, stopwords=set(), trie=trie, overlay_trie=None, min_count=2)
        without_arg = tokenize(text, stopwords=set(), trie=trie, min_count=2)

        assert with_none == without_arg
