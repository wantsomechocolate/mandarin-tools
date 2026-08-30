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
    input_text_id: int | None = None,
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

    `input_text_id` is passed straight through to build_user_overlay so a
    UserWord scoped to this text (but not others) is included - see that
    function's docstring for why only input-text scope, never analysis
    scope, is relevant when building an overlay.
    """
    segmenter = get_segmenter(db)
    overlay = (
        build_user_overlay(user_id, db, segmenter, input_text_id=input_text_id)
        if user_id is not None else None
    )

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
    input_text_id: int | None = None,
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
        input_text_id=input_text_id,
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
) -> dict[str, dict]:
    """
    Excludes garbage words (permanently - a word marked garbage is never
    persisted at all, see GarbageWord's docstring/CLAUDE.md) and annotates
    every remaining result with the word's current familiarity.

    Deliberately does NOT exclude by familiarity. Filtering by familiarity is
    a display-time concern only (the frontend's own "hide familiarity >= N"
    filter over already-persisted results) - it used to also exclude words
    here, before persistence, which meant a word marked known/familiar could
    never be found again even by widening the display filter to "show all",
    since the row simply didn't exist. See router.py's `/analyze` handler:
    every non-garbage word from `results` is now always persisted.
    """
    filtered = {}
    for word, data in results.items():
        if word in garbage_words:
            continue
        familiarity = known_words.get(word)
        filtered[word] = {**data, "familiarity": familiarity}

    return filtered


def get_known_words_for_user(
    user_id: int,
    db: Session,
    analysis_id: int | None = None,
    input_text_id: int | None = None,
) -> dict[str, int]:
    """
    Returns a dict of {word: familiarity} for all known words for a user.
    Resolved per-scope when analysis_id/input_text_id are given: an
    analysis-scoped entry for `analysis_id` wins over an input-text-scoped
    entry for `input_text_id`, which wins over the global (unscoped) entry -
    see KnownWord's scope_analysis_id/scope_input_text_id docstring. Passing
    neither returns only global entries.

    Note on the SQL: `scope_analysis_id = :analysis_id` when :analysis_id is
    Python None binds as `scope_analysis_id = NULL`, which SQL's
    three-valued logic always evaluates false - so passing None correctly
    matches no analysis-scoped rows without needing a separate NULL check.
    """
    rows = db.execute(text("""
        SELECT word, familiarity, scope_analysis_id, scope_input_text_id
        FROM known_words
        WHERE user_id = :user_id
        AND (
            (scope_analysis_id IS NULL AND scope_input_text_id IS NULL)
            OR scope_analysis_id = :analysis_id
            OR scope_input_text_id = :input_text_id
        )
    """), {"user_id": user_id, "analysis_id": analysis_id, "input_text_id": input_text_id}).fetchall()

    def scope_priority(scope_analysis_id: int | None, scope_input_text_id: int | None) -> int:
        if scope_analysis_id is not None:
            return 2
        if scope_input_text_id is not None:
            return 1
        return 0

    best: dict[str, tuple[int, int | None]] = {}
    for word, familiarity, sa, si in rows:
        priority = scope_priority(sa, si)
        if word not in best or priority > best[word][0]:
            best[word] = (priority, familiarity)

    return {word: familiarity for word, (_, familiarity) in best.items()}


def get_fragments_for_user(
    user_id: int,
    db: Session,
    analysis_id: int | None = None,
    input_text_id: int | None = None,
) -> dict[str, dict]:
    """
    Returns {word: {"id": int, "note": str|None}}, resolved analysis >
    input-text > global - same priority and same NULL-binding reasoning as
    get_known_words_for_user (see its docstring).
    """
    rows = db.execute(text("""
        SELECT id, word, note, scope_analysis_id, scope_input_text_id
        FROM fragments
        WHERE user_id = :user_id
        AND (
            (scope_analysis_id IS NULL AND scope_input_text_id IS NULL)
            OR scope_analysis_id = :analysis_id
            OR scope_input_text_id = :input_text_id
        )
    """), {"user_id": user_id, "analysis_id": analysis_id, "input_text_id": input_text_id}).fetchall()

    def scope_priority(scope_analysis_id: int | None, scope_input_text_id: int | None) -> int:
        if scope_analysis_id is not None:
            return 2
        if scope_input_text_id is not None:
            return 1
        return 0

    best: dict[str, tuple[int, dict]] = {}
    for id_, word, note, sa, si in rows:
        priority = scope_priority(sa, si)
        if word not in best or priority > best[word][0]:
            best[word] = (priority, {"id": id_, "note": note})

    return {word: data for word, (_, data) in best.items()}