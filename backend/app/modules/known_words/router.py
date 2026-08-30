from fastapi import APIRouter, Depends, HTTPException, status
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
    HskFormDetail,
    CedictSense,
    WordDetail,
    CompareSegmentationRequest,
    CompareSegmentationResponse,
    SegmentedWord,
)


router = APIRouter(prefix="/known-words", tags=["known-words"])


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
        min_token_length=request.min_token_length,
        max_token_length=request.max_token_length,
        min_token_count=request.min_token_count,
        lm_stopwords=lm_stopwords,
        tokenizer_stopwords=tokenizer_stopwords,
    )

    # Get user's known words and filter results
    known_words = service.get_known_words_for_user(current_user.id, db)
    filtered = service.filter_results(
        results,
        known_words,
        garbage_words,
        min_familiarity=request.min_familiarity_filter,
        max_familiarity=request.max_familiarity_filter,
    )

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

    return AnalysisResponse(
        analysis_id=analysis.id,
        input_text_id=input_text.id,
        title=input_text.title,
        total_words=sum(d["count"] for d in results.values()),
        unique_words=len(results),
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
    Returns every stored occurrence of `word` within analysis_id's source
    text, with `context_chars` characters of surrounding text on each side.
    Empty `occurrences` (not a 404) when the word has no stored positions -
    see AnalysisResult.positions docstring for which sources those are.
    """
    analysis = (
        db.query(Analysis)
        .join(InputText, Analysis.input_text_id == InputText.id)
        .filter(Analysis.id == analysis_id, InputText.user_id == current_user.id)
        .first()
    )
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")

    result = db.query(AnalysisResult).filter_by(analysis_id=analysis_id, word=word).first()
    if not result or not result.positions:
        return WordContextResponse(word=word, occurrences=[])

    body = analysis.input_text.body
    occurrences = [
        WordOccurrence(
            start=start,
            end=end,
            before=body[max(0, start - context_chars):start],
            match=body[start:end],
            after=body[end:end + context_chars],
        )
        for start, end in result.positions
    ]

    return WordContextResponse(word=word, occurrences=occurrences)


@router.post("/known-words", response_model=KnownWordResponse, status_code=status.HTTP_201_CREATED)
def upsert_known_word(
    update: KnownWordUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    known_word = db.query(KnownWord).filter_by(
        user_id=current_user.id, word=update.word
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
    return db.query(KnownWord).filter_by(user_id=current_user.id).all()


@router.delete("/known-words/{word}", status_code=status.HTTP_204_NO_CONTENT)
def delete_known_word(
    word: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    known_word = db.query(KnownWord).filter_by(
        user_id=current_user.id, word=word
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
    existing = db.query(UserWord).filter_by(
        user_id=current_user.id, word=user_word_in.word
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User word already exists"
        )
    user_word = UserWord(
        user_id=current_user.id,
        **user_word_in.model_dump(),
    )
    db.add(user_word)
    db.commit()
    db.refresh(user_word)
    return user_word


@router.get("/user-words", response_model=list[UserWordResponse])
def list_user_words(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.query(UserWord).filter_by(user_id=current_user.id).all()


@router.delete("/user-words/{word}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user_word(
    word: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_word = db.query(UserWord).filter_by(
        user_id=current_user.id, word=word
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
    Creates or updates a user's word entry. Only fields explicitly present
    in the request body are changed — this is what lets the word-detail
    panel save a pinyin or meaning directly without a separate "add word"
    step: filling in either field is enough to create the UserWord row.
    """
    user_word = db.query(UserWord).filter_by(
        user_id=current_user.id, word=word
    ).first()

    provided = update.model_dump(exclude_unset=True)

    if user_word:
        for field, value in provided.items():
            setattr(user_word, field, value)
    else:
        dict_word = db.query(DictionaryWord).filter_by(word=word).first()
        user_word = UserWord(
            user_id=current_user.id,
            word=word,
            dictionary_word_id=dict_word.id if dict_word else None,
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
    return db.query(InputText).filter_by(user_id=current_user.id).order_by(InputText.created_at.desc()).all()


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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.query(Fragment).filter_by(user_id=current_user.id).all()


@router.post("/fragments", response_model=FragmentResponse, status_code=status.HTTP_201_CREATED)
def create_fragment(
    fragment_in: FragmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    existing = db.query(Fragment).filter_by(
        user_id=current_user.id, word=fragment_in.word
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
    """Creates or updates a fragment note — same upsert pattern as
    /user-words/{word}: marking a fragment and annotating it are one action."""
    fragment = db.query(Fragment).filter_by(
        user_id=current_user.id, word=word
    ).first()

    if fragment:
        for field, value in update.model_dump(exclude_unset=True).items():
            setattr(fragment, field, value)
    else:
        fragment = Fragment(
            user_id=current_user.id,
            word=word,
            **update.model_dump(exclude_unset=True),
        )
        db.add(fragment)

    db.commit()
    db.refresh(fragment)
    return fragment


@router.delete("/fragments/{word}", status_code=status.HTTP_204_NO_CONTENT)
def delete_fragment(
    word: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    fragment = db.query(Fragment).filter_by(
        user_id=current_user.id, word=word
    ).first()
    if not fragment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fragment not found")
    db.delete(fragment)
    db.commit()


@router.get("/words/{word}", response_model=WordDetail)
def get_word_detail(
    word: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    dict_word = db.query(DictionaryWord).filter_by(word=word).first()

    hsk_entry = db.query(HskEntry).filter_by(simplified=word).first()
    forms = []
    if hsk_entry:
        forms = db.query(HskForm).filter_by(entry_id=hsk_entry.id).all()

    cedict_entries = db.query(CedictEntry).filter_by(simplified=word).all()

    user_word = db.query(UserWord).filter_by(
        user_id=current_user.id, word=word
    ).first()

    fragment = db.query(Fragment).filter_by(
        user_id=current_user.id, word=word
    ).first()

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