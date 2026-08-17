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
    notes: str | None = None
    dictionary_word_id: int | None = None
    freq_combined: int | None = None
    hsk_v2_2012: int | None = None
    hsk_v3_2021: int | None = None
    hsk_v3_2026: int | None = None


class UserWordResponse(BaseModel):
    id: int
    word: str
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