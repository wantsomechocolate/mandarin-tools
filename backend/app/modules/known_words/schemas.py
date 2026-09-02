from typing import Literal

from pydantic import BaseModel
from datetime import datetime

# Shared by UserWord create+upsert requests: "global" (the
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
    # Resolved (never persisted) same as is_garbage - see WordVisibility's
    # docstring (models.py) and router.py's _resolve_word_visibility for how
    # this is computed fresh on every read, walking analysis > text > global.
    is_hidden: bool = False
    # Which scope produced is_hidden's value - "global"/"text"/"analysis",
    # or "default" if no WordVisibility row applies anywhere (is_hidden is
    # then always False). Drives the results-table quick-action's corner
    # scope badge and the menu-building logic client-side.
    hidden_governing_scope: str = "default"
    # Resolved (never persisted), same pattern as is_garbage/is_hidden -
    # whether this word has an applicable UserWord row (any scope relevant
    # to this viewing context - see router.py's _resolve_user_word_detail).
    # Existence-based like WordVisibility, not tri-state like affects_dag -
    # there's no separate per-row opinion to resolve here, just "is this
    # word in the user's dictionary."
    is_user_word: bool = False
    # Which of "global"/"text"/"analysis" currently have a UserWord row for
    # this word, in the context of this analysis - canonical order, 0-3
    # entries. Unlike is_hidden's single hidden_governing_scope, UserWord
    # entries coexist rather than cascading (see UserWord's docstring,
    # models.py), so this can't collapse to one governing scope - the
    # results-table quick-action renders one badge per entry present here.
    userword_scopes: list[str] = []
    # The winning entry's affects_dag, resolved analysis > text > global
    # (skipping NULL opinions, falling back to True if nothing resolves) -
    # see _resolve_user_word_detail's docstring, router.py, for exactly how
    # this differs from build_user_overlay's own (text/global-only) walk.
    # Already collapsed to plain true/false, never null - this is
    # specifically "what actually happens during segmentation," which is
    # always one of those two.
    userword_resolved_affects_dag: bool = True
    # Each scope-in-userword_scopes' OWN raw affects_dag (tri-state,
    # unresolved/uninherited) - {"global": true, "text": null, ...}. Unlike
    # userword_resolved_affects_dag (the one winning value), this is what
    # lets the results-table quick-action's badge fan show every present
    # scope's actual setting instead of only the winner's - see
    # _resolve_user_word_detail's docstring, router.py.
    userword_scope_affects_dag: dict[str, bool | None] = {}


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
    # Whether this entry's frequency boosts DAG segmentation - tri-state,
    # see UserWord's docstring (models.py). Defaults to None ("no opinion"),
    # NOT True - a request that only sets e.g. `notes` must never silently
    # opt this entry into boosting segmentation.
    affects_dag: bool | None = None
    analysis_id: int | None = None
    input_text_id: int | None = None
    scope: ScopeChoice = "global"


class UserWordUpsert(BaseModel):
    """
    Partial update used by the word-detail panel: any field left unset is
    left untouched on an existing row, and the row is created if it doesn't
    exist yet — filling in a pronunciation or meaning is enough to make a
    word a UserWord, no separate "add" step required. affects_dag follows
    the same exclude-unset rule as every other field here - omit it to
    leave an existing row's segmentation-boost setting untouched (on an
    existing row), or to leave it at its NULL "no opinion" default (on a
    newly-created row) - never send `true` just because the field was
    merely absent from the request.
    """
    pronunciation: str | None = None
    meaning: str | None = None
    notes: str | None = None
    # Tri-state - see UserWord's docstring (models.py). None is a real,
    # explicit value distinct from "field omitted" (handled by
    # exclude_unset in the router) - sending `"affects_dag": null` clears an
    # existing opinion back to "inherit", while omitting the key entirely
    # leaves whatever the row already had untouched.
    affects_dag: bool | None = None
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
    affects_dag: bool | None = None
    scope_analysis_id: int | None = None
    scope_input_text_id: int | None = None
    # Informational only - see UserWord's docstring (models.py).
    created_from_analysis_id: int | None = None
    created_from_input_text_id: int | None = None
    # Only populated by GET /user-words?all_scopes=true (see list_user_words,
    # router.py) - the title of whatever InputText this row is ultimately
    # scoped under (directly for a text-scoped row, via its Analysis for an
    # analysis-scoped row), None for a global row or for the normal
    # resolved-view list mode. Lets the "all your user words" management
    # view label/link scoped rows without a second round trip per row.
    input_text_title: str | None = None

    model_config = {"from_attributes": True}


class WordVisibilityUpsert(BaseModel):
    """
    Sets hidden=True/False at the given scope - create-or-update, same
    upsert pattern as UserWordUpsert/StarredWordUpsert. Simpler than
    UserWordUpsert: WordVisibility has exactly one meaningful field (see
    its docstring, models.py), so there's no partial-update/exclude_unset
    nuance here - `hidden` is always required and always written.
    """
    hidden: bool
    analysis_id: int | None = None
    input_text_id: int | None = None
    scope: ScopeChoice = "global"


class WordVisibilityResponse(BaseModel):
    id: int
    word: str
    hidden: bool
    scope_analysis_id: int | None = None
    scope_input_text_id: int | None = None

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


class StarredWordCreate(BaseModel):
    word: str
    note: str | None = None


class StarredWordUpsert(BaseModel):
    """Partial update, same upsert pattern as UserWordUpsert."""
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
    # Derived read-cache columns from DictionaryWord (see its docstring,
    # models.py) - both null whenever frequency is (nothing to compute a
    # tier from). Populated by scripts/compute_word_rarity.py, not live.
    freq_per_million: float | None = None
    rarity_tier: str | None = None
    hsk_v2_2012: int | None = None
    hsk_v3_2021: int | None = None
    hsk_v3_2026: int | None = None
    forms: list[HskFormDetail] = []
    # CC-CEDICT senses for this word, if any — its own source-specific
    # section, same reasoning as user_word/fragment below.
    cedict: list[CedictSense] = []
    # Every UserWord entry across the three scope levels relevant to the
    # current viewing context (global, plus this text's/this analysis's own
    # row if applicable), most-specific first. Deliberately NOT resolved to
    # one - a word can have several simultaneous entries (e.g. a global one
    # plus a one-off override for a specific text) and none should ever be
    # hidden just because a more-specific one exists. This is a display-only
    # list: segmentation resolution stays entirely in
    # build_user_overlay/segmenter_loader.py, which picks exactly one
    # entry's weight per its own unrelated priority logic - this field must
    # never be read as if it were that resolution.
    user_words: list[UserWordResponse] = []
    # Same multi-entry, most-specific-first, never-resolved-to-one shape as
    # user_words above, for the exact same reason - the panel's Visibility
    # section shows every applicable scope's row independently (see
    # WordVisibility's docstring, models.py). Independent of user_words -
    # a word can be hidden with no UserWord row at all, and vice versa.
    word_visibility: list[WordVisibilityResponse] = []
    # Independent of user_words (a word doesn't need to be in the user's
    # dictionary to have sample sentences) - see SampleSentence's docstring.
    sample_sentences: list[SampleSentenceResponse] = []