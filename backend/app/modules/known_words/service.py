from sqlalchemy.orm import Session
from sqlalchemy import text

from app.modules.known_words.trie_loader import get_trie
from app.modules.known_words.segmentor import longest_matching
from app.modules.known_words.tokenizer import tokenize
from app.modules.known_words.segmenter_loader import get_segmenter, build_user_overlay
from app.modules.known_words.dag_segmentor import aggregate_segments


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


def analyze_text_dag(
    text_body: str,
    db: Session,
    user_id: int | None = None,
    tokenizer_stopwords: set[str] | None = None,
    min_token_length: int = 2,
    max_token_length: int = 20,
    min_token_count: int = 2,
) -> dict[str, dict]:
    """
    DAG + dynamic-programming counterpart to analyze_text. Runs the frequency-
    weighted segmenter (with the user's UserWord overlay, if any) instead of
    longest_matching, then merges in the existing tokenizer pass for unknown
    multi-character sequences, same as analyze_text does.

    This exists alongside analyze_text (rather than replacing it) so the two
    can be compared directly before deciding whether to switch the main
    /analyze endpoint over.
    """
    segmenter = get_segmenter(db)
    overlay = build_user_overlay(user_id, db, segmenter) if user_id is not None else None

    dag_results = segmenter.segment(text_body, overlay=overlay)
    dag_aggregated = aggregate_segments(dag_results)

    tok_sw = tokenizer_stopwords if tokenizer_stopwords is not None else DEFAULT_TOKENIZER_STOPWORDS
    trie = get_trie(db)
    token_results = tokenize(
        text_body,
        tok_sw,
        trie,
        min_length=min_token_length,
        max_length=max_token_length,
        min_count=min_token_count,
    )

    # DAG results take priority over tokenizer results for the same word,
    # matching how analyze_text prioritizes longest_matching over tokenize.
    merged = {**token_results, **dag_aggregated}

    return merged


def analyze_text_combined(
    text_body: str,
    db: Session,
    user_id: int | None = None,
    min_token_length: int = 2,
    max_token_length: int = 20,
    min_token_count: int = 2,
    lm_stopwords: set[str] | None = None,
    tokenizer_stopwords: set[str] | None = None,
) -> dict[str, dict]:
    """
    Primary production analysis: DAG+DP is the source of truth, longest_matching
    runs alongside purely as a safety net for dictionary coverage gaps the DAG
    can't see (a word missing from dictionary_words entirely means there's no
    DP path for it either — longest_matching's overlapping-match behavior
    sometimes stumbles onto pieces of it anyway).

    Any word longest_matching finds that isn't already covered by the DAG+token
    result is included with source="longest_match_only", so callers/UI can
    treat it as a lower-confidence supplemental suggestion rather than a
    primary result. DAG-covered words are never overridden by longest_matching,
    even if both find the same word — the DAG source label wins.
    """
    primary = analyze_text_dag(
        text_body,
        db,
        user_id=user_id,
        tokenizer_stopwords=tokenizer_stopwords,
        min_token_length=min_token_length,
        max_token_length=max_token_length,
        min_token_count=min_token_count,
    )

    legacy = analyze_text(
        text_body,
        db,
        min_token_length=min_token_length,
        max_token_length=max_token_length,
        min_token_count=min_token_count,
        lm_stopwords=lm_stopwords,
        tokenizer_stopwords=tokenizer_stopwords,
    )

    combined = dict(primary)
    for word, data in legacy.items():
        if word not in combined:
            combined[word] = {**data, "source": "longest_match_only"}

    return combined


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