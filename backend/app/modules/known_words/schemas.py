from pydantic import BaseModel
from datetime import datetime


class AnalyzeTextRequest(BaseModel):
    title: str | None = None
    body: str
    min_token_length: int = 2
    max_token_length: int = 20
    min_token_count: int = 2
    min_familiarity_filter: int = 4
    max_familiarity_filter: int = 5


class WordResult(BaseModel):
    word: str
    count: int
    source: str
    familiarity: int | None = None


class CompareSegmentationRequest(BaseModel):
    body: str
    use_user_overlay: bool = True
    min_token_length: int = 2
    max_token_length: int = 20
    min_token_count: int = 2


class SegmentedWord(BaseModel):
    word: str
    count: int
    source: str


class CompareSegmentationResponse(BaseModel):
    body: str
    longest_match_results: list[SegmentedWord]
    dag_results: list[SegmentedWord]
    # words present in one result set but not the other, for a quick diff
    only_in_longest_match: list[str]
    only_in_dag: list[str]


class AnalysisResponse(BaseModel):
    input_text_id: int
    title: str | None = None
    total_words: int
    unique_words: int
    results: list[WordResult]


class KnownWordUpdate(BaseModel):
    word: str
    familiarity: int | None = None


class KnownWordResponse(BaseModel):
    id: int
    word: str
    familiarity: int | None = None

    model_config = {"from_attributes": True}


class UserWordCreate(BaseModel):
    word: str
    pronunciation: str | None = None
    meaning: str | None = None
    notes: str | None = None
    dictionary_word_id: int | None = None
    freq_combined: int | None = None
    hsk_v2_2012: int | None = None
    hsk_v3_2021: int | None = None
    hsk_v3_2026: int | None = None


class UserWordUpsert(BaseModel):
    """
    Partial update used by the word-detail panel: any field left unset is
    left untouched on an existing row, and the row is created if it doesn't
    exist yet — filling in a pronunciation or meaning is enough to make a
    word a UserWord, no separate "add" step required.
    """
    pronunciation: str | None = None
    meaning: str | None = None
    notes: str | None = None


class UserWordResponse(BaseModel):
    id: int
    word: str
    pronunciation: str | None = None
    meaning: str | None = None
    notes: str | None = None
    dictionary_word_id: int | None = None

    model_config = {"from_attributes": True}



class InputTextResponse(BaseModel):
    id: int
    title: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class StopwordCreate(BaseModel):
    word: str
    algo_type: str  # "longest_match" or "tokenization"
    is_override: bool = False


class StopwordResponse(BaseModel):
    id: int
    word: str
    algo_type: str
    is_override: bool
    user_id: int | None = None

    model_config = {"from_attributes": True}


class GarbageWordCreate(BaseModel):
    word: str
    is_override: bool = False


class GarbageWordResponse(BaseModel):
    id: int
    word: str
    is_override: bool
    user_id: int | None = None

    model_config = {"from_attributes": True}


class FragmentCreate(BaseModel):
    word: str
    note: str | None = None


class FragmentUpsert(BaseModel):
    """Partial update, same upsert pattern as UserWordUpsert — marking a
    fragment and annotating it with a note are the same action."""
    note: str | None = None


class FragmentResponse(BaseModel):
    id: int
    word: str
    note: str | None = None

    model_config = {"from_attributes": True}


class HskFormDetail(BaseModel):
    traditional: str | None = None
    pinyin: str | None = None
    meanings: list[str] = []
    classifiers: list[str] = []

    model_config = {"from_attributes": True}


class WordDetail(BaseModel):
    word: str
    frequency: int | None = None
    hsk_v2_2012: int | None = None
    hsk_v3_2021: int | None = None
    hsk_v3_2026: int | None = None
    forms: list[HskFormDetail] = []
    # The current user's own entry for this word, if they have one. Kept as
    # its own section rather than merged into the fields above — this is the
    # first of what should eventually be several source-specific sections
    # (see notes on the planned Pleco-style multi-source panel).
    user_word: UserWordResponse | None = None
    # Present if the user has flagged this word as a fragment (a segmentation
    # artifact worth noting but not studying) — see Fragment model docstring
    # for why this is kept fully separate from user_word.
    fragment: FragmentResponse | None = None