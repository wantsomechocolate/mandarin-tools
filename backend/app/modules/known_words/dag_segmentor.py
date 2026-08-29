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


# Common bound suffix characters: locative/directional morphemes that attach
# to almost any noun/stem to form a compositional (not lexicalized) span -
# e.g. <place>+里 ("in the forest" -> 森林里) rather than a fixed vocabulary
# word. Because these characters are individually extremely frequent, a rare
# compound entry can still statistically out-score splitting into stem+affix:
# "AB as one word" beats "A + B" in the DP exactly when
# freq(AB) > freq(A)*freq(B)/total, and that bar is very low when one half of
# the pair (里/中/上/...) is this common - real numbers: freq(森林)=627,741,
# freq(里)=19,397,088, total≈19.78B gives a chance-level threshold of only
# ~616, so 森林里's real frequency of 13,177 (21x chance) is still enough to
# win despite being a rare, compositional string, not a word worth studying.
#
# Discounting these compounds' scores pushes the DP back toward preferring
# the split, unless the compound's own frequency clears a much higher bar -
# genuinely lexicalized words ending the same way (这里/那里/家里/早上/晚上)
# have frequencies orders of magnitude above the rare compositional case
# these defaults are calibrated against, so they stay merged.
#
# 里 is calibrated directly against the numbers above (0.03 flips 森林里 to
# split while leaving 这里/那里/家里 a healthy margin). The rest default to a
# milder 0.05 - starting points without per-character calibration data yet,
# meant to be tuned via the segmentation_affixes table as real cases surface.
DEFAULT_SUFFIX_DISCOUNTS: dict[str, float] = {
    "里": 0.03,
    "中": 0.05,
    "上": 0.05,
    "下": 0.05,
    "内": 0.05,
    "外": 0.05,
    "边": 0.05,
    "面": 0.05,
    "间": 0.05,
    "处": 0.05,
}

# Chinese bound prefixes are rarer and less uniformly "generic" than the
# locative suffixes above, so no seed list without a concrete case to
# calibrate against - add rows to segmentation_affixes(position='prefix')
# as they come up.
DEFAULT_PREFIX_DISCOUNTS: dict[str, float] = {}


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

    def __init__(
        self,
        trie: Trie,
        freq_dict: dict[str, int],
        suffix_discounts: dict[str, float] | None = None,
        prefix_discounts: dict[str, float] | None = None,
        exemptions: set[str] | None = None,
    ):
        if not freq_dict:
            raise ValueError("freq_dict must not be empty")
        self.trie = trie
        self.freq = freq_dict
        self.total = sum(freq_dict.values())
        self.log_total = math.log(self.total)
        self.max_freq = max(freq_dict.values())

        # Sorted longest-affix-first so a more specific rule (if two affixes
        # both matched, e.g. a future multi-character suffix) wins over a
        # shorter/more general one.
        self._suffixes = sorted((suffix_discounts or {}).items(), key=lambda kv: -len(kv[0]))
        self._prefixes = sorted((prefix_discounts or {}).items(), key=lambda kv: -len(kv[0]))
        self._exemptions = exemptions or set()

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

    def _affix_discount(self, word: str) -> float:
        """
        Multiplicative discount applied to a word's frequency before scoring,
        for compounds ending/starting with a configured affix character (see
        DEFAULT_SUFFIX_DISCOUNTS docstring for why). `len(word) > len(affix)`
        is required so a bare affix character chosen as its own single-char
        word (e.g. 里 on its own) is never discounted - only compounds are.
        """
        if word in self._exemptions:
            return 1.0
        for suffix, discount in self._suffixes:
            if len(word) > len(suffix) and word.endswith(suffix):
                return discount
        for prefix, discount in self._prefixes:
            if len(word) > len(prefix) and word.startswith(prefix):
                return discount
        return 1.0

    def _word_weight(self, word: str, from_overlay: bool, overlay: UserOverlay | None) -> float:
        if from_overlay and overlay is not None and word in overlay.freq:
            return math.log(overlay.freq[word]) - self.log_total
        freq = self.freq.get(word)
        if freq is None:
            # Not in either dictionary - floor score, DP can still route
            # through it but heavily disfavors it vs any real word.
            return -self.log_total
        discount = self._affix_discount(word)
        return math.log(freq * discount) - self.log_total

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
