import re

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.modules.known_words.trie_loader import get_trie
from app.modules.known_words.tokenizer import tokenize
from app.modules.known_words.segmenter_loader import get_segmenter, build_user_overlay
from app.modules.known_words.dag_segmentor import aggregate_segments, aggregate_full_segmentation

# Same CJK-ideograph range as difficulty.py's own _CJK_RE (kept as its own
# copy rather than a cross-module import - that one's module-private, and
# this is the same "at least one real Chinese character" gate the frontend
# search box already enforces client-side (containsChinese, analyze/[id]/
# +page.svelte) - this is the server-side half, not something new invented
# for search.
_CJK_RE = re.compile(r"[一-鿿]")


# DAG-only stopwords (Segmenter.build_dag/segment - see analyze_text below).
# Punctuation/whitespace here are real word-boundary breaks for
# segmentation: a word can never start with or extend through one. Union of
# the old DEFAULT_LM_STOPWORDS/DEFAULT_TOKENIZER_STOPWORDS plus a CJK
# punctuation audit: 「」『』〈〉〔〕 (paired quotation/citation brackets -
# the missing 「」 was the direct cause of a "「小猪"-style glued row, an
# opening quote fusing onto the word it quotes), the ideographic full-width
# space U+3000 (some CJK text uses it in place of an ASCII space), and the
# full-width forms of a few common ASCII punctuation marks that show up
# informally in CJK text (／ especially, in date-like "2024／01／01"
# formatting - the halfwidth "/" alone doesn't catch it). Not intended as
# an exhaustive punctuation list - just closing the gaps found so far;
# segmentation_affixes-style DB-backed additions are the path for anything
# else that turns up.
#
# Deliberately NOT shared with the tokenizer's repeated-sequence pass (see
# TOKENIZER_STOPWORDS below) - these two were briefly unified (migration
# e5640d2e5491) but that was reverted: stopping the repeated-sequence scan
# at every piece of punctuation means it can never find a repeat that spans
# a comma/period, which defeats the point of that pass. User-customizable
# (get_user_stopwords, DB-backed `stopwords` table) - that customization
# only ever applied to the DAG even when the two sets were unified, since
# nothing ever exposed a way to scope a stopword to just the tokenizer.
DEFAULT_STOPWORDS = {
    "\n", "，", "。", "！", "？", "、", "；", "：",
    """, """, "'", "'", "（", "）", "【", "】",
    "《", "》", "—", "…", "·", "～",
    ",", ".", "!", "?", ";", ":", "(", ")",
    "[", "]", "-", "/", "\\", "@", "#", "%",
    " ", "\t", "「", "」", "『", "』", "〈", "〉", "〔", "〕", "　",
    "／", "＼", "－",
}

# Tokenizer-only stopwords (tokenize(), repeated-sequence detection). Just
# the newline - a repeated sequence should be free to span punctuation
# (that's the whole point of scanning for it separately from the DAG), but
# never a paragraph break, which isn't part of any real sequence a user
# would recognize as repeated. Fixed, not user-customizable yet - unlike
# DEFAULT_STOPWORDS this isn't backed by the `stopwords` DB table today;
# making it configurable the same way is a deliberate later follow-up, not
# done in this pass.
TOKENIZER_STOPWORDS = {"\n"}


def _promote_confirmed_unknown_runs(best_guess: dict[str, dict], repeated: dict[str, dict]) -> None:
    """
    A merged "unknown" run (see _merge_unknown_runs, dag_segmentor.py) that
    the tokenizer *also* independently confirms as a repeated sequence
    graduates from "we don't recognize this at all" to "not in any
    dictionary, but this text repeats it enough to be a real unit" -
    relabeled in place, right here in best_guess (mutated directly), rather
    than added as a separate extra-match row. Deliberately an exact-string
    match only - no partial-credit slicing when the tokenizer's own
    candidate only overlaps part of a run, it just stays "unknown". Real
    positions/count stay best_guess's own (from the DAG walk), never the
    tokenizer's - only `source` changes.

    Must run before `extra` is built in analyze_text: once a word's
    `source` flips here, the existing "not already in best_guess" dedup
    automatically drops the tokenizer's own copy of the same word from
    `extra` - no separate bookkeeping needed for that.
    """
    for word, data in best_guess.items():
        if data["source"] == "unknown" and word in repeated:
            data["source"] = "repeated_sequence"


def analyze_text(
    text_body: str,
    db: Session,
    user_id: int | None = None,
    input_text_id: int | None = None,
    min_token_length: int = 2,
    max_token_length: int = 100,
    min_token_count: int = 2,
    stopwords: set[str] | None = None,
) -> dict[str, dict]:
    """
    Primary production analysis. Two views of one DAG build (see
    dag_segmentor.py's module docstring for the full jieba-mode framing):

    - best-guess: the DP's single chosen path (aggregate_segments) -
      source is "dag"/"overlay"/"unknown" per word, plus "repeated_sequence"
      for an "unknown" run the tokenizer also independently confirms
      repeats (see the promotion step below) - a merged run that doesn't
      clear the tokenizer's own thresholds stays "unknown".
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

    `stopwords` (the caller-supplied/DEFAULT_STOPWORDS set) governs the DAG
    build/segment/full-segmentation calls only - the tokenizer's repeated-
    sequence pass always uses its own fixed TOKENIZER_STOPWORDS (just the
    newline) regardless of what's passed here, so a repeated sequence can
    span punctuation the DAG itself would treat as a hard word boundary.
    See TOKENIZER_STOPWORDS' own comment above for why these two were
    re-split apart after briefly being unified. `stopwords` is also passed
    to tokenize() a second time as `junk_chars` though - a different role
    from the scan-boundary one above (see tokenize()'s own docstring for
    why a match can move through punctuation but not start or end on it).

    Lowercased before any of the below - Chinese characters have no case
    concept, so str.lower() is a no-op on them and only ever touches
    incidental Latin-script runs (an English word/phrase sitting in
    otherwise-Chinese text). Without this, "Love" and "love" are two
    unrelated strings to every step below: the tokenizer's repeated-
    sequence scan (tokenizer.py) counts exact substrings, so it never
    recognizes the two as the same word, and the DAG's per-character
    "unknown" fallback (nothing in a Chinese dictionary matches Latin
    letters at all) tags "L" and "l" as separate single-character words
    too - together producing exactly the "ove" flagged as a repeated
    sequence while L/l show up as unrelated singletons that motivated this
    fix. str.lower() preserves length/position character-for-character for
    standard text, so positions computed here stay valid offsets into the
    ORIGINAL (non-lowercased) InputText.body - this only changes what
    analysis treats as the same word for segmentation/counting purposes,
    never the stored source text or anything sliced from it (GET
    /analyze/{id}/context/{word}, /spans - both read positions against the
    original body, so the reading view and context snippets still show
    "Love" exactly as typed even though the results table now lists it
    merged into lowercase "love").
    """
    text_body = text_body.lower()
    stopwords = stopwords if stopwords is not None else DEFAULT_STOPWORDS
    segmenter = get_segmenter(db)
    overlay = (
        build_user_overlay(user_id, db, segmenter, input_text_id=input_text_id)
        if user_id is not None else None
    )

    trie = get_trie(db)

    # Built exactly once - both best-guess (via segment()'s dag= param) and
    # full segmentation consume this same dict, never rebuilding it.
    dag = segmenter.build_dag(text_body, overlay, stopwords)
    best_guess = aggregate_segments(segmenter.segment(text_body, overlay=overlay, stopwords=stopwords, dag=dag))
    # trie/overlay here (not just stopwords) so full segmentation doesn't
    # emit one row per unrecognized character now that best-guess merges
    # consecutive ones into a single run - see aggregate_full_segmentation's
    # own docstring.
    full = aggregate_full_segmentation(text_body, dag, stopwords, trie=trie, overlay=overlay)

    overlay_trie = overlay.trie if overlay is not None else None
    repeated = tokenize(
        text_body,
        TOKENIZER_STOPWORDS,
        trie,
        overlay_trie=overlay_trie,
        min_length=min_token_length,
        max_length=max_token_length,
        min_count=min_token_count,
        junk_chars=stopwords,
    )

    _promote_confirmed_unknown_runs(best_guess, repeated)

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
    additions, minus user overrides) - DAG-only (see DEFAULT_STOPWORDS/
    TOKENIZER_STOPWORDS above for why the tokenizer's repeated-sequence
    pass doesn't consult this).
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




def _escape_like_literal(text_: str) -> str:
    """
    Escapes the 3 characters that mean something special to Postgres's LIKE
    (backslash first, so the backslashes this inserts for % and _ don't
    themselves get re-escaped) - used by _build_like_pattern so a stray
    literal %/_ typed or pasted into the search box is matched literally,
    never mistaken for a SQL wildcard.
    """
    return text_.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _build_like_pattern(query: str) -> tuple[str, bool]:
    """
    Translates the search box's own tiny wildcard syntax into a Postgres
    LIKE pattern - '*' means "any sequence of characters" (mirrors SQL's
    own '%'), placed anywhere the caller wants it. See GET /word-search's
    docstring (router.py) for the real measured cost of each shape: a
    literal prefix before the first '*' (or no '*' at all) stays index-fast
    regardless of what follows, since Postgres's LIKE optimizer can turn
    that literal prefix into an indexed range scan on its own; only a
    query that OPENS with '*' (no literal prefix at all) forces a full
    scan - measured at ~250-550ms against the real ~1.66M-row
    dictionary_words table, vs. sub-millisecond for every prefixed shape.

    No '*' in the query: today's plain "starts with" behavior, unchanged -
    the query is escaped (see _escape_like_literal) and a trailing '%' is
    appended automatically, same as before this function existed.

    '*' present anywhere: "explicit mode" - escaped the same way, then
    every '*' becomes an unescaped '%'. No trailing wildcard is added once
    the user has taken control of the pattern - the same shell-glob
    convention used everywhere else this kind of syntax shows up, so "打*"
    behaves exactly like plain "打" (nothing to gain from adding a second,
    redundant wildcard), while matching "starts with 打, contains 电话
    later, then anything else" needs an explicit second '*': "打*电话*".

    Returns (pattern, is_wildcard) - is_wildcard tells the caller whether
    to keep the "exact match first" ORDER BY tie-break, which only makes
    sense for a plain literal query (a wildcard pattern has no single
    "the query equals this word" case to prefer).
    """
    is_wildcard = "*" in query
    escaped = _escape_like_literal(query)
    if is_wildcard:
        return escaped.replace("*", "%"), True
    return f"{escaped}%", False


def search_words(query: str, user_id: int, db: Session, limit: int = 100) -> tuple[list[dict], bool]:
    """
    Candidate-word resolution for GET /word-search. dictionary_words is
    already a FULL OUTER JOIN of word_frequencies ∪ hsk_entries ∪
    cedict_entries (see build_dictionary.py), with HSK levels/CC-CEDICT
    backing/corpus frequency all denormalized onto that one row (see its
    docstring, models.py) - so a single LIKE scan against it covers HSK,
    CC-CEDICT, and corpus matches at once. A user's own UserWord rows are
    scanned separately: a custom entry (e.g. a segmentation-artifact
    override with no real dictionary backing) still needs to be findable
    here even though it has no dictionary_words row at all. See
    _build_like_pattern for the '*'-wildcard syntax both scans share.

    Ranking: exact match first (skipped entirely for a wildcard pattern -
    see _build_like_pattern), then freq_per_million descending (nulls last
    - a user-only word has no frequency to rank by), then plain codepoint
    order - same non-phonetic tie-break precedent as the results page's
    own Word column sort (not localeCompare/pinyin - see CLAUDE.md's
    sorting note). The dictionary side's own top-`limit` (computed in SQL,
    already in this exact order) can only ever be added to by a user-only
    word, never displaced by one, since a user-only word has no frequency
    to outrank anything with - the one exception is an exact match on a
    non-wildcard query, which always sorts first regardless of which side
    found it.

    Returns (rows, truncated), capped at `limit`. Each row carries
    dictionary_words' own columns (word, frequency, hsk_v2_2012,
    hsk_v3_2021, hsk_v3_2026, freq_per_million, rarity_tier, is_cedict -
    None/False throughout for a user-only word) plus is_user_word.
    Per-word HSK-form/CC-CEDICT/UserWord/KnownWord/StarredWord/garbage
    enrichment is left entirely to the caller (router.py), which only ever
    needs to do it for this already-capped set - the same division of
    labor get_word_dictionary_tiers already uses (bulk-resolve the
    dictionary-backed half here, leave the rest to whoever's assembling the
    response).

    `truncated` is derived from over-fetching by one (`limit + 1`) rather
    than a separate COUNT(*) query - for a leading-'*' pattern (the one
    shape with no usable index), a full-table COUNT costs about as much as
    the scan itself (measured ~420ms against the real table), which would
    roughly double total latency for exactly the query shape already
    paying the most. Fetching one extra row and checking whether it came
    back answers "is there at least one more beyond `limit`" for the same
    price as fetching `limit` in the first place. The dictionary side is
    capped at `limit + 1` (real over-fetch); the user_words side never was
    capped at all (already a full, exact scan - see below), so `len(merged)
    > limit` after combining both is exact whenever the dictionary side
    wasn't the one hitting the cap, and correctly still True whenever it
    was, regardless of how many more actually exist beyond the extra row.
    """
    if not _CJK_RE.search(query):
        return [], False

    pattern, is_wildcard = _build_like_pattern(query)
    order_by = (
        "freq_per_million DESC NULLS LAST, word" if is_wildcard
        else "(word <> :query), freq_per_million DESC NULLS LAST, word"
    )

    # Over-fetch by one (see docstring above) instead of a separate
    # COUNT(*) - `fetch_cap` rows come back only when there are truly at
    # least that many matches.
    fetch_cap = limit + 1
    dict_rows = db.execute(text(f"""
        SELECT word, frequency, hsk_v2_2012, hsk_v3_2021, hsk_v3_2026,
               freq_per_million, rarity_tier, is_cedict
        FROM dictionary_words
        WHERE word LIKE :pattern ESCAPE '\\'
        ORDER BY {order_by}
        LIMIT :fetch_cap
    """), {"pattern": pattern, "query": query, "fetch_cap": fetch_cap}).mappings().all()
    dict_by_word = {r["word"]: dict(r) for r in dict_rows}

    # Never capped - scoped to one user, so this is always a small, exact
    # scan regardless of pattern shape (no perf concern to over-fetch
    # around here).
    user_word_rows = db.execute(text("""
        SELECT DISTINCT word FROM user_words
        WHERE user_id = :user_id AND word LIKE :pattern ESCAPE '\\'
    """), {"user_id": user_id, "pattern": pattern}).fetchall()
    user_matched_words = {w for (w,) in user_word_rows}
    user_only_words = user_matched_words - set(dict_by_word)

    merged = dict(dict_by_word)
    for word in user_only_words:
        merged[word] = {
            "word": word, "frequency": None, "hsk_v2_2012": None,
            "hsk_v3_2021": None, "hsk_v3_2026": None,
            "freq_per_million": None, "rarity_tier": None, "is_cedict": False,
        }

    def sort_key(word: str) -> tuple:
        freq = merged[word]["freq_per_million"]
        exact_first = word != query if not is_wildcard else False
        return (exact_first, -(freq if freq is not None else -1), word)

    ordered_words = sorted(merged, key=sort_key)[:limit]
    rows = [{**merged[w], "is_user_word": w in user_matched_words} for w in ordered_words]

    truncated = len(merged) > limit
    return rows, truncated


def get_word_enrichment(db: Session, word: str) -> dict | None:
    """
    Raw word_enrichment row as a dict, or None if nothing's been generated
    for this word yet - the router resolves this into WordEnrichmentResponse
    (translation precedence, staleness) rather than doing that here, so a
    None here cleanly means "nothing to resolve" for that caller.
    """
    row = db.execute(text("""
        SELECT word, pinyin, pinyin_generated_at,
               ctranslate2_translation, ctranslate2_generated_at, ctranslate2_model_version,
               google_translation, google_generated_at
        FROM word_enrichment WHERE word = :word
    """), {"word": word}).mappings().first()
    return dict(row) if row else None


def generate_fallback_enrichment(db: Session, word: str) -> dict:
    """
    Fills in pinyin (if missing) and (re)generates the CTranslate2
    translation - this one function serves all three of "nothing generated
    yet," "existing ctranslate2_translation is stale" (model version
    mismatch), and "user just wants to manually redo it," since the
    decision of *when* to call this is a frontend concern (which button it
    shows), not this function's. Upserts into the shared word_enrichment
    row - see WordEnrichment's docstring (models.py) for why this table is
    global, not per-user.
    """
    from app.modules.known_words.enrichment import (
        generate_pinyin,
        generate_ctranslate2_translation,
        CURRENT_CTRANSLATE2_MODEL_VERSION,
    )

    existing = get_word_enrichment(db, word)
    pinyin = existing["pinyin"] if existing and existing["pinyin"] else generate_pinyin(word)
    translation = generate_ctranslate2_translation(word)

    db.execute(text("""
        INSERT INTO word_enrichment (word, pinyin, pinyin_generated_at, ctranslate2_translation, ctranslate2_generated_at, ctranslate2_model_version)
        VALUES (:word, :pinyin, now(), :translation, now(), :model_version)
        ON CONFLICT (word) DO UPDATE SET
            pinyin = CASE WHEN word_enrichment.pinyin IS NULL THEN EXCLUDED.pinyin ELSE word_enrichment.pinyin END,
            pinyin_generated_at = CASE WHEN word_enrichment.pinyin IS NULL THEN EXCLUDED.pinyin_generated_at ELSE word_enrichment.pinyin_generated_at END,
            ctranslate2_translation = EXCLUDED.ctranslate2_translation,
            ctranslate2_generated_at = EXCLUDED.ctranslate2_generated_at,
            ctranslate2_model_version = EXCLUDED.ctranslate2_model_version
    """), {"word": word, "pinyin": pinyin, "translation": translation, "model_version": CURRENT_CTRANSLATE2_MODEL_VERSION})
    db.commit()

    return get_word_enrichment(db, word)
