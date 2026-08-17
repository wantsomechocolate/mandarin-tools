from app.modules.known_words.trie import Trie


def add_or_increment(output: dict, word: str, source: str) -> None:
    if word in output:
        output[word]["count"] += 1
    else:
        output[word] = {"count": 1, "source": source}


def longest_matching(
    text: str,
    trie: Trie,
    stopwords: set[str],
) -> dict[str, dict]:
    output = {}
    i = 0
    unknown = ""
    right_max = 0

    while i < len(text):
        cur_char = text[i]

        if cur_char in stopwords:
            if unknown:
                add_or_increment(output, unknown, "unknown")
                unknown = ""
            i += 1
            continue

        parent_node = trie.root
        cur_string = ""
        longest_word = ""
        j = 0

        while True:
            pos = i + j
            if pos >= len(text):
                break
            cur_char = text[pos]
            if cur_char not in parent_node.children:
                break
            cur_string += cur_char
            parent_node = parent_node.children[cur_char]
            if parent_node.is_word:
                longest_word = cur_string
            j += 1

        if longest_word == "":
            if i + 1 > right_max:
                unknown += text[i]
                right_max = i + 1
        else:
            if unknown:
                add_or_increment(output, unknown, "unknown")
                unknown = ""
            if i + len(longest_word) > right_max:
                add_or_increment(output, longest_word, "trie")
                right_max = i + len(longest_word)

        i += 1

    if unknown:
        add_or_increment(output, unknown, "unknown")

    return output