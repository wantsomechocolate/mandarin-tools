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

        # Distinct surrounding characters at each occurrence, so no longer
        # substring containing 李四 also repeats and claims its spans -
        # keeps this test about overlay-awareness only, not containment.
        text = "甲李四乙丙李四丁戊李四己"
        result = tokenize(text, stopwords=set(), trie=trie, overlay_trie=overlay_trie, min_count=2)

        assert "李四" in result
        assert result["李四"]["source"] == "token"

    def test_overlay_trie_none_behaves_like_no_overlay(self):
        trie = Trie()
        text = "甲李四乙丙李四丁戊李四己"

        with_none = tokenize(text, stopwords=set(), trie=trie, overlay_trie=None, min_count=2)
        without_arg = tokenize(text, stopwords=set(), trie=trie, min_count=2)

        assert with_none == without_arg


class TestNestedContainment:
    """
    An occurrence of a shorter candidate that falls entirely inside an
    occurrence of a longer, accepted candidate shouldn't count toward the
    shorter one's tally - see tokenize()'s own docstring for the exact
    rule (longest-to-shortest span claiming).
    """

    def test_shorter_sequence_fully_subsumed_by_longer_one_is_dropped(self):
        # 是一个 occurs twice (我是一个苹果 / 你是一个西瓜) - claims both
        # occurrences. 一个 occurs 3 times raw, but 2 of those are the same
        # spans 是一个 already claimed, leaving only 1 unclaimed occurrence
        # (我有一个桃子) - below min_count=2, so 一个 should not appear.
        trie = Trie()
        text = "我是一个苹果你是一个西瓜我有一个桃子"
        result = tokenize(text, stopwords=set(), trie=trie, min_count=2)

        assert "是一个" in result
        assert result["是一个"]["count"] == 2
        assert "一个" not in result

    def test_partially_overlapping_sequence_keeps_its_unclaimed_occurrences(self):
        # Same as above, plus "我有一个桃子" (一个's 3rd occurrence, not
        # claimed by anything - 有一个 itself only occurs once here, so it
        # never becomes an accepted candidate) and "他吃一个梨" (a 4th,
        # likewise unclaimed occurrence) - two unclaimed occurrences clear
        # min_count=2 on their own.
        trie = Trie()
        text = "我是一个苹果你是一个西瓜我有一个桃子他吃一个梨"
        result = tokenize(text, stopwords=set(), trie=trie, min_count=2)

        assert "是一个" in result
        assert result["是一个"]["count"] == 2
        assert "一个" in result
        assert result["一个"]["count"] == 2

    def test_unrelated_repeats_of_different_lengths_are_unaffected(self):
        # No nesting relationship between these two (distinct surrounding
        # characters at each occurrence, so no longer substring spanning
        # either one also repeats), so both should be reported at their
        # full raw counts.
        trie = Trie()
        text = "李四来了李四走了甲张三乙丙张三丁"
        result = tokenize(text, stopwords=set(), trie=trie, min_count=2)

        assert result["李四"]["count"] == 2
        assert result["张三"]["count"] == 2


class TestJunkEdgeExclusion:
    """
    `junk_chars` excludes any candidate starting or ending on one of these
    characters - see tokenize()'s own docstring for why this is a plain
    exclusion (not a trim-then-reinsert step): the properly-trimmed core is
    always already present in the scan as its own independent candidate,
    starting right after any leading junk run.
    """

    JUNK = {"。", "“", "”", "？", "！", "，"}

    def test_junk_edged_match_is_dropped_when_its_core_is_too_short(self):
        # "来。“" occurs twice, but is junk-edged (trailing "。“") so it's
        # excluded outright; its trimmed core "来" is generated on its own
        # too, but at length 1 it never clears min_length=2 either - so
        # nothing survives for this repeat at all, matching the "来。“"
        # example (dropped, not just re-labeled).
        trie = Trie()
        text = "来。“工作来。“休息"
        result = tokenize(text, stopwords=set(), trie=trie, min_count=2, junk_chars=self.JUNK)

        assert "来。“" not in result
        assert "来" not in result

    def test_junk_edged_match_survives_as_its_trimmed_core(self):
        # "怎么这样大呀" (6 chars) occurs twice, once followed by "？“" and
        # once by a different trailing junk ("！") - the junk-inclusive
        # windows never become candidates, but the shared 6-char core is
        # independently found at both occurrences and survives with the
        # combined count, exactly like the "怎么这样大呀？“" example.
        trie = Trie()
        text = "怎么这样大呀？“他说怎么这样大呀！你猜"
        result = tokenize(text, stopwords=set(), trie=trie, min_count=2, junk_chars=self.JUNK)

        assert "怎么这样大呀" in result
        assert result["怎么这样大呀"]["count"] == 2
        assert "怎么这样大呀？“" not in result
        assert "怎么这样大呀！" not in result

    def test_internal_junk_is_preserved_not_stripped(self):
        # The comma sits strictly inside this repeated sequence, never at
        # an edge - only edge-junk gets excluded, so the whole 5-character
        # sequence (comma included) should survive intact.
        trie = Trie()
        text = "你好，谢谢先生你好，谢谢女士"
        result = tokenize(text, stopwords=set(), trie=trie, min_count=2, junk_chars=self.JUNK)

        assert "你好，谢谢" in result
        assert result["你好，谢谢"]["count"] == 2

    def test_junk_chars_none_skips_the_filter_entirely(self):
        # Default behavior (no junk_chars passed) is unchanged from before
        # this feature - a junk-edged match can still appear.
        trie = Trie()
        text = "来。“工作来。“休息"
        result = tokenize(text, stopwords=set(), trie=trie, min_count=2)

        assert "来。“" in result
        assert result["来。“"]["count"] == 2


class TestDictionaryWordSuppressesFragments:
    """
    A dictionary word's own occurrences claim spans too (unconditionally,
    no min_count gate), even though the word itself never appears in the
    result - otherwise a fragment of a real word (e.g. 小红/红帽, pieces of
    小红帽) looks like its own independent repeated sequence instead of
    being recognized as part of one. See tokenize()'s own docstring.
    """

    def test_fragments_of_a_dictionary_word_are_excluded(self):
        trie = Trie()
        trie.insert("小红帽")
        # Distinct character between each occurrence so nothing longer
        # than 小红帽 itself repeats and complicates the picture.
        text = "小红帽甲小红帽乙小红帽丙"
        result = tokenize(text, stopwords=set(), trie=trie, min_count=2)

        assert "小红帽" not in result  # dictionary word itself, as before
        assert "小红" not in result
        assert "红帽" not in result

    def test_fragment_occurring_independently_is_still_counted(self):
        # 红帽 occurs twice as part of 小红帽 (should be excluded there)
        # and twice more on its own, unconnected to 小红帽 - only the
        # independent occurrences should count.
        trie = Trie()
        trie.insert("小红帽")
        text = "小红帽甲小红帽乙丙红帽丁戊红帽己"
        result = tokenize(text, stopwords=set(), trie=trie, min_count=2)

        assert "红帽" in result
        assert result["红帽"]["count"] == 2
        assert "小红" not in result


class TestMaxLengthTruncation:
    """
    A repeated phrase longer than max_length can never be captured as one
    candidate - only its ≤max_length sub-windows can, and since none of
    them is ever the true longest match, containment can't suppress any of
    them either, producing a wall of overlapping fragments instead of one
    clean result (the bug that motivated raising the default to 100 - see
    AnalyzeTextRequest.max_token_length's own comment, schemas.py). These
    tests pin the mechanism itself, independent of whatever the default is.
    """

    CORE = "if you gonna leave me like that"  # 32 characters - past the old cap of 20
    # The true maximal repeat also picks up the space on each side (every
    # occurrence below really does share it - "xyzq " and "abcm " and
    # "pqrn " all end in a space, and "that " is followed by a space before
    # each differing okay/alright/fine) - not a test artifact, a correct
    # reflection of what's actually common to all three occurrences.
    PHRASE = f" {CORE} "

    def _text(self) -> str:
        # Distinct characters immediately before and after each occurrence
        # (not shared words/punctuation) so nothing accidentally extends
        # the true maximal match past PHRASE in either direction - e.g.
        # "he said"/"she said" would share "he said" as a literal substring
        # and silently produce an even longer "real" match.
        return (
            f"xyzq{self.PHRASE}okay "
            f"abcm{self.PHRASE}alright "
            f"pqrn{self.PHRASE}fine"
        )

    def test_capped_at_the_old_default_fragments_instead_of_capturing_the_whole_phrase(self):
        trie = Trie()
        result = tokenize(self._text(), stopwords=set(), trie=trie, min_count=2, max_length=20)

        assert self.PHRASE not in result
        # At least one truncated sub-window of the phrase shows up instead.
        assert any(len(word) <= 20 and word in self.PHRASE for word in result)

    def test_generous_max_length_captures_the_whole_phrase_and_suppresses_fragments(self):
        trie = Trie()
        result = tokenize(self._text(), stopwords=set(), trie=trie, min_count=2, max_length=100)

        assert self.PHRASE in result
        assert result[self.PHRASE]["count"] == 3
        # None of its own sub-windows should survive as separate results -
        # they're all fully contained within the now-captured whole phrase.
        assert not any(word != self.PHRASE and word in self.PHRASE for word in result)
