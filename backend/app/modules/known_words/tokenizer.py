from app.modules.known_words.trie import Trie


def add_or_increment(token_dict: dict, token: str) -> None:
    if token in token_dict:
        token_dict[token]["count"] += 1
    else:
        token_dict[token] = {"count": 1}


def tokenize(
    text: str,
    stopwords: set[str],
    trie: Trie,
    overlay_trie: Trie | None = None,
    min_length: int = 2,
    max_length: int = 20,
    min_count: int = 1,
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
    of already being a full-segmentation candidate. No other change to this
    algorithm - the sliding-window/repeat-count/containment-pruning logic
    is exactly what it was before.
    """
    token_dict = {}

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
            add_or_increment(token_dict, token)

    # Prune tokens
    new_token_dict = {}
    for key1, val1 in token_dict.items():
        # Skip if below min count, too short, or already in dictionary
        if val1["count"] < min_count or len(key1) < min_length:
            continue

        # Skip if it's a dictionary word
        node = trie.root
        is_dict_word = True
        for char in key1:
            if char not in node.children:
                is_dict_word = False
                break
            node = node.children[char]
        if is_dict_word and node.is_word:
            continue

        # Skip if it's a user-overlay word - same walk, second trie. A
        # user word is always trie-resident now regardless of affects_dag
        # (see UserOverlay.add_word, dag_segmentor.py), so this is what
        # keeps it from being double-counted here on top of already being
        # a full-segmentation candidate.
        if overlay_trie is not None:
            onode = overlay_trie.root
            is_overlay_word = True
            for char in key1:
                if char not in onode.children:
                    is_overlay_word = False
                    break
                onode = onode.children[char]
            if is_overlay_word and onode.is_word:
                continue

        # Skip if completely contained within a longer token with same or higher count
        keep = True
        for key2, val2 in token_dict.items():
            if (
                len(key2) > len(key1)
                and key1 in key2
                and val2["count"] >= val1["count"]
            ):
                keep = False
                break

        if keep:
            new_token_dict[key1] = {"count": val1["count"], "source": "token"}

    return new_token_dict