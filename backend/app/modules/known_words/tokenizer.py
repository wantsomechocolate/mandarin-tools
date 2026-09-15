from app.modules.known_words.trie import Trie


def _is_trie_word(trie: Trie, token: str) -> bool:
    node = trie.root
    for char in token:
        if char not in node.children:
            return False
        node = node.children[char]
    return node.is_word


def _dictionary_word_spans(
    text: str,
    stopwords: set[str],
    trie: Trie,
    overlay_trie: Trie | None,
    max_length: int,
) -> list[tuple[int, int]]:
    """
    Every (start, end) span in `text` covered by a real dictionary/overlay
    word, at every starting position - not just spans that also happen to
    be repeated-sequence candidates. Same walk shape as _is_trie_word, just
    run from every position instead of checking one fixed string, and
    recording a hit at every length where `is_word` is true along the way
    (a word can be a prefix of a longer word - both spans are real).
    """
    spans: list[tuple[int, int]] = []
    n = len(text)
    for left in range(n):
        node = trie.root
        for k in range(max_length):
            pos = left + k
            if pos >= n or text[pos] in stopwords or text[pos] not in node.children:
                break
            node = node.children[text[pos]]
            if node.is_word:
                spans.append((left, pos + 1))

        if overlay_trie is not None:
            onode = overlay_trie.root
            for k in range(max_length):
                pos = left + k
                if pos >= n or text[pos] in stopwords or text[pos] not in onode.children:
                    break
                onode = onode.children[text[pos]]
                if onode.is_word:
                    spans.append((left, pos + 1))

    return spans


def tokenize(
    text: str,
    stopwords: set[str],
    trie: Trie,
    overlay_trie: Trie | None = None,
    min_length: int = 2,
    max_length: int = 100,
    min_count: int = 2,
    junk_chars: set[str] | None = None,
) -> dict[str, dict]:
    """
    Finds repeated unknown sequences in text that don't appear in the dictionary.

    Returns a dict of {token: {"count": int, "source": str}}

    `overlay_trie` (the user's UserOverlay.trie, if any - see
    dag_segmentor.py) is checked alongside the global trie when deciding
    whether a candidate is "already a dictionary word" and should be
    skipped: a user word is now always trie-resident regardless of its
    affects_dag setting (see UserOverlay.add_word), so without this check a
    user word would get double-counted here as a "repeated sequence" on top
    of already being a full-segmentation candidate.

    Containment: an occurrence of a shorter candidate that falls entirely
    inside an occurrence of a longer, *accepted* candidate doesn't count
    toward the shorter one's tally - a candidate is "accepted" once its own
    (already-deduped) occurrence count clears min_count. E.g. given
    "我是一个苹果，你是一个西瓜。我有一个桃子。", 是一个 occurs twice and
    clears min_count=2 first (nothing longer contains it), so both of its
    occurrences are claimed; 一个 occurs 3 times raw, but 2 of those sit
    inside a claimed 是一个 occurrence, leaving only 1 unclaimed occurrence
    - below min_count, so 一个 is dropped. This replaces the old "drop a
    token if some longer token containing it has count >= its own count"
    heuristic, which compared whole-dictionary counts rather than actual
    per-occurrence overlap and so couldn't handle a token that's only
    *partially* subsumed by a longer repeat.

    Dictionary/overlay words claim spans too, unconditionally (no min_count
    gate - a known word doesn't need to repeat to be real), even though
    they never appear in the result themselves (see the dictionary-word
    skip below). Without this, a real word like 小红帽 - itself filtered
    out of `candidates` for being a dictionary word - would never get a
    chance to suppress fragments of itself: 小红 and 红帽 would each look
    like their own independent repeated sequence instead of pieces of one,
    and worse, some *other* unrelated repeated phrase that happens to also
    contain 小红帽 could end up claiming a subset of their occurrences on
    小红帽's behalf, producing a partial, misleading count instead of
    excluding them outright. _dictionary_word_spans finds every such span
    up front (every position, not just ones that also happen to be
    repeated-sequence candidates) and seeds claimed_spans with them before
    the loop below runs, so the exact same per-occurrence "is this instance
    already claimed" check handles both dictionary words and accepted
    candidates uniformly.

    `junk_chars` (typically the caller's DAG stopword set - punctuation/
    whitespace, NOT the same as `stopwords` above, which only governs where
    the scan can never cross at all) excludes any candidate whose first or
    last character is one of these - a match is free to move *through*
    junk in the middle (that's the whole point of `stopwords` here being
    so much narrower than the DAG's), but shouldn't start or end on it.
    This is a plain exclusion, not a trim-then-reinsert step, and
    deliberately so: since every window up to max_length starting at every
    position is already scanned, a junk-framed window's properly-trimmed
    core (e.g. "怎么这样大呀" out of "怎么这样大呀？“") is *always* already
    present in `occurrences` as its own independent candidate, starting
    right after the leading junk run - excluding the junk-edged window
    just stops it from shadowing that already-present core. This also
    means occurrences of the same core framed by *different* junk each
    time (e.g. one instance followed by "？“", another by just "！")
    still merge into one shared count for free, and the dictionary/
    overlay-word check below still runs on the real (already-clean)
    content instead of being fooled by trailing punctuation. `None` skips
    this filter entirely (existing callers that don't pass it are
    unaffected).
    """
    occurrences: dict[str, list[int]] = {}

    for left in range(len(text)):
        for k in range(max_length):
            right = k + 1
            pos = left + k
            if pos >= len(text):
                break
            cur_char = text[pos]
            if cur_char in stopwords:
                break
            token = text[left:left + right]
            occurrences.setdefault(token, []).append(left)

    # Candidates: long enough, not junk-edged, not a dictionary/overlay
    # word. Filtered up front since these can never appear in the result
    # and shouldn't participate in containment either way.
    candidates: dict[str, list[int]] = {}
    for token, starts in occurrences.items():
        if len(token) < min_length:
            continue
        if junk_chars is not None and (token[0] in junk_chars or token[-1] in junk_chars):
            continue
        if _is_trie_word(trie, token):
            continue
        if overlay_trie is not None and _is_trie_word(overlay_trie, token):
            continue
        candidates[token] = starts

    # Claim occurrence spans longest-to-shortest: a candidate only counts
    # an occurrence that isn't already covered by a longer, accepted
    # candidate's span, and only claims its own spans (blocking shorter
    # candidates in turn) once it clears min_count itself. Seeded with
    # every dictionary/overlay word's own spans (unconditional, no
    # min_count gate) so a fragment of a real word is suppressed the same
    # way a fragment of an accepted longer candidate already was.
    claimed_spans: list[tuple[int, int]] = _dictionary_word_spans(text, stopwords, trie, overlay_trie, max_length)
    result: dict[str, dict] = {}

    for token in sorted(candidates, key=len, reverse=True):
        starts = candidates[token]
        end_offset = len(token)
        effective_count = sum(
            1 for s in starts
            if not any(cs <= s and s + end_offset <= ce for cs, ce in claimed_spans)
        )
        if effective_count < min_count:
            continue
        result[token] = {"count": effective_count, "source": "token"}
        claimed_spans.extend((s, s + end_offset) for s in starts)

    return result