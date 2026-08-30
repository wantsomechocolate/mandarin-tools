from typing import Literal

from pydantic import BaseModel
from datetime import datetime

# Shared by KnownWord/UserWord/Fragment create+upsert requests: "global" (the
# default, unchanged from before scoping existed) applies everywhere; "text"
# scopes to every Analysis of the given input_text_id; "analysis" scopes to
# just the given analysis_id. See each model's scope_analysis_id/
# scope_input_text_id docstring (models.py) for the resolution priority.
ScopeChoice = Literal["global", "text", "analysis"]


class AnalyzeTextRequest(BaseModel):
    # Set to re-run analysis against an existing InputText (a new Analysis +
    # AnalysisResults is created under it, body is ignored). Leave unset to
    # create a new InputText from title/body, as before.
    input_text_id: int | None = None
    title: str | None = None
    body: str | None = None
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
    # Display-time flag only (see GarbageWord/filter_results) - garbage words
    # are persisted and returned like every other word, never excluded, so
    # the analysis results stay a faithful representation of the full text.
    is_garbage: bool = False


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
    analysis_id: int
    input_text_id: int
    title: str | None = None
    total_words: int
    unique_words: int
    results: list[WordResult]


class AnalysisSummary(BaseModel):
    """One entry in an input text's list of past analysis runs."""
    id: int
    created_at: datetime
    total_words: int
    unique_words: int
    min_token_length: int
    max_token_length: int
    min_token_count: int
    min_familiarity_filter: int
    max_familiarity_filter: int


class InputTextDetailResponse(BaseModel):
    id: int
    title: str | None = None
    body: str
    created_at: datetime
    updated_at: datetime
    analyses: list[AnalysisSummary]


class WordOccurrence(BaseModel):
    start: int
    end: int
    before: str
    match: str
    after: str


class WordContextResponse(BaseModel):
    word: str
    # Empty when the word has no stored positions (e.g. it was only found by
    # the tokenizer or longest-matching passes, which have no natural
    # per-occurrence span - see AnalysisResult.positions docstring).
    occurrences: list[WordOccurrence]


class KnownWordUpdate(BaseModel):
    # Always global - see KnownWord's docstring (models.py).
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
    analysis_id: int | None = None
    input_text_id: int | None = None
    scope: ScopeChoice = "global"


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
    analysis_id: int | None = None
    input_text_id: int | None = None
    scope: ScopeChoice = "global"


class UserWordResponse(BaseModel):
    id: int
    word: str
    pronunciation: str | None = None
    meaning: str | None = None
    notes: str | None = None
    dictionary_word_id: int | None = None
    scope_analysis_id: int | None = None
    scope_input_text_id: int | None = None
    # Informational only - see UserWord's docstring (models.py).
    created_from_analysis_id: int | None = None
    created_from_input_text_id: int | None = None

    model_config = {"from_attributes": True}



class InputTextResponse(BaseModel):
    id: int
    title: str | None = None
    created_at: datetime
    updated_at: datetime
    # Most recent Analysis of this text, if any - lets the input-texts list
    # page offer a "jump straight to latest results" shortcut without a
    # round trip through the text's own hub page. Computed query-time (not
    # stored), same as other summaries (see AnalysisSummary).
    latest_analysis_id: int | None = None

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
    analysis_id: int | None = None
    input_text_id: int | None = None
    scope: ScopeChoice = "global"


class FragmentUpsert(BaseModel):
    """Partial update, same upsert pattern as UserWordUpsert — marking a
    fragment and annotating it with a note are the same action."""
    note: str | None = None
    analysis_id: int | None = None
    input_text_id: int | None = None
    scope: ScopeChoice = "global"


class FragmentResponse(BaseModel):
    id: int
    word: str
    note: str | None = None
    scope_analysis_id: int | None = None
    scope_input_text_id: int | None = None

    model_config = {"from_attributes": True}


class StarredWordCreate(BaseModel):
    word: str
    note: str | None = None


class StarredWordUpsert(BaseModel):
    """Partial update, same upsert pattern as FragmentUpsert."""
    note: str | None = None


class StarredWordResponse(BaseModel):
    id: int
    word: str
    note: str | None = None

    model_config = {"from_attributes": True}


class SampleSentenceCreate(BaseModel):
    word: str
    sentence: str


class SampleSentenceResponse(BaseModel):
    id: int
    word: str
    sentence: str

    model_config = {"from_attributes": True}


class HskFormDetail(BaseModel):
    traditional: str | None = None
    pinyin: str | None = None
    meanings: list[str] = []
    classifiers: list[str] = []

    model_config = {"from_attributes": True}


class CedictSense(BaseModel):
    """One CC-CEDICT line for this word — a word can have several (different
    pronunciations/meanings), each its own sense, the same way HskFormDetail
    can repeat for one HskEntry."""
    traditional: str | None = None
    pinyin: str | None = None
    definitions: list[str] = []

    model_config = {"from_attributes": True}


class WordDetail(BaseModel):
    word: str
    frequency: int | None = None
    hsk_v2_2012: int | None = None
    hsk_v3_2021: int | None = None
    hsk_v3_2026: int | None = None
    forms: list[HskFormDetail] = []
    # CC-CEDICT senses for this word, if any — its own source-specific
    # section, same reasoning as user_word/fragment below.
    cedict: list[CedictSense] = []
    # The current user's own entry for this word, if they have one. Kept as
    # its own section rather than merged into the fields above — this is the
    # first of what should eventually be several source-specific sections
    # (see notes on the planned Pleco-style multi-source panel).
    user_word: UserWordResponse | None = None
    # Present if the user has flagged this word as a fragment (a segmentation
    # artifact worth noting but not studying) — see Fragment model docstring
    # for why this is kept fully separate from user_word.
    fragment: FragmentResponse | None = None
    # Independent of user_word (a word doesn't need to be in the user's
    # dictionary to have sample sentences) - see SampleSentence's docstring.
    sample_sentences: list[SampleSentenceResponse] = []