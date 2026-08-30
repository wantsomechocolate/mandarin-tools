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
    Stopword,
    GarbageWord,
    Fragment,
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
    InputTextResponse,
    StopwordCreate,
    StopwordResponse,
    GarbageWordCreate,
    GarbageWordResponse,
    FragmentCreate,
    FragmentResponse,
    FragmentUpsert,
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


# --- Scoping helpers, shared by the known-words/user-words/fragments CRUD
# endpoints below (see KnownWord/UserWord/Fragment's scope_analysis_id/
# scope_input_text_id docstrings in models.py for the full design). ---

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


def _resolve_by_scope(rows, key_fn):
    """
    Given ORM rows that already have scope_analysis_id/scope_input_text_id
    (e.g. from a query built with _scope_filter_conditions), picks the
    single highest-priority row per key_fn(row) - an analysis-scoped row
    wins over an input-text-scoped row, which wins over the global row.
    """
    def priority(row) -> int:
        if row.scope_analysis_id is not None:
            return 2
        if row.scope_input_text_id is not None:
            return 1
        return 0

    best: dict = {}
    best_priority: dict = {}
    for row in rows:
        key = key_fn(row)
        p = priority(row)
        if key not in best or p > best_priority[key]:
            best[key] = row
            best_priority[key] = p
    return best


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

    # Get user's known words (resolved for this text - the new Analysis
    # doesn't have an id yet, but nothing could be scoped to it anyway; see
    # get_known_words_for_user) and filter out garbage (familiarity no
    # longer excludes here - see filter_results docstring for why
    # persistence must keep every non-garbage word regardless of familiarity).
    known_words = service.get_known_words_for_user(current_user.id, db, input_text_id=input_text.id)
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

    word_results = [
        WordResult(
            word=word,
            count=data["count"],
            source=data["source"],
            familiarity=data.get("familiarity"),
        )
        for word, data in sorted(filtered.items(), key=lambda x: x[1]["count"], reverse=True)
    ]

    # Totals reflect what was actually persisted (filtered = results minus
    # garbage words only, now that familiarity no longer excludes rows) -
    # matches how GET /analyze/{id} computes totals from the persisted rows,
    # rather than counting garbage words that were never saved.
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
    known_words = service.get_known_words_for_user(
        current_user.id, db, analysis_id=analysis_id, input_text_id=analysis.input_text_id
    )

    word_results = [
        WordResult(
            word=r.word,
            count=r.count,
            source=r.source,
            familiarity=known_words.get(r.word),
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
    scope_analysis_id, scope_input_text_id = _resolve_scope_columns(
        update.scope, update.analysis_id, update.input_text_id
    )
    known_word = db.query(KnownWord).filter_by(
        user_id=current_user.id, word=update.word,
        scope_analysis_id=scope_analysis_id, scope_input_text_id=scope_input_text_id,
    ).first()

    if known_word:
        known_word.familiarity = update.familiarity
    else:
        known_word = KnownWord(
            user_id=current_user.id,
            word=update.word,
            familiarity=update.familiarity,
            scope_analysis_id=scope_analysis_id,
            scope_input_text_id=scope_input_text_id,
        )
        db.add(known_word)

    db.commit()
    db.refresh(known_word)
    return known_word


@router.get("/known-words", response_model=list[KnownWordResponse])
def list_known_words(
    analysis_id: int | None = None,
    input_text_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Resolved (analysis > text > global - see KnownWord's scope docstring)
    set of known words for the given viewing context. Omitting both params
    returns only global entries.
    """
    rows = db.query(KnownWord).filter(
        KnownWord.user_id == current_user.id,
        or_(*_scope_filter_conditions(KnownWord, analysis_id, input_text_id)),
    ).all()
    return list(_resolve_by_scope(rows, key_fn=lambda kw: kw.word).values())


@router.delete("/known-words/{word}", status_code=status.HTTP_204_NO_CONTENT)
def delete_known_word(
    word: str,
    scope_analysis_id: int | None = None,
    scope_input_text_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Deletes the entry at exactly the given scope (default: the global
    entry, matching behavior before scoping existed)."""
    known_word = db.query(KnownWord).filter_by(
        user_id=current_user.id, word=word,
        scope_analysis_id=scope_analysis_id, scope_input_text_id=scope_input_text_id,
    ).first()
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


@router.get("/user-words", response_model=list[UserWordResponse])
def list_user_words(
    analysis_id: int | None = None,
    input_text_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Resolved (analysis > text > global - see UserWord's scope docstring) set
    of user words for the given viewing context. Omitting both params
    returns only global entries.
    """
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


# Fragments — segmentation artifacts / partial strings worth annotating but
# not studying. Deliberately NOT wired into /analyze or filter_results: unlike
# garbage words (excluded from results before they're ever persisted) or
# familiar known words (same), a fragment stays in the persisted analysis
# results exactly as segmented. Hiding it from the default view and letting
# the user reveal/annotate it is handled client-side, the same way
# source="longest_match_only" words are handled — this keeps fragment
# marking fully reversible and inspectable, rather than a one-way deletion.
@router.get("/fragments", response_model=list[FragmentResponse])
def list_fragments(
    analysis_id: int | None = None,
    input_text_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Resolved (analysis > text > global - see Fragment's scope docstring) set
    of fragments for the given viewing context. Omitting both params
    returns only global entries.
    """
    rows = db.query(Fragment).filter(
        Fragment.user_id == current_user.id,
        or_(*_scope_filter_conditions(Fragment, analysis_id, input_text_id)),
    ).all()
    return list(_resolve_by_scope(rows, key_fn=lambda f: f.word).values())


@router.post("/fragments", response_model=FragmentResponse, status_code=status.HTTP_201_CREATED)
def create_fragment(
    fragment_in: FragmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    scope_analysis_id, scope_input_text_id = _resolve_scope_columns(
        fragment_in.scope, fragment_in.analysis_id, fragment_in.input_text_id
    )
    existing = db.query(Fragment).filter_by(
        user_id=current_user.id, word=fragment_in.word,
        scope_analysis_id=scope_analysis_id, scope_input_text_id=scope_input_text_id,
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Fragment already exists"
        )
    fragment = Fragment(
        user_id=current_user.id,
        word=fragment_in.word,
        note=fragment_in.note,
        scope_analysis_id=scope_analysis_id,
        scope_input_text_id=scope_input_text_id,
    )
    db.add(fragment)
    db.commit()
    db.refresh(fragment)
    return fragment


@router.put("/fragments/{word}", response_model=FragmentResponse)
def upsert_fragment(
    word: str,
    update: FragmentUpsert,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Creates or updates a fragment note at the given scope (default:
    global) — same upsert + scope pattern as /user-words/{word}: marking a
    fragment and annotating it are one action."""
    scope_analysis_id, scope_input_text_id = _resolve_scope_columns(
        update.scope, update.analysis_id, update.input_text_id
    )
    fragment = db.query(Fragment).filter_by(
        user_id=current_user.id, word=word,
        scope_analysis_id=scope_analysis_id, scope_input_text_id=scope_input_text_id,
    ).first()

    provided = update.model_dump(exclude_unset=True, exclude={"analysis_id", "input_text_id", "scope"})

    if fragment:
        for field, value in provided.items():
            setattr(fragment, field, value)
    else:
        fragment = Fragment(
            user_id=current_user.id,
            word=word,
            scope_analysis_id=scope_analysis_id,
            scope_input_text_id=scope_input_text_id,
            **provided,
        )
        db.add(fragment)

    db.commit()
    db.refresh(fragment)
    return fragment


@router.delete("/fragments/{word}", status_code=status.HTTP_204_NO_CONTENT)
def delete_fragment(
    word: str,
    scope_analysis_id: int | None = None,
    scope_input_text_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Deletes the entry at exactly the given scope (default: the global
    entry, matching behavior before scoping existed)."""
    fragment = db.query(Fragment).filter_by(
        user_id=current_user.id, word=word,
        scope_analysis_id=scope_analysis_id, scope_input_text_id=scope_input_text_id,
    ).first()
    if not fragment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fragment not found")
    db.delete(fragment)
    db.commit()


# Starred words — a lightweight personal bookmark ("this looks interesting,
# come back to it"), global only (see StarredWord's docstring for why it's
# not scoped like KnownWord/UserWord/Fragment). Endpoints mirror the
# Fragment ones exactly, minus scoping.
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
    which scoped user_word/fragment entry is shown - resolved analysis >
    text > global, same as the list endpoints (see UserWord/Fragment's
    scope docstrings). Omitting both shows only global entries.
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
    user_word = next(iter(_resolve_by_scope(user_word_rows, key_fn=lambda uw: uw.word).values()), None)

    fragment_rows = db.query(Fragment).filter(
        Fragment.user_id == current_user.id, Fragment.word == word,
        or_(*_scope_filter_conditions(Fragment, analysis_id, input_text_id)),
    ).all()
    fragment = next(iter(_resolve_by_scope(fragment_rows, key_fn=lambda f: f.word).values()), None)

    return WordDetail(
        word=word,
        frequency=dict_word.frequency if dict_word else None,
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
        user_word=user_word,
        fragment=fragment,
    )