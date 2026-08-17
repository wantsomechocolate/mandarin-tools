from sqlalchemy.orm import Session
from sqlalchemy import text

from app.modules.known_words.trie_loader import get_trie
from app.modules.known_words.segmentor import longest_matching
from app.modules.known_words.tokenizer import tokenize


DEFAULT_LM_STOPWORDS = {"\n"}

DEFAULT_TOKENIZER_STOPWORDS = {
    "\n", "，", "。", "！", "？", "、", "；", "：",
    """, """, "'", "'", "（", "）", "【", "】",
    "《", "》", "—", "…", "·", "～",
    ",", ".", "!", "?", ";", ":", "(", ")", 
    "[", "]", "-", "/", "\\", "@", "#", "%",
    " ", "\t",
}


def analyze_text(
    text_body: str,
    db: Session,
    min_token_length: int = 2,
    max_token_length: int = 20,
    min_token_count: int = 2,
    lm_stopwords: set[str] | None = None,
    tokenizer_stopwords: set[str] | None = None,
) -> dict[str, dict]:
    """
    Runs both the longest matching segmentation and tokenization algorithms
    on the input text and merges the results.

    Returns a dict of {word: {"count": int, "source": str}}
    """
    trie = get_trie(db)

    lm_sw = lm_stopwords if lm_stopwords is not None else DEFAULT_LM_STOPWORDS
    tok_sw = tokenizer_stopwords if tokenizer_stopwords is not None else DEFAULT_TOKENIZER_STOPWORDS

    # Run longest matching
    lm_results = longest_matching(text_body, trie, lm_sw)

    # Run tokenizer
    token_results = tokenize(
        text_body,
        tok_sw,
        trie,
        min_length=min_token_length,
        max_length=max_token_length,
        min_count=min_token_count,
    )

    # Merge results — longest matching takes priority if same word appears in both
    merged = {**token_results, **lm_results}

    return merged


def get_user_stopwords(user_id: int, db: Session) -> tuple[set[str], set[str]]:
    """
    Returns (lm_stopwords, tokenizer_stopwords) for a user,
    merging system defaults with user additions and applying overrides.
    """
    rows = db.execute(text("""
        SELECT word, algo_type, is_override
        FROM stopwords
        WHERE user_id IS NULL OR user_id = :user_id
    """), {"user_id": user_id}).fetchall()

    lm_stopwords = set(DEFAULT_LM_STOPWORDS)
    tokenizer_stopwords = set(DEFAULT_TOKENIZER_STOPWORDS)

    lm_overrides = set()
    tok_overrides = set()

    for word, algo_type, is_override in rows:
        if is_override:
            if algo_type == "longest_match":
                lm_overrides.add(word)
            else:
                tok_overrides.add(word)
        else:
            if algo_type == "longest_match":
                lm_stopwords.add(word)
            else:
                tokenizer_stopwords.add(word)

    lm_stopwords -= lm_overrides
    tokenizer_stopwords -= tok_overrides

    return lm_stopwords, tokenizer_stopwords


def get_user_garbage_words(user_id: int, db: Session) -> set[str]:
    """
    Returns the set of garbage words for a user,
    merging system defaults with user additions and applying overrides.
    """
    rows = db.execute(text("""
        SELECT word, is_override
        FROM garbage_words
        WHERE user_id IS NULL OR user_id = :user_id
    """), {"user_id": user_id}).fetchall()

    garbage = set()
    overrides = set()

    for word, is_override in rows:
        if is_override:
            overrides.add(word)
        else:
            garbage.add(word)

    garbage -= overrides
    return garbage


def filter_results(
    results: dict[str, dict],
    known_words: dict[str, int],
    garbage_words: set[str],
    min_familiarity: int | None = None,
    max_familiarity: int | None = None,
) -> dict[str, dict]:
    """
    Filters analysis results based on known word familiarity and garbage words.

    known_words is a dict of {word: familiarity_score}
    min/max_familiarity filter out words within that familiarity range.
    Default behavior filters out words with familiarity 4 or 5.
    """
    if min_familiarity is None:
        min_familiarity = 4
    if max_familiarity is None:
        max_familiarity = 5

    filtered = {}
    for word, data in results.items():
        if word in garbage_words:
            continue
        familiarity = known_words.get(word)
        if familiarity is not None and min_familiarity <= familiarity <= max_familiarity:
            continue
        filtered[word] = {**data, "familiarity": familiarity}

    return filtered


def get_known_words_for_user(user_id: int, db: Session) -> dict[str, int]:
    """
    Returns a dict of {word: familiarity} for all known words for a user.
    """
    rows = db.execute(text("""
        SELECT word, familiarity FROM known_words
        WHERE user_id = :user_id
    """), {"user_id": user_id}).fetchall()

    return {word: familiarity for word, familiarity in rows}