"""
DAG + dynamic-programming segmenter (jieba-style "accurate mode", minus the
HMM new-word layer — see project notes for why that's intentionally skipped).

Unlike segmentor.py's longest_matching, this considers *every* dictionary-backed
segmentation of a sentence and picks the one with the highest total word
frequency via right-to-left dynamic programming, rather than greedily taking
the longest match at each position. This fixes cases where the longest match
at a given position isn't actually part of the best overall segmentation
(classic example: 研究生命起源 -> 研究/生命/起源, not 研究生/命/起源).

Unknown spans (no dictionary path at all) fall back to single characters here,
on the assumption that the existing tokenizer.py pass downstream is a better
tool for surfacing genuinely unknown multi-character sequences than trying to
guess word boundaries for them.
"""

import math
from dataclasses import dataclass

from app.modules.known_words.trie import Trie


@dataclass
class SegmentResult:
    word: str
    start: int
    end: int  # exclusive
    in_dictionary: bool
    from_overlay: bool = False


class UserOverlay:
    """
    Small per-user trie + frequency table. Built fresh per request (see
    frequency_loader.build_user_overlay) from that user's UserWord rows.
    Never mutates the shared global Segmenter/trie.
    """

    def __init__(self):
        self.trie = Trie()
        self.freq: dict[str, int] = {}

    def add_word(self, word: str, freq: int | None, dominance_floor: int) -> None:
        self.trie.insert(word)
        self.freq[word] = freq if freq is not None else dominance_floor


class Segmenter:
    """
    Wraps the shared global Trie + word-frequency table. Built once at
    startup (see frequency_loader.get_segmenter) and never mutated per
    request — per-user custom words are passed in as a UserOverlay instead.
    """

    def __init__(self, trie: Trie, freq_dict: dict[str, int]):
        if not freq_dict:
            raise ValueError("freq_dict must not be empty")
        self.trie = trie
        self.freq = freq_dict
        self.total = sum(freq_dict.values())
        self.log_total = math.log(self.total)
        self.max_freq = max(freq_dict.values())

    def dominance_floor(self) -> int:
        """A frequency guaranteed to outrank anything in the global table,
        for user words added without an explicit frequency."""
        return self.max_freq * 2

    def _build_dag(
        self, text: str, overlay: UserOverlay | None
    ) -> dict[int, list[tuple[int, bool]]]:
        """
        For each start position, every (end_index_inclusive, from_overlay)
        reachable via a dictionary word in either trie. Falls back to a
        single unknown character when nothing matches, so every position
        always has at least one outgoing edge.
        """
        n = len(text)
        dag: dict[int, list[tuple[int, bool]]] = {}
        for i in range(n):
            candidates: list[tuple[int, bool]] = []

            node, j = self.trie.root, i
            while j < n and text[j] in node.children:
                node = node.children[text[j]]
                if node.is_word:
                    candidates.append((j, False))
                j += 1

            if overlay is not None:
                onode, oj = overlay.trie.root, i
                while oj < n and text[oj] in onode.children:
                    onode = onode.children[text[oj]]
                    if onode.is_word:
                        candidates.append((oj, True))
                    oj += 1

            if not candidates:
                candidates = [(i, False)]
            dag[i] = candidates
        return dag

    def _word_weight(self, word: str, from_overlay: bool, overlay: UserOverlay | None) -> float:
        if from_overlay and overlay is not None and word in overlay.freq:
            return math.log(overlay.freq[word]) - self.log_total
        freq = self.freq.get(word)
        if freq is None:
            # Not in either dictionary - floor score, DP can still route
            # through it but heavily disfavors it vs any real word.
            return -self.log_total
        return math.log(freq) - self.log_total

    def _dp(
        self, text: str, dag: dict[int, list[tuple[int, bool]]], overlay: UserOverlay | None
    ) -> dict[int, tuple[float, int, bool]]:
        n = len(text)
        route: dict[int, tuple[float, int, bool]] = {n: (0.0, n, False)}
        for idx in range(n - 1, -1, -1):
            best = None
            for end, from_overlay in dag[idx]:
                word = text[idx:end + 1]
                score = self._word_weight(word, from_overlay, overlay) + route[end + 1][0]
                if best is None or score > best[0]:
                    best = (score, end + 1, from_overlay)
            route[idx] = best
        return route

    def segment(self, text: str, overlay: UserOverlay | None = None) -> list[SegmentResult]:
        if not text:
            return []
        dag = self._build_dag(text, overlay)
        route = self._dp(text, dag, overlay)
        results: list[SegmentResult] = []
        idx, n = 0, len(text)
        while idx < n:
            _, next_idx, from_overlay = route[idx]
            word = text[idx:next_idx]
            results.append(SegmentResult(
                word=word,
                start=idx,
                end=next_idx,
                in_dictionary=(word in self.freq) or (overlay is not None and word in overlay.freq),
                from_overlay=from_overlay,
            ))
            idx = next_idx
        return results


def aggregate_segments(results: list[SegmentResult]) -> dict[str, dict]:
    """
    Collapses an ordered segment list into {word: {"count", "source"}},
    matching the shape segmentor.longest_matching/tokenizer.tokenize already
    return, so results are comparable/mergeable with the existing pipeline.
    """
    output: dict[str, dict] = {}
    for r in results:
        if not r.in_dictionary:
            source = "unknown"
        elif r.from_overlay:
            source = "overlay"
        else:
            source = "dag"
        if r.word in output:
            output[r.word]["count"] += 1
        else:
            output[r.word] = {"count": 1, "source": source}
    return output
