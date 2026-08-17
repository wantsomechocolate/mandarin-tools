class TrieNode:
    __slots__ = ("children", "is_word")

    def __init__(self):
        self.children: dict[str, "TrieNode"] = {}
        self.is_word: bool = False


class Trie:
    def __init__(self):
        self.root = TrieNode()

    def insert(self, word: str) -> None:
        node = self.root
        for char in word:
            if char not in node.children:
                node.children[char] = TrieNode()
            node = node.children[char]
        node.is_word = True

    def has_children(self, node: TrieNode, char: str) -> bool:
        return char in node.children

    def get_child(self, node: TrieNode, char: str) -> TrieNode | None:
        return node.children.get(char)


def build_trie(words: list[str]) -> Trie:
    trie = Trie()
    for word in words:
        trie.insert(word)
    return trie