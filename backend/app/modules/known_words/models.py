from sqlalchemy import ARRAY, BigInteger, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, SmallInteger, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from datetime import datetime
from app.models.user import User

class WordFrequency(Base):
    __tablename__ = "word_frequencies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    word: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    blog: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    literature: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    news: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    tech: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    weibo: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    combined: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    calc_combined: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    frequency: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class HskEntry(Base):
    __tablename__ = "hsk_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    simplified: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    radical: Mapped[str | None] = mapped_column(String, nullable=True)
    hsk_v2_2012: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    hsk_v3_2021: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    hsk_v3_2026: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    hsk_frequency: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pos: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)

    forms: Mapped[list["HskForm"]] = relationship("HskForm", back_populates="entry", cascade="all, delete-orphan")


class HskForm(Base):
    __tablename__ = "hsk_forms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[int] = mapped_column(Integer, ForeignKey("hsk_entries.id"), nullable=False, index=True)
    traditional: Mapped[str | None] = mapped_column(String, nullable=True)
    pinyin: Mapped[str | None] = mapped_column(String, nullable=True)
    numeric_transcription: Mapped[str | None] = mapped_column(String, nullable=True)
    meanings: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    classifiers: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)

    entry: Mapped["HskEntry"] = relationship("HskEntry", back_populates="forms")


class CedictEntry(Base):
    """
    One row per CC-CEDICT line (backend/assets/cc-cedict/cedict_ts.u8).
    `simplified` is deliberately NOT unique - a given simplified word can have
    multiple pronunciations/senses (e.g. 差 has 3 lines: cha1/cha4/chai1), each
    its own row here, the same way HskEntry/HskForm split entry from form -
    just flatter, since CC-CEDICT has no natural entry-level grouping beyond
    the simplified string itself.
    """
    __tablename__ = "cedict_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    simplified: Mapped[str] = mapped_column(String, nullable=False, index=True)
    traditional: Mapped[str | None] = mapped_column(String, nullable=True)
    pinyin: Mapped[str | None] = mapped_column(String, nullable=True)  # diacritic form, e.g. "chà"
    pinyin_numeric: Mapped[str | None] = mapped_column(String, nullable=True)  # raw CC-CEDICT form, e.g. "cha4"
    definitions: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)


class SegmentationAffix(Base):
    """
    Tuning data for the DAG segmenter's affix discount (see dag_segmentor.py's
    DEFAULT_SUFFIX_DISCOUNTS/DEFAULT_PREFIX_DISCOUNTS and Segmenter._affix_discount).
    A word strictly longer than `affix` and ending (position="suffix") or
    starting (position="prefix") with it has its score discounted by
    `discount`, so a rare compound like 森林里 doesn't out-score splitting
    into its stem + a generic locative/directional character just because
    that character is extremely common on its own.

    Rows here are loaded once at Segmenter build time and merged on top of
    the code-level defaults (same affix+position overrides the default's
    discount; a new affix adds to the list) - this is system-wide tuning
    data, not a per-user table, same as word_frequencies/dictionary_words.
    """
    __tablename__ = "segmentation_affixes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    affix: Mapped[str] = mapped_column(String, nullable=False)
    position: Mapped[str] = mapped_column(String, nullable=False)  # "prefix" or "suffix"
    discount: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        Index("ix_segmentation_affixes_affix_position", "affix", "position", unique=True),
        CheckConstraint("position IN ('prefix', 'suffix')", name="ck_segmentation_affixes_position"),
        CheckConstraint("discount > 0 AND discount <= 1", name="ck_segmentation_affixes_discount"),
    )


class SegmentationAffixExemption(Base):
    """
    Word-level escape hatch for SegmentationAffix: a word listed here is
    never discounted, regardless of any affix rule that would otherwise
    match it. Kept as its own table rather than an is_override flag on
    SegmentationAffix (the Stopword/GarbageWord pattern) because the general
    rule operates on characters (里) while an exemption has to operate on a
    whole word (这里) - different granularity, so it doesn't fit the same
    row shape.
    """
    __tablename__ = "segmentation_affix_exemptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    word: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    note: Mapped[str | None] = mapped_column(String, nullable=True)


class DictionaryWord(Base):
    """
    freq_per_million/rarity_tier are both derived, persisted read-cache
    columns - computed by scripts/compute_word_rarity.py from `frequency`
    (freq_per_million = frequency / total corpus frequency * 1_000_000,
    same total definition as Segmenter.total/segmenter_loader.py's freq_dict
    sum), not maintained live. Both stay NULL for any row with no usable
    frequency (NULL or 0) - there's nothing to compute a tier from, so NULL
    correctly means "no data," same reasoning as `frequency` itself being
    nullable. rarity_tier's 5 values and their occurrences-per-million
    cutoffs (extremely_rare < 0.03, rare 0.03-1, uncommon 1-50, common
    50-2250, extremely_common >= 2250) were chosen by
    scripts/analyze_word_rarity.py's log-frequency distribution analysis,
    cross-checked against HSK levels - see that script's docstring for the
    reasoning, not repeated here.
    """
    __tablename__ = "dictionary_words"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    word: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    frequency: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    hsk_v2_2012: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    hsk_v3_2021: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    hsk_v3_2026: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    freq_per_million: Mapped[float | None] = mapped_column(Float, nullable=True)
    rarity_tier: Mapped[str | None] = mapped_column(String, nullable=True)
    # Whether this word has a CC-CEDICT entry - set from build_dictionary.py's
    # CEDICT join (ce.simplified IS NOT NULL), not maintained live. Needed
    # so evidence-tier resolution (service.get_word_dictionary_tiers) can
    # check CEDICT backing per-word without a live join on every results
    # view - see build_dictionary.py's docstring for how this is populated.
    is_cedict: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    # Relationships
    #user_words: Mapped[list["UserWord"]] = relationship("UserWord", back_populates="dictionary_word")
    #known_words: Mapped[list["KnownWord"]] = relationship("KnownWord", back_populates="dictionary_word")

    __table_args__ = (
        CheckConstraint(
            "rarity_tier IN ('extremely_rare', 'rare', 'uncommon', 'common', 'extremely_common')",
            name="ck_dictionary_words_rarity_tier",
        ),
    )


class UserWord(Base):
    """
    Scoping (scope_analysis_id/scope_input_text_id): both NULL (the default)
    means this entry is global - applies to every analysis, exactly like
    before this column existed. Setting scope_analysis_id restricts it to
    one specific Analysis; setting scope_input_text_id restricts it to every
    Analysis of one InputText. At most one of the two is ever set (see the
    CHECK constraint) - "scope to this analysis" and "scope to this text"
    are alternative choices, not stackable.

    Resolution when several entries exist for the same word: an
    analysis-scoped entry wins over an input-text-scoped entry, which wins
    over the global entry - see service.py's build_user_overlay docstring.
    KnownWord (familiarity) does NOT use this scoping - see its own
    docstring for why. Scoping is what makes it possible to try a custom
    dictionary word (which
    feeds straight into DAG segmentation via the per-request UserOverlay -
    see dag_segmentor.py) against just one text without it silently
    affecting every other analysis.

    affects_dag: whether this entry's frequency boosts DAG segmentation at
    all - tri-state (NULL/true/false), NOT a plain boolean. NULL means "no
    opinion at this scope, inherit from the next broader scope" - this is
    the field's default for newly-created rows, deliberately not `true`:
    a UserWord row created purely to hold a note (pronunciation/meaning/
    notes worth keeping) has no opinion on segmentation weight, and
    silently defaulting that to `true` would let a note-only row override
    a broader scope's explicit `affects_dag = false` without the user ever
    touching this setting. `true`/`false` are explicit opinions - see
    build_user_overlay (segmenter_loader.py) for exactly how the
    resolution walk treats a NULL row as "keep walking to the next
    broader scope" (distinct from "no row exists here" but functionally
    the same outcome), only falling back to a hardcoded `true` default if
    every scope has neither a row nor a non-NULL opinion. This absorbed
    the old, now-removed Fragment concept: a word that's a genuine word in
    one text but a segmentation artifact in another is a single UserWord
    row with affects_dag=false at whatever scope it's an artifact in. Note
    this can only ever have an observable effect at global or text scope:
    an analysis-scoped row can't influence segmentation, since the
    analysis it's scoped to has already finished segmenting by the time
    such a row could exist (build_user_overlay never resolves
    analysis-scoped rows at all, for exactly this reason) - the UI hides
    the toggle for analysis-scoped entries accordingly.

    Existing rows from before this field became nullable were left exactly
    as they were (no backfill to NULL) - every row that already held an
    explicit true/false keeps meaning exactly that; nullability only
    changes what happens for rows created going forward that intentionally
    leave this field untouched.

    created_from_analysis_id/created_from_input_text_id are purely
    informational (never used for resolution) - they remember where an
    entry was first added from even if it ends up global, so "global word X
    was originally added while reading text Y" stays answerable.
    """
    __tablename__ = "user_words"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    word: Mapped[str] = mapped_column(String, nullable=False, index=True)

    # If this is an override of a dictionary word, link to it
    dictionary_word_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("dictionary_words.id"), nullable=True, index=True)

    # Full copy of dictionary fields, user can override any of these
    freq_combined: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    hsk_v2_2012: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    hsk_v3_2021: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    hsk_v3_2026: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    # User supplied fields
    pronunciation: Mapped[str | None] = mapped_column(String, nullable=True)
    meaning: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)

    # See class docstring's affects_dag paragraph - tri-state, NULL is a
    # real, distinct value ("no opinion"), not just "unset."
    affects_dag: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)

    # See class docstring - at most one of these two is ever set.
    scope_analysis_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("analyses.id"), nullable=True, index=True)
    scope_input_text_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("input_texts.id"), nullable=True, index=True)

    # Informational only - see class docstring.
    created_from_analysis_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("analyses.id"), nullable=True)
    created_from_input_text_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("input_texts.id"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user: Mapped["User"] = relationship("User")
    dictionary_word: Mapped["DictionaryWord | None"] = relationship("DictionaryWord")
    #dictionary_word: Mapped["DictionaryWord | None"] = relationship("DictionaryWord", back_populates="user_words")
    #known_words: Mapped[list["KnownWord"]] = relationship("KnownWord", back_populates="user_word")

    __table_args__ = (
        # A user can only have one entry per (word, scope) combination - the
        # NULLS NOT DISTINCT is what makes "at most one global entry per
        # word" actually enforceable, since a plain unique index treats
        # every NULL pair as distinct and would silently allow duplicate
        # global rows otherwise.
        Index(
            "ix_user_words_user_word_scope", "user_id", "word", "scope_analysis_id", "scope_input_text_id",
            unique=True, postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "scope_analysis_id IS NULL OR scope_input_text_id IS NULL",
            name="ck_user_words_scope_mutually_exclusive",
        ),
    )


class WordVisibility(Base):
    """
    Whether a word should be hidden from analysis results - deliberately
    its own table, not a column on UserWord: a word can be hidden with
    zero interest in pronunciation/meaning/notes/affects_dag (e.g. 的, 了,
    是), and forcing an empty UserWord row to exist just to carry one
    boolean would make "has a UserWord row" stop reliably meaning "has
    customized dictionary info," which the results table's +Add word/
    Added button already relies on (see `userWords`/`userWordAffectsDag`
    in +page.svelte).

    Same scope_analysis_id/scope_input_text_id columns, mutual-exclusion
    CHECK, and analysis > text > global resolution priority as UserWord -
    see that model's docstring for the full scoping design. Reuses
    router.py's _resolve_scope_columns/_scope_filter_conditions/
    _resolve_by_scope helpers for CRUD and resolution rather than
    reimplementing them.

    Unlike UserWord.affects_dag, `hidden` is a plain NOT NULL boolean, no
    tri-state needed: this table's only reason to exist at a given scope
    is to express an opinion on this one field, so a row's mere presence
    already means "opinion" - there's no "row exists to hold other data
    but has no opinion on this field" case the way affects_dag has to
    handle on UserWord. Absence of a row at a scope IS the "no opinion,
    inherit from the next broader scope" state; resolution is simply the
    first row found walking analysis -> text -> global, defaulting to
    hidden=false if no row exists at any scope.
    """
    __tablename__ = "word_visibility"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    word: Mapped[str] = mapped_column(String, nullable=False, index=True)
    hidden: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # See class docstring - at most one of these two is ever set, same as
    # UserWord.
    scope_analysis_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("analyses.id"), nullable=True, index=True)
    scope_input_text_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("input_texts.id"), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship("User")

    __table_args__ = (
        # Same NULLS NOT DISTINCT reasoning as UserWord's matching index -
        # without it, a plain unique index would treat every NULL/NULL
        # (global) pair as distinct and allow duplicate global rows.
        Index(
            "ix_word_visibility_user_word_scope", "user_id", "word", "scope_analysis_id", "scope_input_text_id",
            unique=True, postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "scope_analysis_id IS NULL OR scope_input_text_id IS NULL",
            name="ck_word_visibility_scope_mutually_exclusive",
        ),
    )


class SampleSentence(Base):
    """
    A sample sentence for a word - deliberately independent of UserWord (an
    earlier version attached sentences to a UserWord row, requiring a word
    to be "in your dictionary" before it could have sample sentences; that
    was reversed once real usage showed sentences are wanted for words that
    aren't necessarily UserWords too). A word can have many of these. Global
    only, no scoping - same shape/reasoning as StarredWord, just list-typed
    (many rows per word) instead of upsert-typed (one row per word).
    """
    __tablename__ = "sample_sentences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    word: Mapped[str] = mapped_column(String, nullable=False, index=True)
    sentence: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship("User")

    __table_args__ = (
        Index("ix_sample_sentences_user_word", "user_id", "word"),
    )


class KnownWord(Base):
    """
    Familiarity score for a word - deliberately always global, unlike
    UserWord. This was scoped for a while (scope_analysis_id/
    scope_input_text_id, same design as UserWord) but that was reversed:
    familiarity was never meant to vary by text/analysis - "how well do I
    know this word" isn't a per-text question the way "should this count
    toward this text's vocabulary, and should it boost segmentation here"
    (UserWord/affects_dag) is.
    """
    __tablename__ = "known_words"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    word: Mapped[str] = mapped_column(String, nullable=False)
    familiarity: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship("User")

    __table_args__ = (
        Index("ix_known_words_user_word", "user_id", "word", unique=True),
        CheckConstraint(
            "familiarity IS NULL OR (familiarity >= 1 AND familiarity <= 5)",
            name="ck_known_words_familiarity"
        ),
    )


class GarbageWord(Base):
    __tablename__ = "garbage_words"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    word: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    is_override: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped["User | None"] = relationship("User")

    __table_args__ = (
        Index("ix_garbage_words_user_word", "user_id", "word", unique=True),
    )


class StarredWord(Base):
    """
    A word/phrase the user has flagged as interesting or worth remembering -
    word + optional note, no system-wide/is_override concept (the
    GarbageWord pattern) - this is purely personal, there's no "starred by
    default for everyone" notion.

    Deliberately global only, no scope_analysis_id/scope_input_text_id like
    KnownWord/UserWord have - starring something is a lightweight personal
    bookmark, not tied to segmentation or a particular reading session, so
    scoping it wasn't asked for and isn't built here.
    """
    __tablename__ = "starred_words"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    word: Mapped[str] = mapped_column(String, nullable=False)
    note: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship("User")

    __table_args__ = (
        Index("ix_starred_words_user_word", "user_id", "word", unique=True),
    )


class Stopword(Base):
    """
    One unified list, not one per algorithm - both the DAG (Segmenter.
    build_dag) and the tokenizer's repeated-sequence scan consult the same
    set (see service.get_user_stopwords/DEFAULT_STOPWORDS). Previously
    split by `algo_type` ("longest_match"/"tokenization"), each algorithm
    only seeing its own half - dropped once every consumer needed the same
    list anyway and the split only ever meant a stopword added for one
    algorithm silently didn't apply to the other.
    """
    __tablename__ = "stopwords"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    word: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    is_override: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped["User | None"] = relationship("User")

    __table_args__ = (
        Index("ix_stopwords_user_word", "user_id", "word", unique=True),
    )


class InputText(Base):
    __tablename__ = "input_texts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    body: Mapped[str] = mapped_column(String, nullable=False)
    image: Mapped[str | None] = mapped_column(String, nullable=True)  # path or URL, populated later

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship("User")
    # One input text can have many analysis runs (e.g. re-run after
    # configuration changes) - see Analysis docstring.
    analyses: Mapped[list["Analysis"]] = relationship(
        "Analysis", back_populates="input_text", cascade="all, delete-orphan"
    )


class Analysis(Base):
    """
    One run of the analysis pipeline over an InputText's body. Deliberately
    its own entity (not folded into InputText or AnalysisResult) so the same
    source text can be analyzed multiple times - e.g. after segmentation
    config changes - with each run's parameters and results kept distinct
    and independently viewable. Comparing runs against each other is out of
    scope for now; this just makes multiple runs possible/visible.
    """
    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    input_text_id: Mapped[int] = mapped_column(Integer, ForeignKey("input_texts.id"), nullable=False, index=True)

    # Snapshot of the config this run used - persisted (not just accepted as
    # transient request params) so future runs with different config are
    # distinguishable from this one.
    min_token_length: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    max_token_length: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    min_token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    min_familiarity_filter: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    max_familiarity_filter: Mapped[int] = mapped_column(Integer, nullable=False, default=5)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    input_text: Mapped["InputText"] = relationship("InputText", back_populates="analyses")
    results: Mapped[list["AnalysisResult"]] = relationship(
        "AnalysisResult", back_populates="analysis", cascade="all, delete-orphan"
    )


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    analysis_id: Mapped[int] = mapped_column(Integer, ForeignKey("analyses.id"), nullable=False, index=True)
    word: Mapped[str] = mapped_column(String, nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)  # "dag", "overlay", "unknown", "extra_match" (going forward), or a legacy "trie"/"token"/"longest_match_only" value on a pre-retirement row (see ck_analysis_results_source - kept in the allowed set, never backfilled)
    # [[start, end], ...] character offsets into the parent InputText.body,
    # exclusive end, one pair per occurrence - powers "show this word in
    # context" without re-running segmentation. Only populated for
    # dag/overlay-sourced words: the tokenizer's unknown-sequence scan finds
    # overlapping substrings rather than a disjoint segmentation, so it has
    # no natural per-occurrence span the way Segmenter.segment()'s ordered
    # walk does (see aggregate_segments in dag_segmentor.py). Words sourced
    # only from token/longest_match_only simply have positions=None here.
    positions: Mapped[list[list[int]] | None] = mapped_column(JSONB, nullable=True)

    analysis: Mapped["Analysis"] = relationship("Analysis", back_populates="results")

    __table_args__ = (
        Index("ix_analysis_results_analysis_word", "analysis_id", "word", unique=True),
        CheckConstraint(
            "source IN ('trie', 'token', 'unknown', 'dag', 'overlay', 'longest_match_only', 'extra_match')",
            name="ck_analysis_results_source",
        ),
    )