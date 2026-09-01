import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, or_, text
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.modules.known_words import service

from app.modules.known_words.models import (
    InputText,
    Analysis,
    AnalysisResult,
    KnownWord,
    UserWord,
    WordVisibility,
    SampleSentence,
    Stopword,
    GarbageWord,
    StarredWord,
    DictionaryWord,
    HskEntry,
    HskForm,
    CedictEntry
)

from app.modules.known_words.schemas import (
    AnalyzeTextRequest,
    AnalysisResponse,
    AnalysisSummary,
    InputTextDetailResponse,
    WordOccurrence,
    WordContextResponse,
    WordResult,
    KnownWordUpdate,
    KnownWordResponse,
    UserWordCreate,
    UserWordResponse,
    UserWordUpsert,
    WordVisibilityUpsert,
    WordVisibilityResponse,
    SampleSentenceCreate,
    SampleSentenceResponse,
    InputTextResponse,
    StopwordCreate,
    StopwordResponse,
    GarbageWordCreate,
    GarbageWordResponse,
    StarredWordCreate,
    StarredWordResponse,
    StarredWordUpsert,
    HskFormDetail,
    CedictSense,
    WordDetail,
    CompareSegmentationRequest,
    CompareSegmentationResponse,
    SegmentedWord,
)


router = APIRouter(prefix="/known-words", tags=["known-words"])


# --- Scoping helpers, shared by the user-words CRUD endpoints below (see
# UserWord's scope_analysis_id/scope_input_text_id docstring in models.py
# for the full design). KnownWord (familiarity) is deliberately NOT scoped -
# see its own docstring - so it doesn't use these. ---

def _resolve_scope_columns(
    scope: str, analysis_id: int | None, input_text_id: int | None
) -> tuple[int | None, int | None]:
    """
    Turns a create/upsert request's scope choice ("global"/"text"/"analysis")
    plus the caller's current viewing context into the
    (scope_analysis_id, scope_input_text_id) column values to write.
    """
    if scope == "analysis":
        if analysis_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="analysis_id is required when scope is 'analysis'",
            )
        return analysis_id, None
    if scope == "text":
        if input_text_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="input_text_id is required when scope is 'text'",
            )
        return None, input_text_id
    return None, None


def _scope_filter_conditions(model, analysis_id: int | None, input_text_id: int | None) -> list:
    """
    Builds the OR-list of scope-match conditions for a scoped model, for a
    *resolved* read (list/detail endpoints): the global row always matches,
    plus an analysis-scoped or input-text-scoped row when that context is
    actually provided. Conditions for absent context are omitted entirely
    rather than compared against None - SQLAlchemy's `column == None` would
    otherwise auto-convert to `IS NULL` and incorrectly match every
    global-ish row instead of matching nothing.
    """
    conditions = [and_(model.scope_analysis_id.is_(None), model.scope_input_text_id.is_(None))]
    if analysis_id is not None:
        conditions.append(model.scope_analysis_id == analysis_id)
    if input_text_id is not None:
        conditions.append(model.scope_input_text_id == input_text_id)
    return conditions


def _scope_priority(row) -> int:
    """An analysis-scoped row outranks an input-text-scoped row, which
    outranks the global row - shared by _resolve_by_scope (bulk, picks one
    winner per word) and _sort_most_specific_first (single-word, keeps
    every row but orders them)."""
    if row.scope_analysis_id is not None:
        return 2
    if row.scope_input_text_id is not None:
        return 1
    return 0


def _resolve_by_scope(rows, key_fn):
    """
    Given ORM rows that already have scope_analysis_id/scope_input_text_id
    (e.g. from a query built with _scope_filter_conditions), picks the
    single highest-priority row per key_fn(row) - an analysis-scoped row
    wins over an input-text-scoped row, which wins over the global row.
    """
    best: dict = {}
    best_priority: dict = {}
    for row in rows:
        key = key_fn(row)
        p = _scope_priority(row)
        if key not in best or p > best_priority[key]:
            best[key] = row
            best_priority[key] = p
    return best


def _sort_most_specific_first(rows):
    """
    Same priority as _resolve_by_scope, but for a single word's already
    scope-filtered rows (e.g. from get_word_detail) where every applicable
    entry should be kept and shown, not collapsed to one winner - see
    UserWord's docstring (models.py) for why no entry should ever be hidden
    just because a more-specific one exists.
    """
    return sorted(rows, key=_scope_priority, reverse=True)


def _resolve_word_visibility(
    user_id: int, db: Session, analysis_id: int | None, input_text_id: int | None
) -> dict[str, tuple[bool, str]]:
    """
    Resolves {word: (hidden, governing_scope)} for every word that has at
    least one applicable WordVisibility row for this viewing context -
    reuses _scope_filter_conditions (which rows are even in play) and
    _resolve_by_scope (picking the single highest-priority row per word),
    same building blocks list_user_words uses for the analogous UserWord
    resolution. A word with no row anywhere simply isn't a key here -
    callers should default such words to (False, "default"), matching
    WordVisibility's "absence of a row IS the no-opinion state" docstring
    (models.py).
    """
    rows = db.query(WordVisibility).filter(
        WordVisibility.user_id == user_id,
        or_(*_scope_filter_conditions(WordVisibility, analysis_id, input_text_id)),
    ).all()
    winners = _resolve_by_scope(rows, key_fn=lambda wv: wv.word)
    resolved: dict[str, tuple[bool, str]] = {}
    for word, row in winners.items():
        if row.scope_analysis_id is not None:
            scope_name = "analysis"
        elif row.scope_input_text_id is not None:
            scope_name = "text"
        else:
            scope_name = "global"
        resolved[word] = (row.hidden, scope_name)
    return resolved


def _resolve_user_word_presence(
    user_id: int, db: Session, analysis_id: int | None, input_text_id: int | None
) -> set[str]:
    """
    Words that have at least one applicable UserWord row for this viewing
    context (global, plus this text's/this analysis's own row if
    applicable - same _scope_filter_conditions used by get_word_detail/
    list_user_words). Existence-based, like WordVisibility - unlike
    affects_dag there's no separate per-row opinion to resolve, just "is
    this word in the user's dictionary here." Powers WordResult.is_user_word.
    """
    rows = db.query(UserWord.word).filter(
        UserWord.user_id == user_id,
        or_(*_scope_filter_conditions(UserWord, analysis_id, input_text_id)),
    ).distinct().all()
    return {word for (word,) in rows}


@router.post("/compare-segmentation", response_model=CompareSegmentationResponse)
def compare_segmentation(
    request: CompareSegmentationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Runs both the existing longest-matching segmenter and the new DAG+DP
    segmenter over the same text and returns both, for manual comparison.
    Does not persist anything - safe to call repeatedly while testing.
    """
    lm_stopwords, tokenizer_stopwords = service.get_user_stopwords(current_user.id, db)

    lm_merged = service.analyze_text(
        text_body=request.body,
        db=db,
        min_token_length=request.min_token_length,
        max_token_length=request.max_token_length,
        min_token_count=request.min_token_count,
        lm_stopwords=lm_stopwords,
        tokenizer_stopwords=tokenizer_stopwords,
    )

    dag_merged = service.analyze_text_dag(
        text_body=request.body,
        db=db,
        user_id=current_user.id if request.use_user_overlay else None,
        tokenizer_stopwords=tokenizer_stopwords,
        min_token_length=request.min_token_length,
        max_token_length=request.max_token_length,
        min_token_count=request.min_token_count,
    )

    def to_list(results: dict[str, dict]) -> list[SegmentedWord]:
        return [
            SegmentedWord(word=w, count=d["count"], source=d["source"])
            for w, d in sorted(results.items(), key=lambda x: x[1]["count"], reverse=True)
        ]

    lm_words = set(lm_merged.keys())
    dag_words = set(dag_merged.keys())

    return CompareSegmentationResponse(
        body=request.body,
        longest_match_results=to_list(lm_merged),
        dag_results=to_list(dag_merged),
        only_in_longest_match=sorted(lm_words - dag_words),
        only_in_dag=sorted(dag_words - lm_words),
    )


@router.post("/analyze", response_model=AnalysisResponse)
def analyze(
    request: AnalyzeTextRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Reuse an existing InputText (re-analyze - just a new Analysis run under
    # it) if input_text_id is given, otherwise create a new InputText from
    # title/body as before.
    if request.input_text_id is not None:
        input_text = db.query(InputText).filter_by(
            id=request.input_text_id, user_id=current_user.id
        ).first()
        if not input_text:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Input text not found")
    else:
        if not request.body:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="body is required when input_text_id is not set"
            )
        input_text = InputText(
            user_id=current_user.id,
            title=request.title,
            body=request.body,
        )
        db.add(input_text)
        db.flush()

    body = input_text.body

    # Get user's stopwords and garbage words
    lm_stopwords, tokenizer_stopwords = service.get_user_stopwords(current_user.id, db)
    garbage_words = service.get_user_garbage_words(current_user.id, db)

    # Run analysis — DAG+DP is primary, longest-matching supplements it with
    # words the DAG's dictionary coverage misses (tagged source="longest_match_only")
    results = service.analyze_text_combined(
        text_body=body,
        db=db,
        user_id=current_user.id,
        input_text_id=input_text.id,
        min_token_length=request.min_token_length,
        max_token_length=request.max_token_length,
        min_token_count=request.min_token_count,
        lm_stopwords=lm_stopwords,
        tokenizer_stopwords=tokenizer_stopwords,
    )

    # Get user's known words (always global - see KnownWord's docstring) and
    # annotate familiarity/garbage status. Neither excludes here - see
    # filter_results docstring for why persistence must keep every word from
    # `results`, regardless of familiarity or garbage status.
    known_words = service.get_known_words_for_user(current_user.id, db)
    filtered = service.filter_results(results, known_words, garbage_words)

    # Save this run as its own Analysis under the input text, remembering
    # the config it used so future runs with different config are
    # distinguishable from this one.
    analysis = Analysis(
        input_text_id=input_text.id,
        min_token_length=request.min_token_length,
        max_token_length=request.max_token_length,
        min_token_count=request.min_token_count,
        min_familiarity_filter=request.min_familiarity_filter,
        max_familiarity_filter=request.max_familiarity_filter,
    )
    db.add(analysis)
    db.flush()

    # Save analysis results. "positions" is only present for words that came
    # from the DAG's own ordered walk (see aggregate_segments) - tokenizer/
    # longest_match_only-only words just get positions=None.
    for word, data in filtered.items():
        positions = data.get("positions")
        db.add(AnalysisResult(
            analysis_id=analysis.id,
            word=word,
            count=data["count"],
            source=data["source"],
            positions=[[start, end] for start, end in positions] if positions else None,
        ))

    db.commit()
    db.refresh(input_text)
    db.refresh(analysis)

    # Resolved fresh, same as familiarity/is_garbage - never persisted (see
    # WordVisibility's docstring, models.py). analysis.id already exists
    # here (post-flush/commit) but no WordVisibility row could reference it
    # yet regardless, since it was never exposed to the user before this
    # response - only text/global scope can meaningfully apply to a
    # brand-new analysis, same reasoning as build_user_overlay never
    # resolving analysis-scoped UserWord rows.
    visibility = _resolve_word_visibility(current_user.id, db, analysis.id, input_text.id)
    user_words_present = _resolve_user_word_presence(current_user.id, db, analysis.id, input_text.id)

    word_results = [
        WordResult(
            word=word,
            count=data["count"],
            source=data["source"],
            familiarity=data.get("familiarity"),
            is_garbage=data.get("is_garbage", False),
            is_hidden=visibility.get(word, (False, "default"))[0],
            hidden_governing_scope=visibility.get(word, (False, "default"))[1],
            is_user_word=word in user_words_present,
        )
        for word, data in sorted(filtered.items(), key=lambda x: x[1]["count"], reverse=True)
    ]

    # Totals reflect what was actually persisted (filtered = results, now
    # that nothing is excluded at persist time - not even garbage) - matches
    # how GET /analyze/{id} computes totals from the persisted rows, and
    # keeps the analysis a faithful representation of the full text.
    return AnalysisResponse(
        analysis_id=analysis.id,
        input_text_id=input_text.id,
        title=input_text.title,
        total_words=sum(d["count"] for d in filtered.values()),
        unique_words=len(filtered),
        results=word_results,
    )


@router.get("/analyze/{analysis_id}", response_model=AnalysisResponse)
def get_analysis(
    analysis_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    analysis = (
        db.query(Analysis)
        .join(InputText, Analysis.input_text_id == InputText.id)
        .filter(Analysis.id == analysis_id, InputText.user_id == current_user.id)
        .first()
    )
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")

    results = db.query(AnalysisResult).filter_by(analysis_id=analysis_id).all()
    known_words = service.get_known_words_for_user(current_user.id, db)
    garbage_words = service.get_user_garbage_words(current_user.id, db)
    # Unlike analyze()'s call to this, analysis_id here is a real, previously
    # -exposed analysis - an analysis-scoped WordVisibility row can and does
    # apply when reopening it, see _resolve_word_visibility.
    visibility = _resolve_word_visibility(current_user.id, db, analysis.id, analysis.input_text_id)
    user_words_present = _resolve_user_word_presence(current_user.id, db, analysis.id, analysis.input_text_id)

    word_results = [
        WordResult(
            word=r.word,
            count=r.count,
            source=r.source,
            familiarity=known_words.get(r.word),
            is_garbage=r.word in garbage_words,
            is_hidden=visibility.get(r.word, (False, "default"))[0],
            hidden_governing_scope=visibility.get(r.word, (False, "default"))[1],
            is_user_word=r.word in user_words_present,
        )
        for r in sorted(results, key=lambda x: x.count, reverse=True)
    ]

    return AnalysisResponse(
        analysis_id=analysis.id,
        input_text_id=analysis.input_text_id,
        title=analysis.input_text.title,
        total_words=sum(r.count for r in results),
        unique_words=len(results),
        results=word_results,
    )


@router.get("/analyze/{analysis_id}/context/{word}", response_model=WordContextResponse)
def get_word_context(
    analysis_id: int,
    word: str,
    context_chars: int = 15,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns every occurrence of `word` within analysis_id's source text, with
    `context_chars` characters of surrounding text on each side.

    Prefers stored positions (AnalysisResult.positions - exact, cheap, from
    the DAG's own segmentation walk) when present. Falls back to a live scan
    of the source text for words that don't have any - tokenizer/longest-
    matching-only words, or any word from an analysis run before positions
    existed - rather than returning nothing. This fallback is a plain
    substring search, not overlap-aware the way the DAG's own segmentation
    is, so it can surface a match that's actually part of a different word's
    span too (e.g. a search for a common radical inside longer words) - still
    real, useful text for a learner to see, just not guaranteed to align
    exactly with how this word was itself segmented.
    """
    analysis = (
        db.query(Analysis)
        .join(InputText, Analysis.input_text_id == InputText.id)
        .filter(Analysis.id == analysis_id, InputText.user_id == current_user.id)
        .first()
    )
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")

    body = analysis.input_text.body
    result = db.query(AnalysisResult).filter_by(analysis_id=analysis_id, word=word).first()

    positions = result.positions if result and result.positions else None
    if positions is None:
        positions = [(m.start(), m.end()) for m in re.finditer(re.escape(word), body)]

    occurrences = [
        WordOccurrence(
            start=start,
            end=end,
            before=body[max(0, start - context_chars):start],
            match=body[start:end],
            after=body[end:end + context_chars],
        )
        for start, end in positions
    ]

    return WordContextResponse(word=word, occurrences=occurrences)


@router.post("/known-words", response_model=KnownWordResponse, status_code=status.HTTP_201_CREATED)
def upsert_known_word(
    update: KnownWordUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    known_word = db.query(KnownWord).filter_by(
        user_id=current_user.id, word=update.word,
    ).first()

    if known_word:
        known_word.familiarity = update.familiarity
    else:
        known_word = KnownWord(
            user_id=current_user.id,
            word=update.word,
            familiarity=update.familiarity,
        )
        db.add(known_word)

    db.commit()
    db.refresh(known_word)
    return known_word


@router.get("/known-words", response_model=list[KnownWordResponse])
def list_known_words(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.query(KnownWord).filter(KnownWord.user_id == current_user.id).all()


@router.delete("/known-words/{word}", status_code=status.HTTP_204_NO_CONTENT)
def delete_known_word(
    word: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    known_word = db.query(KnownWord).filter_by(user_id=current_user.id, word=word).first()
    if not known_word:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Word not found")
    db.delete(known_word)
    db.commit()


@router.post("/user-words", response_model=UserWordResponse, status_code=status.HTTP_201_CREATED)
def create_user_word(
    user_word_in: UserWordCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    scope_analysis_id, scope_input_text_id = _resolve_scope_columns(
        user_word_in.scope, user_word_in.analysis_id, user_word_in.input_text_id
    )
    existing = db.query(UserWord).filter_by(
        user_id=current_user.id, word=user_word_in.word,
        scope_analysis_id=scope_analysis_id, scope_input_text_id=scope_input_text_id,
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User word already exists"
        )
    fields = user_word_in.model_dump(exclude={"analysis_id", "input_text_id", "scope"})
    user_word = UserWord(
        user_id=current_user.id,
        scope_analysis_id=scope_analysis_id,
        scope_input_text_id=scope_input_text_id,
        # Origin is recorded regardless of final scope - see UserWord docstring.
        created_from_analysis_id=user_word_in.analysis_id,
        created_from_input_text_id=user_word_in.input_text_id,
        **fields,
    )
    db.add(user_word)
    db.commit()
    db.refresh(user_word)
    return user_word


def _resolve_input_text_titles(rows: list[UserWord], db: Session) -> dict[int, str | None]:
    """
    Maps each of `rows`' own id to the title of whatever InputText it's
    ultimately scoped under - directly for a text-scoped row, via its
    Analysis for an analysis-scoped row, None for a global row. Bulk
    (2 queries total, not N+1) - only used by list_user_words' all_scopes
    view.
    """
    text_ids = {r.scope_input_text_id for r in rows if r.scope_input_text_id is not None}
    analysis_ids = {r.scope_analysis_id for r in rows if r.scope_analysis_id is not None}

    titles_by_text_id: dict[int, str | None] = {}
    if text_ids:
        for t_id, title in db.query(InputText.id, InputText.title).filter(InputText.id.in_(text_ids)).all():
            titles_by_text_id[t_id] = title

    text_id_by_analysis_id: dict[int, int] = {}
    if analysis_ids:
        for a_id, t_id in db.query(Analysis.id, Analysis.input_text_id).filter(Analysis.id.in_(analysis_ids)).all():
            text_id_by_analysis_id[a_id] = t_id
        more_text_ids = set(text_id_by_analysis_id.values()) - set(titles_by_text_id.keys())
        if more_text_ids:
            for t_id, title in db.query(InputText.id, InputText.title).filter(InputText.id.in_(more_text_ids)).all():
                titles_by_text_id[t_id] = title

    result: dict[int, str | None] = {}
    for r in rows:
        if r.scope_input_text_id is not None:
            result[r.id] = titles_by_text_id.get(r.scope_input_text_id)
        elif r.scope_analysis_id is not None:
            t_id = text_id_by_analysis_id.get(r.scope_analysis_id)
            result[r.id] = titles_by_text_id.get(t_id) if t_id is not None else None
        else:
            result[r.id] = None
    return result


@router.get("/user-words", response_model=list[UserWordResponse])
def list_user_words(
    analysis_id: int | None = None,
    input_text_id: int | None = None,
    all_scopes: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Resolved (analysis > text > global - see UserWord's scope docstring) set
    of user words for the given viewing context. Omitting both params
    returns only global entries.

    all_scopes=true bypasses analysis_id/input_text_id and the resolution
    above entirely, instead returning every UserWord row for this user
    across every scope, unresolved - for a management view ("see all your
    user words, wherever they're scoped"), not the DAG overlay's
    pick-one-per-word resolution used elsewhere. Each row is annotated with
    input_text_title (see _resolve_input_text_titles) so the UI can label
    scoped rows without a per-row round trip.
    """
    if all_scopes:
        rows = db.query(UserWord).filter(UserWord.user_id == current_user.id).all()
        titles = _resolve_input_text_titles(rows, db)
        return [
            UserWordResponse.model_validate(r).model_copy(update={"input_text_title": titles.get(r.id)})
            for r in rows
        ]

    rows = db.query(UserWord).filter(
        UserWord.user_id == current_user.id,
        or_(*_scope_filter_conditions(UserWord, analysis_id, input_text_id)),
    ).all()
    return list(_resolve_by_scope(rows, key_fn=lambda uw: uw.word).values())


@router.delete("/user-words/{word}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user_word(
    word: str,
    scope_analysis_id: int | None = None,
    scope_input_text_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Deletes the entry at exactly the given scope (default: the global
    entry, matching behavior before scoping existed)."""
    user_word = db.query(UserWord).filter_by(
        user_id=current_user.id, word=word,
        scope_analysis_id=scope_analysis_id, scope_input_text_id=scope_input_text_id,
    ).first()
    if not user_word:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User word not found")
    db.delete(user_word)
    db.commit()


@router.put("/user-words/{word}", response_model=UserWordResponse)
def upsert_user_word_detail(
    word: str,
    update: UserWordUpsert,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Creates or updates a user's word entry at the given scope (default:
    global, matching behavior before scoping existed). Only fields
    explicitly present in the request body are changed on an existing row —
    this is what lets the word-detail panel save a pronunciation or meaning
    directly without a separate "add word" step: filling in either field is
    enough to create the UserWord row.
    """
    scope_analysis_id, scope_input_text_id = _resolve_scope_columns(
        update.scope, update.analysis_id, update.input_text_id
    )
    user_word = db.query(UserWord).filter_by(
        user_id=current_user.id, word=word,
        scope_analysis_id=scope_analysis_id, scope_input_text_id=scope_input_text_id,
    ).first()

    provided = update.model_dump(exclude_unset=True, exclude={"analysis_id", "input_text_id", "scope"})

    if user_word:
        for field, value in provided.items():
            setattr(user_word, field, value)
    else:
        dict_word = db.query(DictionaryWord).filter_by(word=word).first()
        user_word = UserWord(
            user_id=current_user.id,
            word=word,
            dictionary_word_id=dict_word.id if dict_word else None,
            scope_analysis_id=scope_analysis_id,
            scope_input_text_id=scope_input_text_id,
            created_from_analysis_id=update.analysis_id,
            created_from_input_text_id=update.input_text_id,
            **provided,
        )
        db.add(user_word)

    db.commit()
    db.refresh(user_word)
    return user_word


# Word visibility ("hide from results") - see WordVisibility's docstring
# (models.py) for why this is its own scoped table rather than a column on
# UserWord.
@router.put("/word-visibility/{word}", response_model=WordVisibilityResponse)
def upsert_word_visibility(
    word: str,
    update: WordVisibilityUpsert,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Creates or updates the hidden flag at the given scope (default: global,
    same convention as upsert_user_word_detail). Simpler than that endpoint:
    WordVisibility has exactly one meaningful field, so there's no
    exclude_unset partial-update logic needed - `hidden` is always present
    and always written.
    """
    scope_analysis_id, scope_input_text_id = _resolve_scope_columns(
        update.scope, update.analysis_id, update.input_text_id
    )
    row = db.query(WordVisibility).filter_by(
        user_id=current_user.id, word=word,
        scope_analysis_id=scope_analysis_id, scope_input_text_id=scope_input_text_id,
    ).first()
    if row:
        row.hidden = update.hidden
    else:
        row = WordVisibility(
            user_id=current_user.id, word=word, hidden=update.hidden,
            scope_analysis_id=scope_analysis_id, scope_input_text_id=scope_input_text_id,
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/word-visibility/{word}", status_code=status.HTTP_204_NO_CONTENT)
def delete_word_visibility(
    word: str,
    scope_analysis_id: int | None = None,
    scope_input_text_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Deletes the override at exactly the given scope (default: global) -
    same pattern as delete_user_word. Reverts that scope to "no opinion,
    inherit from the next broader scope," it does NOT necessarily make the
    word shown again - a broader scope's own row (or lack thereof) still
    governs after this.
    """
    row = db.query(WordVisibility).filter_by(
        user_id=current_user.id, word=word,
        scope_analysis_id=scope_analysis_id, scope_input_text_id=scope_input_text_id,
    ).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visibility override not found")
    db.delete(row)
    db.commit()


# Sample sentences - a word can have many, meant for pasting in real usage
# copied from a text's context view (see get_word_context below) rather than
# writing one from scratch. Deliberately independent of UserWord (earlier
# version attached them to a UserWord row - reversed, see SampleSentence's
# docstring in models.py) - global per user+word, no scoping, no find-or-
# create dance with another table.
@router.post("/sample-sentences", response_model=SampleSentenceResponse, status_code=status.HTTP_201_CREATED)
def create_sample_sentence(
    sentence_in: SampleSentenceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sentence = SampleSentence(
        user_id=current_user.id, word=sentence_in.word, sentence=sentence_in.sentence
    )
    db.add(sentence)
    db.commit()
    db.refresh(sentence)
    return sentence


@router.get("/sample-sentences", response_model=list[SampleSentenceResponse])
def list_sample_sentences(
    word: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(SampleSentence).filter(SampleSentence.user_id == current_user.id)
    if word is not None:
        query = query.filter(SampleSentence.word == word)
    return query.order_by(SampleSentence.created_at).all()


@router.delete("/sample-sentences/{sentence_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sample_sentence(
    sentence_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sentence = db.query(SampleSentence).filter_by(
        id=sentence_id, user_id=current_user.id
    ).first()
    if not sentence:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sentence not found")
    db.delete(sentence)
    db.commit()


# Input texts
@router.get("/input-texts", response_model=list[InputTextResponse])
def list_input_texts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    input_texts = (
        db.query(InputText)
        .filter_by(user_id=current_user.id)
        .order_by(InputText.created_at.desc())
        .all()
    )

    # Latest Analysis id per text (by created_at, not just id, to be
    # correct even if that were ever to diverge) - DISTINCT ON is the
    # idiomatic Postgres way to get "top row per group" in one query.
    latest_analysis_ids = dict(db.execute(text("""
        SELECT DISTINCT ON (input_text_id) input_text_id, id
        FROM analyses
        WHERE input_text_id = ANY(:input_text_ids)
        ORDER BY input_text_id, created_at DESC
    """), {"input_text_ids": [t.id for t in input_texts]}).fetchall())

    return [
        InputTextResponse(
            id=t.id,
            title=t.title,
            created_at=t.created_at,
            updated_at=t.updated_at,
            latest_analysis_id=latest_analysis_ids.get(t.id),
        )
        for t in input_texts
    ]


@router.get("/input-texts/{input_text_id}", response_model=InputTextDetailResponse)
def get_input_text(
    input_text_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    input_text = db.query(InputText).filter_by(
        id=input_text_id, user_id=current_user.id
    ).first()
    if not input_text:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Input text not found")

    analyses = (
        db.query(Analysis)
        .filter_by(input_text_id=input_text_id)
        .order_by(Analysis.created_at.desc())
        .all()
    )

    # total_words/unique_words computed query-time per analysis, same as
    # AnalysisResponse already does - not stored redundantly on Analysis.
    summaries = []
    for a in analyses:
        results = db.query(AnalysisResult).filter_by(analysis_id=a.id).all()
        summaries.append(AnalysisSummary(
            id=a.id,
            created_at=a.created_at,
            total_words=sum(r.count for r in results),
            unique_words=len(results),
            min_token_length=a.min_token_length,
            max_token_length=a.max_token_length,
            min_token_count=a.min_token_count,
            min_familiarity_filter=a.min_familiarity_filter,
            max_familiarity_filter=a.max_familiarity_filter,
        ))

    return InputTextDetailResponse(
        id=input_text.id,
        title=input_text.title,
        body=input_text.body,
        created_at=input_text.created_at,
        updated_at=input_text.updated_at,
        analyses=summaries,
    )


@router.delete("/input-texts/{input_text_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_input_text(
    input_text_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    input_text = db.query(InputText).filter_by(
        id=input_text_id, user_id=current_user.id
    ).first()
    if not input_text:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Input text not found")
    db.delete(input_text)
    db.commit()


# Stopwords
@router.get("/stopwords", response_model=list[StopwordResponse])
def list_stopwords(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.query(Stopword).filter(
        (Stopword.user_id == None) | (Stopword.user_id == current_user.id)
    ).all()


@router.post("/stopwords", response_model=StopwordResponse, status_code=status.HTTP_201_CREATED)
def create_stopword(
    stopword_in: StopwordCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if stopword_in.algo_type not in ("longest_match", "tokenization"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="algo_type must be 'longest_match' or 'tokenization'"
        )
    existing = db.query(Stopword).filter_by(
        user_id=current_user.id,
        word=stopword_in.word,
        algo_type=stopword_in.algo_type,
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Stopword already exists"
        )
    stopword = Stopword(
        user_id=current_user.id,
        word=stopword_in.word,
        algo_type=stopword_in.algo_type,
        is_override=stopword_in.is_override,
    )
    db.add(stopword)
    db.commit()
    db.refresh(stopword)
    return stopword


@router.delete("/stopwords/{stopword_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_stopword(
    stopword_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stopword = db.query(Stopword).filter_by(
        id=stopword_id, user_id=current_user.id
    ).first()
    if not stopword:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stopword not found")
    db.delete(stopword)
    db.commit()


# Garbage words
@router.get("/garbage-words", response_model=list[GarbageWordResponse])
def list_garbage_words(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.query(GarbageWord).filter(
        (GarbageWord.user_id == None) | (GarbageWord.user_id == current_user.id)
    ).all()


@router.post("/garbage-words", response_model=GarbageWordResponse, status_code=status.HTTP_201_CREATED)
def create_garbage_word(
    garbage_word_in: GarbageWordCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    existing = db.query(GarbageWord).filter_by(
        user_id=current_user.id,
        word=garbage_word_in.word,
    ).first()
    if existing:
        # Re-marking a word whose only user-owned row is an override (added
        # by unmark_garbage_word below, to cancel out a system-default
        # marking) is a legitimate "mark it again" request, not a duplicate -
        # flip it back rather than blocking.
        if existing.is_override and not garbage_word_in.is_override:
            existing.is_override = False
            db.commit()
            db.refresh(existing)
            return existing
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Garbage word already exists"
        )
    garbage_word = GarbageWord(
        user_id=current_user.id,
        word=garbage_word_in.word,
        is_override=garbage_word_in.is_override,
    )
    db.add(garbage_word)
    db.commit()
    db.refresh(garbage_word)
    return garbage_word


# Reverses whatever is currently making `word` show as garbage for this user
# - deletes the user's own non-override GarbageWord row if they added one
# themselves, or adds an override row to cancel out a system-default marking
# otherwise (see GarbageWord.is_override / service.get_user_garbage_words).
# Word-based (not id-based, unlike delete_garbage_word below) so the
# frontend can call it the same way it unmarks a fragment, without needing
# to know which row - own or system-default - is actually responsible.
@router.delete("/garbage-words/word/{word}", status_code=status.HTTP_204_NO_CONTENT)
def unmark_garbage_word(
    word: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    own_row = db.query(GarbageWord).filter_by(
        user_id=current_user.id, word=word, is_override=False
    ).first()
    if own_row:
        db.delete(own_row)
        db.commit()
        return

    garbage_words = service.get_user_garbage_words(current_user.id, db)
    if word not in garbage_words:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Word is not marked as garbage")

    # Only a system-default row can be marking it garbage at this point (no
    # user-owned non-override row, but still garbage) - cancel it out with
    # an override rather than trying to delete a row this user doesn't own.
    db.add(GarbageWord(user_id=current_user.id, word=word, is_override=True))
    db.commit()


@router.delete("/garbage-words/{garbage_word_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_garbage_word(
    garbage_word_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    garbage_word = db.query(GarbageWord).filter_by(
        id=garbage_word_id, user_id=current_user.id
    ).first()
    if not garbage_word:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Garbage word not found")
    db.delete(garbage_word)
    db.commit()


# Starred words — a lightweight personal bookmark ("this looks interesting,
# come back to it"), global only (see StarredWord's docstring for why it's
# not scoped like KnownWord/UserWord).
@router.get("/starred-words", response_model=list[StarredWordResponse])
def list_starred_words(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.query(StarredWord).filter_by(user_id=current_user.id).all()


@router.post("/starred-words", response_model=StarredWordResponse, status_code=status.HTTP_201_CREATED)
def create_starred_word(
    starred_in: StarredWordCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    existing = db.query(StarredWord).filter_by(
        user_id=current_user.id, word=starred_in.word
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Starred word already exists"
        )
    starred = StarredWord(
        user_id=current_user.id,
        word=starred_in.word,
        note=starred_in.note,
    )
    db.add(starred)
    db.commit()
    db.refresh(starred)
    return starred


@router.put("/starred-words/{word}", response_model=StarredWordResponse)
def upsert_starred_word(
    word: str,
    update: StarredWordUpsert,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Creates or updates a starred word's note — same upsert pattern as
    /fragments/{word}."""
    starred = db.query(StarredWord).filter_by(
        user_id=current_user.id, word=word
    ).first()

    if starred:
        for field, value in update.model_dump(exclude_unset=True).items():
            setattr(starred, field, value)
    else:
        starred = StarredWord(
            user_id=current_user.id,
            word=word,
            **update.model_dump(exclude_unset=True),
        )
        db.add(starred)

    db.commit()
    db.refresh(starred)
    return starred


@router.delete("/starred-words/{word}", status_code=status.HTTP_204_NO_CONTENT)
def delete_starred_word(
    word: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    starred = db.query(StarredWord).filter_by(
        user_id=current_user.id, word=word
    ).first()
    if not starred:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Starred word not found")
    db.delete(starred)
    db.commit()


@router.get("/words/{word}", response_model=WordDetail)
def get_word_detail(
    word: str,
    analysis_id: int | None = None,
    input_text_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    analysis_id/input_text_id (the caller's current viewing context) decide
    which scoped user_word rows are relevant - global always, plus this
    analysis's/this text's own row if applicable (see
    _scope_filter_conditions). Omitting both shows only global entries.

    user_words returns every applicable row, most-specific first - never
    resolved to one, so the panel can show/edit/delete each independently
    without implying a relationship between scopes (see UserWord's
    docstring).
    """

    dict_word = db.query(DictionaryWord).filter_by(word=word).first()

    hsk_entry = db.query(HskEntry).filter_by(simplified=word).first()
    forms = []
    if hsk_entry:
        forms = db.query(HskForm).filter_by(entry_id=hsk_entry.id).all()

    cedict_entries = db.query(CedictEntry).filter_by(simplified=word).all()

    user_word_rows = db.query(UserWord).filter(
        UserWord.user_id == current_user.id, UserWord.word == word,
        or_(*_scope_filter_conditions(UserWord, analysis_id, input_text_id)),
    ).all()
    user_words = _sort_most_specific_first(user_word_rows)

    # Same shape/reasoning as user_words above - every applicable scope's
    # row, most-specific first, never resolved to one, so the panel's
    # Visibility section can show/edit/remove each scope independently.
    word_visibility_rows = db.query(WordVisibility).filter(
        WordVisibility.user_id == current_user.id, WordVisibility.word == word,
        or_(*_scope_filter_conditions(WordVisibility, analysis_id, input_text_id)),
    ).all()
    word_visibility = _sort_most_specific_first(word_visibility_rows)

    sample_sentences = (
        db.query(SampleSentence)
        .filter(SampleSentence.user_id == current_user.id, SampleSentence.word == word)
        .order_by(SampleSentence.created_at)
        .all()
    )

    return WordDetail(
        word=word,
        frequency=dict_word.frequency if dict_word else None,
        freq_per_million=dict_word.freq_per_million if dict_word else None,
        rarity_tier=dict_word.rarity_tier if dict_word else None,
        hsk_v2_2012=hsk_entry.hsk_v2_2012 if hsk_entry else None,
        hsk_v3_2021=hsk_entry.hsk_v3_2021 if hsk_entry else None,
        hsk_v3_2026=hsk_entry.hsk_v3_2026 if hsk_entry else None,
        forms=[
            HskFormDetail(
                traditional=f.traditional,
                pinyin=f.pinyin,
                meanings=f.meanings or [],
                classifiers=f.classifiers or [],
            )
            for f in forms
        ],
        cedict=[
            CedictSense(
                traditional=c.traditional,
                pinyin=c.pinyin,
                definitions=c.definitions or [],
            )
            for c in cedict_entries
        ],
        user_words=user_words,
        word_visibility=word_visibility,
        sample_sentences=sample_sentences,
    )