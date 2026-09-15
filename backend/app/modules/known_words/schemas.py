from typing import Literal

from pydantic import BaseModel
from datetime import datetime

# Shared by UserWord create+upsert requests: "global" (the
# default, unchanged from before scoping existed) applies everywhere; "text"
# scopes to every Analysis of the given input_text_id; "analysis" scopes to
# just the given analysis_id. See each model's scope_analysis_id/
# scope_input_text_id docstring (models.py) for the resolution priority.
ScopeChoice = Literal["global", "text", "analysis"]

# UserWord.affects_dag's three states (see its docstring, models.py):
# 'increase' boosts a word's DAG segmentation weight to a dominant ceiling,
# 'decrease' suppresses it to the same floor a totally unrecognized word
# gets (applied to every DAG edge spelling that word, regardless of which
# trie produced it - see Segmenter._word_weight, dag_segmentor.py), and
# 'neutral' expresses "no boost, no suppression" explicitly (distinct from
# NULL/"no opinion, inherit from a broader scope" - see UserWord's
# docstring). NULL is still represented as `AffectsDagChoice | None` at
# every use site, never folded into this Literal itself.
AffectsDagChoice = Literal["increase", "neutral", "decrease"]


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
    # (skipping NULL opinions, falling back to 'increase' if nothing
    # resolves) - see _resolve_user_word_detail's docstring, router.py, for
    # exactly how this differs from build_user_overlay's own
    # (text/global-only) walk. Carries the actual 3-way value (not collapsed
    # to a boolean) so 'decrease' is visually distinguishable from 'neutral'
    # in the UI, not just "boosts or doesn't" - this is specifically "what
    # actually happens during segmentation," which is always one of the
    # three (never null itself, even though a per-scope entry can be).
    userword_resolved_affects_dag: AffectsDagChoice = "increase"
    # Each scope-in-userword_scopes' OWN raw affects_dag (tri-state,
    # unresolved/uninherited) - {"global": "increase", "text": null, ...}.
    # Unlike userword_resolved_affects_dag (the one winning value), this is
    # what lets the results-table quick-action's badge fan show every
    # present scope's actual setting instead of only the winner's - see
    # _resolve_user_word_detail's docstring, router.py.
    userword_scope_affects_dag: dict[str, AffectsDagChoice | None] = {}
    # Resolved (never persisted) same as is_garbage/is_hidden - a second,
    # orthogonal dimension from `source` above: `source` answers "which
    # pipeline pass produced this row" (dag/overlay/unknown for best-guess,
    # extra_match/repeated_sequence for everything else, or a legacy
    # trie/token/longest_match_only/pre-split-ambiguous extra_match value on
    # an older row); `evidence_tier` answers "why should a user trust this
    # as a real word," resolved fresh from current UserWord/dictionary_words
    # state on every read - see service.get_word_dictionary_tiers and
    # router.py's per-endpoint resolution. Hierarchy: 'user' (an applicable
    # UserWord entry at this scope, active or not) > 'dictionary' (HSK
    # and/or CC-CEDICT backed) > 'corpus' (real corpus frequency, no
    # dictionary backing) > 'unknown'.
    evidence_tier: Literal["user", "dictionary", "corpus", "unknown"] = "unknown"


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
    best_guess_results: list[SegmentedWord]
    full_segmentation_results: list[SegmentedWord]
    # words present in one result set but not the other, for a quick diff
    only_in_best_guess: list[str]
    only_in_full_segmentation: list[str]


class WeakWord(BaseModel):
    word: str
    count: int
    effective_weight: float


class DifficultyBreakdown(BaseModel):
    """
    See app.modules.known_words.difficulty for the full model writeup.
    Resolved fresh from current KnownWord state on every read, same as
    WordResult.familiarity/is_garbage/evidence_tier - never persisted.
    """
    # 0-1 fraction (token-weighted known-coverage), not pre-formatted -
    # the frontend picks its own display scale (%, /10, ...) from this one
    # source of truth rather than carrying multiple redundant fields.
    score: float
    band: Literal["very_easy", "easy", "manageable", "difficult", "very_difficult"]
    counted_tokens: int
    known_tokens: int
    unknown_tokens: int
    # Count of distinct words whose score got a boost specifically because
    # their component characters are known, even though the word itself
    # isn't - see difficulty.compute_difficulty's docstring.
    partial_credit_words: int
    weakest_words: list[WeakWord]


class AnalysisResponse(BaseModel):
    analysis_id: int
    input_text_id: int
    title: str | None = None
    total_words: int
    unique_words: int
    results: list[WordResult]
    # None only when there are zero main-segmentation results at all (e.g.
    # an empty text) - see difficulty.compute_difficulty.
    difficulty: DifficultyBreakdown | None = None


class AnalysisSpan(BaseModel):
    """
    One span in the reading view's ordered walk of InputText.body - either
    a "word" span (a dag/overlay-sourced occurrence, from AnalysisResult.
    positions - see its docstring, models.py) or a "gap" span (everything
    else: token/unknown/longest_match_only content, whitespace,
    punctuation - rendered as plain unstyled text). Together, in order,
    spans cover the entire body with no gaps or overlaps.

    "word"-only fields mirror a subset of WordResult's own resolved
    fields (same resolution functions, not reimplemented - see
    get_analysis_spans, router.py) plus rarity_tier (not on WordResult -
    pulled from DictionaryWord the same way WordDetail does). Left null/
    default on a "gap" span.
    """
    type: Literal["word", "gap"]
    start: int
    end: int
    # "gap" only.
    text: str | None = None
    # "word" only.
    word: str | None = None
    source: str | None = None
    familiarity: int | None = None
    is_hidden: bool = False
    hidden_governing_scope: str = "default"
    rarity_tier: str | None = None
    # Raw DictionaryWord.freq_per_million, alongside rarity_tier rather than
    # instead of it - ReadingView's continuous "Color by: Rarity" gradient
    # needs the actual number (it interpolates a color from log-frequency
    # directly, not a snap to one of 5 tiers), but rarity_tier stays too
    # since spanTitle's tooltip still reads off it. Null exactly when
    # rarity_tier is (see compute_word_rarity.py - both columns are always
    # NULL/non-NULL together).
    freq_per_million: float | None = None
    userword_scopes: list[str] = []
    userword_resolved_affects_dag: AffectsDagChoice = "increase"
    # Same resolved-fresh evidence tier as WordResult.evidence_tier (see its
    # docstring) - null on a "gap" span, same nullable pattern `source`
    # already uses here, since both are only meaningful for a "word" span.
    # Powers ReadingView's "Color by: Source" mode's fallback (see
    # dictionary_source below for the finer split that mode actually uses).
    evidence_tier: Literal["user", "dictionary", "corpus", "unknown"] | None = None
    # Splits evidence_tier's "dictionary" bucket into which curated source
    # actually backs the word - reading view only (WordResult.evidence_tier,
    # and every other consumer of evidence_tier, keeps treating HSK/CC-CEDICT
    # as one undifferentiated "dictionary" tier; this is a new, additive
    # field, not a replacement). Null whenever evidence_tier isn't
    # "dictionary" (user/corpus/unknown words have no dictionary_source to
    # report) or when a word is dictionary-backed by neither HSK nor
    # CC-CEDICT specifically (shouldn't happen given how evidence_tier's own
    # "dictionary" value is derived, but nothing here assumes it can't).
    # HSK wins when a word is backed by both (get_analysis_spans, router.py)
    # - the more curated/pedagogical source, matching the priority order
    # ReadingView's "Color by: Source" mode uses top to bottom: User > HSK >
    # CC-CEDICT > Corpus > None.
    dictionary_source: Literal["hsk", "cedict"] | None = None


class AnalysisSpansResponse(BaseModel):
    analysis_id: int
    input_text_id: int
    spans: list[AnalysisSpan]


class ExportHskForm(BaseModel):
    """One HSK form, for the export's HSK column - same fields as
    HskFormDetail (below), a separate class only because it lives in a
    separate response tree (ExportWordData, not WordDetail)."""
    traditional: str | None = None
    pinyin: str | None = None
    meanings: list[str] = []
    classifiers: list[str] = []


class ExportCedictSense(BaseModel):
    """One CC-CEDICT sense, for the export's CC-CEDICT column - see
    CedictSense (below) for the WordDetail equivalent."""
    traditional: str | None = None
    pinyin: str | None = None
    definitions: list[str] = []


class ExportContext(BaseModel):
    """
    One occurrence's surrounding context, split into its three pieces
    (rather than one pre-joined string) specifically so a formatter can
    render `match` distinctly from `before`/`after` - the .xlsx export
    bolds it (a real rich-text run, not a marker character a plain string
    could carry); Pleco's plain-text field just concatenates all three,
    same as before. Each piece is independently whitespace-normalized -
    see _normalize_context_text's docstring, router.py.
    """
    before: str
    match: str
    after: str


class ExportUserEntry(BaseModel):
    """
    One UserWord entry - UNBOUNDED, every entry this word has anywhere,
    across every text/analysis the user has ever customized it in (same
    philosophy as WordDetail.user_word_entries/UserWordEntryDetail, NOT
    WordResult.userword_scopes' "just this viewing context" set). Carries
    the actual pronunciation/meaning/notes text (unlike UserWordResponse's
    use elsewhere, which only needs affects_dag for the results-table
    quick-action) plus the scope/text_id/text_title/analysis_id label data
    `_resolve_scope_context_info` already produces - the frontend builds
    its own export-specific label from these ("Global" / "Text: {title}" /
    "Analysis: {title}-{analysis_id}" - see exportUserEntryLabel, exportData.ts
    - deliberately NOT the word-detail panel's entryLabel, which has its
    own, different established wording for its own UI callers).
    """
    scope: ScopeChoice
    text_id: int | None = None
    text_title: str | None = None
    analysis_id: int | None = None
    pronunciation: str | None = None
    meaning: str | None = None
    notes: str | None = None


class ExportWordData(BaseModel):
    """One word's worth of export-time data - see get_export_data's
    docstring (router.py) for how each field is resolved."""
    word: str
    # Resolved fallback: first HSK form pinyin, else first CC-CEDICT
    # pinyin, else the closest applicable UserWord pronunciation (walking
    # analysis -> text -> global over the unbounded user_entries below),
    # else WordEnrichment.pinyin - same precedence WordSearchResult.pinyin
    # uses elsewhere in this module, plus the new auto-generated fallback.
    pinyin: str | None = None
    # "Segmentation Source" column - same 4-way hierarchy as WordResult.
    # evidence_tier (user > dictionary > corpus > unknown), with
    # dictionary_source below splitting which curated source backs a
    # "dictionary" word - same split get_analysis_spans already computes
    # for the reading view's "Color by: Source" mode.
    evidence_tier: Literal["user", "dictionary", "corpus", "unknown"]
    dictionary_source: Literal["hsk", "cedict"] | None = None
    frequency: int | None = None
    freq_per_million: float | None = None
    rarity_tier: str | None = None
    hsk_forms: list[ExportHskForm] = []
    # HSK entry-level fields (radical/frequency-rank/POS) - these existed
    # on HskEntry all along but weren't surfaced anywhere in the app until
    # now (see WordDetail's matching new fields, added in this same pass).
    hsk_radical: str | None = None
    hsk_v2_2012: int | None = None
    hsk_v3_2021: int | None = None
    hsk_v3_2026: int | None = None
    hsk_frequency: int | None = None
    hsk_pos: list[str] = []
    cedict_senses: list[ExportCedictSense] = []
    user_entries: list[ExportUserEntry] = []
    # Machine-generated (WordEnrichment) - resolved translation only
    # (google_translation ?? ctranslate2_translation ?? None), same
    # resolution _resolve_word_enrichment uses; staleness isn't meaningful
    # in an export so it isn't carried here.
    enrichment_pinyin: str | None = None
    enrichment_translation: str | None = None
    familiarity: int | None = None
    sample_sentences: list[str] = []
    # One entry per occurrence in this analysis's source text - see
    # get_export_data for the stored-positions-first, live-regex-scan-
    # fallback resolution (same fallback get_word_context uses for a word
    # with no positions).
    contexts: list[ExportContext] = []
    note: str | None = None


class ExportDataResponse(BaseModel):
    analysis_id: int
    input_text_id: int
    text_title: str | None = None
    words: list[ExportWordData] = []


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
    note: str | None = None
    body: str
    created_at: datetime
    updated_at: datetime
    analyses: list[AnalysisSummary]


class InputTextUpdate(BaseModel):
    """
    PUT /input-texts/{id} body. Only fields explicitly present in the
    request are changed - same exclude_unset convention as UserWordUpsert/
    WordVisibilityUpsert, so e.g. saving a note doesn't require resending
    the current title. `title`/`note` are each nullable (clearing either
    back to unset is a valid edit, not just setting new text).
    """
    title: str | None = None
    note: str | None = None


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


# Bulk HSK-level familiarity assignment - see bulk_assign_hsk_familiarity's
# docstring (router.py) for the actual behavior. "2021" is deliberately not
# a valid edition here - excluded by product decision (see the feature's
# own planning conversation), not an oversight.
HskEdition = Literal["2012", "2026"]


class BulkAssignHskRequest(BaseModel):
    edition: HskEdition
    level: int
    familiarity: int
    overwrite: bool = False


class BulkAssignHskResponse(BaseModel):
    matched: int
    updated: int
    skipped: int


class HskLevelCount(BaseModel):
    level: int
    word_count: int


class HskLevelCountsResponse(BaseModel):
    v2012: list[HskLevelCount]
    v2026: list[HskLevelCount]


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
    # Whether/how this entry's frequency affects DAG segmentation -
    # tri-state ('increase'/'neutral'/'decrease'), see UserWord's docstring
    # (models.py). Defaults to None ("no opinion"), NOT 'increase' - a
    # request that only sets e.g. `notes` must never silently opt this
    # entry into boosting segmentation.
    affects_dag: AffectsDagChoice | None = None
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
    # Tri-state ('increase'/'neutral'/'decrease') - see UserWord's docstring
    # (models.py). None is a real, explicit value distinct from "field
    # omitted" (handled by exclude_unset in the router) - sending
    # `"affects_dag": null` clears an existing opinion back to "inherit",
    # while omitting the key entirely leaves whatever the row already had
    # untouched.
    affects_dag: AffectsDagChoice | None = None
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
    affects_dag: AffectsDagChoice | None = None
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
    note: str | None = None
    created_at: datetime
    updated_at: datetime
    # Most recent Analysis of this text, if any - lets the input-texts list
    # page offer a "jump straight to latest results" shortcut without a
    # round trip through the text's own hub page. Computed query-time (not
    # stored), same as other summaries (see AnalysisSummary).
    latest_analysis_id: int | None = None
    # Word-count stats for that same latest analysis, so the input-texts
    # list cards can show a quick sense of a text's size/coverage without a
    # second round trip - same total_words/unique_words shape as
    # AnalysisSummary, just for the one most-recent run. None/None when
    # there's no analysis yet (mirrors latest_analysis_id being None).
    latest_analysis_total_words: int | None = None
    latest_analysis_unique_words: int | None = None
    # Same DifficultyBreakdown.score/band pair the analysis page's own chip
    # reads (difficultyColor/difficultyLabel/difficultyOutOfTen, wordDisplay.ts)
    # - just the two fields that chip actually needs, not the full
    # breakdown (weakest_words etc. have no use on a list card). None/None
    # when there's no analysis yet, or that analysis has zero counted
    # tokens (see difficulty.compute_difficulty) - same as DifficultyBreakdown
    # itself being optional on AnalysisResponse.
    latest_analysis_difficulty_score: float | None = None
    latest_analysis_difficulty_band: Literal["very_easy", "easy", "manageable", "difficult", "very_difficult"] | None = None

    model_config = {"from_attributes": True}


class StopwordCreate(BaseModel):
    word: str
    is_override: bool = False


class StopwordResponse(BaseModel):
    id: int
    word: str
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


class StarredWordResponse(BaseModel):
    id: int
    word: str

    model_config = {"from_attributes": True}


class WordNoteUpsert(BaseModel):
    """Creates or updates a word's note - empty/whitespace-only text deletes
    the row instead (see upsert_word_note's docstring, router.py)."""
    note: str


class WordNoteResponse(BaseModel):
    id: int
    word: str
    note: str

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


class UserWordEntryDetail(BaseModel):
    """
    One UserWord row, unconditionally - every entry that exists for this
    word across every scope this user has ever customized it in, not
    resolved/filtered against any particular viewing context. This is a
    different concern from UserWordResponse/the resolved fields on
    WordResult (userword_scopes/userword_resolved_affects_dag) - those
    stay exactly as they are, single-context-resolved, for the results-
    table quick-action. This shape is for the word-detail panel
    (WordDetailPanel.svelte), which shows every entry and decides
    per-entry editability client-side against whatever page it's opened
    from (see that component's isEntryEditable).
    """
    id: int
    scope: ScopeChoice
    # None for a global entry. text_id/text_title are always populated
    # together for a text-scoped entry; for an analysis-scoped entry,
    # they describe the text that analysis belongs to (an analysis-scoped
    # entry needs both to render "Analysis of <text_title>" and to know
    # which text it's under for the editability hierarchy - see
    # isEntryEditable's docstring, WordDetailPanel.svelte).
    text_id: int | None = None
    text_title: str | None = None
    analysis_id: int | None = None
    analysis_created_at: datetime | None = None
    pronunciation: str | None = None
    meaning: str | None = None
    notes: str | None = None
    affects_dag: AffectsDagChoice | None = None

    model_config = {"from_attributes": True}


class VisibilityEntryDetail(BaseModel):
    """Same shape/reasoning as UserWordEntryDetail, for WordVisibility."""
    id: int
    scope: ScopeChoice
    text_id: int | None = None
    text_title: str | None = None
    analysis_id: int | None = None
    analysis_created_at: datetime | None = None
    hidden: bool

    model_config = {"from_attributes": True}


class WordVisibilityEntry(VisibilityEntryDetail):
    """
    VisibilityEntryDetail plus the word itself - for GET /word-visibility
    (list_word_visibility, router.py), which lists every WordVisibility row
    for the user across every word, not scoped to one word the way
    get_word_detail's own visibility_entries is. Reuses the exact same
    per-entry shape so the frontend's "Hidden Words" management page can
    share wordDetailContext.ts's entryLabel/jumpLink with the word-detail
    panel instead of inventing a parallel labeling scheme.
    """
    word: str


class WordDetail(BaseModel):
    word: str
    # Resolved per-word status for the quick-action bar at the top of the
    # panel (Familiarity/Star/Garbage) - always global (see KnownWord/
    # StarredWord's docstrings, models.py) and always fully editable
    # regardless of viewing context, so no hierarchy logic applies to these
    # three, unlike user_word_entries/visibility_entries below. Included
    # here (rather than requiring the caller to have already bulk-fetched
    # listKnownWords/listStarredWords/listGarbageWords) so the panel is
    # self-sufficient from any page, including one with no such bulk state
    # of its own (e.g. the profile list pages).
    familiarity: int | None = None
    is_starred: bool = False
    is_garbage: bool = False
    frequency: int | None = None
    # Derived read-cache columns from DictionaryWord (see its docstring,
    # models.py) - both null whenever frequency is (nothing to compute a
    # tier from). Populated by scripts/compute_word_rarity.py, not live.
    freq_per_million: float | None = None
    rarity_tier: str | None = None
    hsk_v2_2012: int | None = None
    hsk_v3_2021: int | None = None
    hsk_v3_2026: int | None = None
    # Entry-level HSK fields - these existed on HskEntry all along
    # (build_dictionary.py) but weren't surfaced anywhere in the app until
    # the Excel-export work surfaced the gap. Omitted (null/empty) the same
    # "no HSK entry" way hsk_v2_2012 etc. already are.
    hsk_radical: str | None = None
    hsk_frequency: int | None = None
    hsk_pos: list[str] = []
    forms: list[HskFormDetail] = []
    # CC-CEDICT senses for this word, if any — its own source-specific
    # section, same reasoning as user_word/fragment below.
    cedict: list[CedictSense] = []
    # Every UserWord entry across the three scope levels relevant to the
    # viewing context passed as analysis_id/input_text_id (global, plus this
    # text's/this analysis's own row if applicable), most-specific first.
    # Kept for the results-table quick-action's own menu (toggleUserWordMenu/
    # buildUserWordMenu, +page.svelte), which needs exactly "what's relevant
    # here", not "everything that exists" - segmentation resolution itself
    # stays entirely in build_user_overlay/segmenter_loader.py, unrelated to
    # either list. The word-detail panel no longer uses this field - see
    # user_word_entries below for what it uses instead.
    user_words: list[UserWordResponse] = []
    # Same reasoning/consumer as user_words above, for WordVisibility - kept
    # for the results-table's own Visibility quick-action menu
    # (toggleVisibilityMenu/buildVisibilityMenu, +page.svelte).
    word_visibility: list[WordVisibilityResponse] = []
    # Independent of user_words (a word doesn't need to be in the user's
    # dictionary to have sample sentences) - see SampleSentence's docstring.
    sample_sentences: list[SampleSentenceResponse] = []
    # A word's single free-text note, if any - see WordNote's docstring,
    # models.py, for why this is its own table rather than living on
    # StarredWord. Null when no WordNote row exists (no note, not "note is
    # an empty string" - an empty note is never persisted, same as a
    # cleared KnownWord familiarity).
    note: str | None = None
    # Every UserWord row that exists for this word, across every scope this
    # user has ever customized it in - unconditional, NOT filtered/resolved
    # against analysis_id/input_text_id the way user_words above is. This is
    # what WordDetailPanel.svelte's UserWord section renders: a word can have
    # many text- or analysis-scoped entries over time (one per text/analysis
    # it's ever been customized in), not bounded at 3 - editability per entry
    # is a client-side decision (see isEntryEditable) based on whatever
    # context the panel was opened from, not something this field encodes.
    user_word_entries: list[UserWordEntryDetail] = []
    # Same reasoning/shape as user_word_entries above, for WordVisibility -
    # what WordDetailPanel.svelte's Visibility section renders.
    visibility_entries: list[VisibilityEntryDetail] = []


class WordSearchResult(BaseModel):
    """
    One row in a word-search hit list - a lightweight preview, deliberately
    NOT a second copy of WordDetail: clicking a result opens WordDetailPanel,
    which does its own full GET /words/{word} fetch (sample sentences, notes,
    every scoped UserWord/WordVisibility entry, etc. - see that endpoint's
    docstring) regardless of what this row already carried. This shape only
    needs to be enough for the hit list itself - badges plus a one-line
    preview - to help the user pick which word to open.
    """
    word: str
    # Preferred HSK form pinyin, else first CC-CEDICT pinyin, else the
    # user's own pronunciation (see get_word_search's docstring, router.py,
    # for the exact fallback order) - null only when none of the three
    # exist, e.g. a bare corpus-frequency word with no curated backing and
    # no user entry yet.
    pinyin: str | None = None
    preview_meaning: str | None = None
    hsk_v2_2012: int | None = None
    hsk_v3_2021: int | None = None
    hsk_v3_2026: int | None = None
    freq_per_million: float | None = None
    rarity_tier: str | None = None
    # Which source(s) actually back this word - dictionary_words already
    # denormalizes HSK/CC-CEDICT/corpus backing onto one row (see its
    # docstring, models.py, and build_dictionary.py), so "hsk"/"cedict"/
    # "corpus" all come off that single lookup; "user" is separate, since a
    # user's own word (e.g. a segmentation-artifact UserWord entry) doesn't
    # need any dictionary_words backing to be findable here.
    sources: list[Literal["hsk", "cedict", "corpus", "user"]] = []
    is_user_word: bool = False
    familiarity: int | None = None
    is_starred: bool = False
    is_garbage: bool = False


class WordSearchResponse(BaseModel):
    query: str
    results: list[WordSearchResult]
    # True when more candidates existed than `results` returned (capped at
    # service.search_words' limit) - lets the frontend hint "keep typing to
    # narrow this down" instead of silently presenting a partial list as
    # if it were the complete match set.
    truncated: bool = False


# Machine-generated pinyin/translation - see WordEnrichment's docstring
# (models.py) for the full storage/staleness design. `translation` is the
# already-resolved value (google_translation ?? ctranslate2_translation ??
# null) computed in service.py - the frontend never re-derives this
# precedence itself. `google_translation`/`ctranslate2_translation` are
# also both included individually (not just the resolved value) so the
# info panel can show which source backed the resolved translation, and
# offer "improve with Google" when only the ctranslate2 one exists (phase 2).
class WordEnrichmentResponse(BaseModel):
    word: str
    pinyin: str | None = None
    translation: str | None = None
    google_translation: str | None = None
    google_generated_at: datetime | None = None
    ctranslate2_translation: str | None = None
    ctranslate2_generated_at: datetime | None = None
    ctranslate2_stale: bool = False
