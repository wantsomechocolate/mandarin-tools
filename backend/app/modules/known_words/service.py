from sqlalchemy.orm import Session
from sqlalchemy import text

from app.modules.known_words.trie_loader import get_trie
from app.modules.known_words.tokenizer import tokenize
from app.modules.known_words.segmenter_loader import get_segmenter, build_user_overlay
from app.modules.known_words.dag_segmentor import aggregate_segments, aggregate_full_segmentation


# One unified stopword list, not two per-algorithm ones - both the DAG
# (build_dag) and the tokenizer's repeated-sequence scan now consult the
# same set (see analyze_text below), so there's no more "an algorithm
# doesn't know about this stopword" gap for a symbol/bracket to slip
# through. Union of the old DEFAULT_LM_STOPWORDS/DEFAULT_TOKENIZER_STOPWORDS
# plus a CJK punctuation audit: 「」『』〈〉〔〕 (paired quotation/citation
# brackets - the missing 「」 was the direct cause of a "「小猪"-style glued
# row, an opening quote fusing onto the word it quotes), the ideographic
# full-width space U+3000 (some CJK text uses it in place of an ASCII
# space), and the full-width forms of a few common ASCII punctuation marks
# that show up informally in CJK text (／ especially, in date-like
# "2024／01／01" formatting - the halfwidth "/" alone doesn't catch it).
# Not intended as an exhaustive punctuation list - just closing the gaps
# found so far; segmentation_affixes-style DB-backed additions are the
# path for anything else that turns up.
DEFAULT_STOPWORDS = {
    "\n", "，", "。", "！", "？", "、", "；", "：",
    """, """, "'", "'", "（", "）", "【", "】",
    "《", "》", "—", "…", "·", "～",
    ",", ".", "!", "?", ";", ":", "(", ")",
    "[", "]", "-", "/", "\\", "@", "#", "%",
    " ", "\t", "「", "」", "『", "』", "〈", "〉", "〔", "〕", "　",
    "／", "＼", "－",
}


def analyze_text(
    text_body: str,
    db: Session,
    user_id: int | None = None,
    input_text_id: int | None = None,
    min_token_length: int = 2,
    max_token_length: int = 20,
    min_token_count: int = 2,
    stopwords: set[str] | None = None,
) -> dict[str, dict]:
    """
    Primary production analysis. Two views of one DAG build (see
    dag_segmentor.py's module docstring for the full jieba-mode framing):

    - best-guess: the DP's single chosen path (aggregate_segments) -
      source is "dag"/"overlay"/"unknown" per word, exactly as before.
    - extra matches: full segmentation minus best-guess (source
      "extra_match") unioned with the tokenizer's repeated-sequence finds
      not already in best-guess (source "repeated_sequence") - two
      independently-filterable buckets, replacing what the old
      segmentor.py's longest_matching was approximating (a second,
      lower-confidence pass over the same text) more completely: full
      segmentation includes user-overlay words, real per-occurrence
      positions, and no word-type coarseness, all for free from the same
      dag build the DP walk already needed - never a second, separate scan.
      The two are disjoint by construction (tokenize() skips anything
      that's a complete trie/overlay word), so no reconciliation is needed
      between them.

    Full segmentation's positions win over the tokenizer's on a word found
    by both (the tokenizer never records positions at all - see
    aggregate_full_segmentation's docstring for why full segmentation is
    the strictly more complete source for a word either pass can find).
    Best-guess is never overridden here even if the same word is also an
    unchosen full-segmentation/tokenizer candidate elsewhere in the text -
    a word that already won best-guess once keeps exactly its best-guess
    count/positions, nothing added from the other passes.

    `input_text_id` is passed straight through to build_user_overlay so a
    UserWord scoped to this text (but not others) is included - see that
    function's docstring for why only input-text scope, never analysis
    scope, is relevant when building an overlay.
    """
    stopwords = stopwords if stopwords is not None else DEFAULT_STOPWORDS
    segmenter = get_segmenter(db)
    overlay = (
        build_user_overlay(user_id, db, segmenter, input_text_id=input_text_id)
        if user_id is not None else None
    )

    # Built exactly once - both best-guess (via segment()'s dag= param) and
    # full segmentation consume this same dict, never rebuilding it.
    dag = segmenter.build_dag(text_body, overlay, stopwords)
    best_guess = aggregate_segments(segmenter.segment(text_body, overlay=overlay, stopwords=stopwords, dag=dag))
    full = aggregate_full_segmentation(text_body, dag, stopwords)

    trie = get_trie(db)
    overlay_trie = overlay.trie if overlay is not None else None
    repeated = tokenize(
        text_body,
        stopwords,
        trie,
        overlay_trie=overlay_trie,
        min_length=min_token_length,
        max_length=max_token_length,
        min_count=min_token_count,
    )

    repeated_tagged = {word: {**data, "source": "repeated_sequence"} for word, data in repeated.items()}
    full_tagged = {word: {**data, "source": "extra_match"} for word, data in full.items()}
    # full wins on a word found by both - shouldn't happen in practice given
    # tokenize()'s overlay_trie-aware skip above, but this keeps the same
    # defensive tie-break the old flat merge implicitly had.
    extra = {**repeated_tagged, **full_tagged}
    extra = {word: data for word, data in extra.items() if word not in best_guess}

    return {**extra, **best_guess}


def get_user_stopwords(user_id: int, db: Session) -> set[str]:
    """
    Returns one merged stopword set for a user (system defaults plus user
    additions, minus user overrides) - unified from the old per-algorithm
    (lm_stopwords, tokenizer_stopwords) pair now that both the DAG and the
    tokenizer consult the same list (see DEFAULT_STOPWORDS/analyze_text).
    """
    rows = db.execute(text("""
        SELECT word, is_override
        FROM stopwords
        WHERE user_id IS NULL OR user_id = :user_id
    """), {"user_id": user_id}).fetchall()

    stopwords = set(DEFAULT_STOPWORDS)
    overrides = set()

    for word, is_override in rows:
        if is_override:
            overrides.add(word)
        else:
            stopwords.add(word)

    stopwords -= overrides
    return stopwords


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


def get_word_dictionary_tiers(words: set[str], db: Session) -> dict[str, str]:
    """
    Bulk-resolves the dictionary-backing half of each word's evidence tier
    ('dictionary' or 'corpus') - the 'user'/'unknown' ends of the hierarchy
    are resolved by the caller (router.py), which already has the
    per-request user_words dict and doesn't need a query for either.

    One query for every word in the result set, not one per row. Per word:
    - 'dictionary' if HSK-backed (any of hsk_v2_2012/hsk_v3_2021/
      hsk_v3_2026 is not null) or CC-CEDICT-backed (is_cedict) - a curated
      source vouches for it regardless of whether it has usable corpus
      frequency.
    - else 'corpus' if frequency is not null AND > 0 - the same threshold
      segmenter_loader's freq_dict filter uses to decide what actually
      gets DP weight, so 'corpus' means "this word had real scoring
      influence," not just a stray zero-frequency row.
    - else the word is omitted entirely - the caller treats a missing key
      as no dictionary backing at all ('unknown', unless the user tier
      applies).

    Deliberately does not consult AnalysisResult.source for this - same
    reasoning as is_hidden/familiarity: resolved fresh from current
    dictionary_words state so a word's tier can correct itself (e.g. after
    a dictionary rebuild) without re-running analysis.
    """
    if not words:
        return {}
    rows = db.execute(text("""
        SELECT word, frequency, hsk_v2_2012, hsk_v3_2021, hsk_v3_2026, is_cedict
        FROM dictionary_words
        WHERE word = ANY(:words)
    """), {"words": list(words)}).fetchall()

    tiers: dict[str, str] = {}
    for word, frequency, hsk_v2, hsk_v3_2021, hsk_v3_2026, is_cedict in rows:
        if hsk_v2 is not None or hsk_v3_2021 is not None or hsk_v3_2026 is not None or is_cedict:
            tiers[word] = "dictionary"
        elif frequency is not None and frequency > 0:
            tiers[word] = "corpus"
    return tiers


def filter_results(
    results: dict[str, dict],
    known_words: dict[str, int],
    garbage_words: set[str],
) -> dict[str, dict]:
    """
    Annotates every result with the word's current familiarity and garbage
    status. Excludes nothing - the persisted analysis results are meant to be
    a faithful representation of the full contents of the analyzed text, so
    numbers/punctuation/junk (garbage_words) are persisted and returned just
    like everything else, only flagged via `is_garbage`.

    This mirrors how familiarity already works: a display-time concern only
    (the frontend's own "hide familiarity >= N" / "show garbage" filters over
    already-persisted results), never an exclusion at persist time. Both used
    to exclude here, which meant a word marked known/familiar - or garbage -
    could never be found again even by widening/toggling the display filter,
    since the row simply didn't exist. See router.py's `/analyze` handler:
    every word from `results` is now always persisted.
    """
    filtered = {}
    for word, data in results.items():
        familiarity = known_words.get(word)
        filtered[word] = {**data, "familiarity": familiarity, "is_garbage": word in garbage_words}

    return filtered


def get_known_words_for_user(user_id: int, db: Session) -> dict[str, int]:
    """
    Returns a dict of {word: familiarity} for all of a user's known words.
    Always global - see KnownWord's docstring for why familiarity isn't
    scoped to an analysis/text the way UserWord is.
    """
    rows = db.execute(text("""
        SELECT word, familiarity FROM known_words WHERE user_id = :user_id
    """), {"user_id": user_id}).fetchall()

    return {word: familiarity for word, familiarity in rows}


