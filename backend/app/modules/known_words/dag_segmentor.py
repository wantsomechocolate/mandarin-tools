"""
DAG + dynamic-programming segmenter, jieba-style. Produces two views of the
same underlying DAG (see build_dag) - jieba calls these "accurate mode" and
"full mode", and this module keeps both names' spirit without borrowing the
terms verbatim:

- best-guess (aggregate_segments, over Segmenter.segment()'s DP walk): the
  single highest-total-frequency path through the sentence, chosen via
  right-to-left dynamic programming rather than greedily taking the longest
  match at each position. This fixes cases where the longest match at a
  given position isn't actually part of the best overall segmentation
  (classic example: 研究生命起源 -> 研究/生命/起源, not 研究生/命/起源).
- full segmentation (aggregate_full_segmentation, over the same dag dict):
  every dictionary/corpus/user-backed candidate word the DAG's own
  candidate generation found at every position, chosen by the DP or not.
  This is what service.py's "extra matches" are built from - it fully
  replaces what the old segmentor.py's longest_matching was approximating
  (a second, lower-confidence pass over the same text), and does it more
  completely: it includes user-overlay words, real per-occurrence
  positions, and no word-type coarseness, all for free from the same dag
  build the DP walk already needed.

Deliberately still skips jieba's HMM new-word-discovery layer - an
unresolved character sequence is useful signal for this app (something to
flag for the user), not a failure to paper over. The tokenizer.py pass
(a distinct algorithm - sliding-window repeat detection, not a DAG walk)
covers that role instead.

A single character with no dictionary/overlay path at all falls back to its
own one-character DAG edge (see build_dag), so the DP always has somewhere
to route through - this is what produces a best-guess "unknown" row rather
than silently dropping unrecognized content.
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

    def add_word(self, word: str, freq: int | None, dominance_floor: int, affects_dag: bool = True) -> None:
        """
        Always inserts into the trie, so the word is always a real DAG
        candidate (both best-guess and full segmentation) regardless of
        affects_dag - see build_user_overlay's docstring for why floor
        scoring, not exclusion, is what "doesn't affect segmentation" means
        now.

        Only populates self.freq when affects_dag is true - a near-
        guaranteed-win floor (dominance_floor, or the word's own
        freq_combined if it has one) so it reliably wins the DP exactly as
        a boosted word should. When affects_dag is false, self.freq is left
        untouched for this word: Segmenter._word_weight's existing
        `from_overlay and word in overlay.freq` check then falls straight
        through to `self.freq.get(word)` (almost always None for a
        personal-only word), landing on the same low-confidence
        unknown-floor score any no-frequency dictionary word already gets -
        no separate scoring path needed, the word just essentially never
        wins best-guess while still being a real, visible candidate.
        """
        self.trie.insert(word)
        if affects_dag:
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

    def build_dag(
        self, text: str, overlay: UserOverlay | None, stopwords: set[str] | None = None
    ) -> dict[int, list[tuple[int, bool]]]:
        """
        For each start position, every (end_index_inclusive, from_overlay)
        reachable via a dictionary word in either trie. Falls back to a
        single unknown character when nothing matches, so every position
        always has at least one outgoing edge.

        Non-underscored (unlike the old _build_dag) so service.py can call
        it directly and reuse the exact same dag dict for both the DP walk
        (via segment()) and aggregate_full_segmentation - built exactly
        once per analysis, never twice.

        `stopwords` (never baked into the shared, cached Segmenter, passed
        per-call exactly like overlay) is enforced with a single guard on
        each trie walk's next character: `text[j] not in stopwords`. This
        does double duty - a walk starting exactly ON a stopword character
        fails on its very first iteration (j == i), so that position gets
        no real candidates and falls through to the single-character
        fallback below, exactly as if nothing had matched there; a walk
        that reaches a stopword character partway through simply can't
        extend past it either, so no candidate word can ever span across
        one (the direct fix for punctuation gluing onto an adjacent word,
        e.g. a quotation mark fusing onto the word it quotes). Both
        global and overlay tries get the same guard.
        """
        stopwords = stopwords or set()
        n = len(text)
        dag: dict[int, list[tuple[int, bool]]] = {}
        for i in range(n):
            candidates: list[tuple[int, bool]] = []

            node, j = self.trie.root, i
            while j < n and text[j] not in stopwords and text[j] in node.children:
                node = node.children[text[j]]
                if node.is_word:
                    candidates.append((j, False))
                j += 1

            if overlay is not None:
                onode, oj = overlay.trie.root, i
                while oj < n and text[oj] not in stopwords and text[oj] in onode.children:
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

    def segment(
        self,
        text: str,
        overlay: UserOverlay | None = None,
        stopwords: set[str] | None = None,
        dag: dict[int, list[tuple[int, bool]]] | None = None,
    ) -> list[SegmentResult]:
        """
        The DP's own best-guess walk. `dag` lets a caller (service.py) pass
        in a dag it already built via build_dag, so the DP walk and
        aggregate_full_segmentation consume the exact same candidate set
        instead of building it twice - build it internally from
        `text`/`overlay`/`stopwords` when omitted (e.g. every existing
        test/call site that only cares about best-guess).
        """
        if not text:
            return []
        if dag is None:
            dag = self.build_dag(text, overlay, stopwords)
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
                # Trie membership, not frequency membership - self.freq is
                # deliberately restricted to rows with usable frequency
                # (see segmenter_loader._build_segmenter), while the trie is
                # built from every dictionary_words row regardless of
                # frequency. A word backed only by HSK/CC-CEDICT (no
                # frequency row) is a real trie hit and should count as a
                # dictionary word - frequency still drives DP scoring via
                # self.freq exactly as before (_word_weight's floor-score
                # fallback is unchanged), only this classification changes.
                in_dictionary=self.trie.contains(word) or (overlay is not None and overlay.trie.contains(word)),
                from_overlay=from_overlay,
            ))
            idx = next_idx
        # A stopword character always ends up as its own one-character
        # fallback edge (build_dag can't extend a trie walk onto or past
        # one), so without this filter every stopword in the text would
        # otherwise surface as its own "unknown" row here - drop it
        # entirely instead, matching how the tokenizer already silently
        # excludes stopwords rather than surfacing them as clutter.
        if stopwords:
            results = [r for r in results if not (len(r.word) == 1 and r.word in stopwords)]
        return results


def aggregate_segments(results: list[SegmentResult]) -> dict[str, dict]:
    """
    Collapses an ordered best-guess segment list (Segmenter.segment()'s own
    output) into {word: {"count", "source", "positions"}}, matching the
    shape tokenizer.tokenize/aggregate_full_segmentation return (plus
    "positions" - see below), so results are comparable/mergeable with the
    rest of the pipeline (service.analyze_text).

    "positions" is a list of (start, end) pairs, one per occurrence - every
    entry here comes from the DAG's own ordered, non-overlapping walk of the
    text, so exact positions are always available at this point, regardless
    of which source label ends up assigned. This is what makes "positions"
    NOT available for words added only by the tokenizer's repeated-sequence
    pass (see service.analyze_text) - that scans overlapping substrings
    rather than a disjoint segmentation, so it has no single natural span
    per occurrence.
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
            output[r.word]["positions"].append((r.start, r.end))
        else:
            output[r.word] = {"count": 1, "source": source, "positions": [(r.start, r.end)]}
    return output


def aggregate_full_segmentation(
    text: str,
    dag: dict[int, list[tuple[int, bool]]],
    stopwords: set[str] | None = None,
) -> dict[str, dict]:
    """
    Jieba's "full mode" counterpart to aggregate_segments: every candidate
    word the DAG's own candidate generation found at each position, chosen
    by the DP or not - not just the single best-scoring path. This is what
    service.analyze_text's "extra matches" are built from.

    Must consume the SAME dag dict the DP walk used (Segmenter.build_dag,
    called once by the caller) - never rebuilt here, so the two views of
    one analysis can't drift apart.

    Every real entry in dag[i] is a genuine trie/overlay word-boundary hit
    - no separate "is this a dictionary word" check needed here, unlike the
    tokenizer's free-form scan. The one exception is build_dag's own
    single-character fallback (`if not candidates: candidates = [(i,
    False)]`), emitted whenever nothing else matched at position i -
    structurally identical whether that position holds a stopword
    character or a genuinely unrecognized one, so this function can't tell
    those two cases apart by shape alone. The stopword case is filtered
    explicitly here (same rule Segmenter.segment() applies to its own
    output) because that word was already stripped out of best-guess, so
    the caller's "not already in best-guess" dedup wouldn't otherwise catch
    it. A genuinely unrecognized character needs no such handling: nothing
    can span across it either (it has no trie children at all), so it's
    guaranteed to land in best-guess's own "unknown" output wherever it
    occurs, and the caller's dedup against best-guess takes care of it.
    """
    stopwords = stopwords or set()
    output: dict[str, dict] = {}
    for i, candidates in dag.items():
        for end, _from_overlay in candidates:
            word = text[i:end + 1]
            if len(word) == 1 and word in stopwords:
                continue
            if word in output:
                output[word]["count"] += 1
                output[word]["positions"].append((i, end + 1))
            else:
                output[word] = {"count": 1, "positions": [(i, end + 1)]}
    return output
