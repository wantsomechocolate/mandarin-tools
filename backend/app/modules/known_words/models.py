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
    __tablename__ = "dictionary_words"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    word: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    frequency: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    hsk_v2_2012: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    hsk_v3_2021: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    hsk_v3_2026: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    # Relationships
    #user_words: Mapped[list["UserWord"]] = relationship("UserWord", back_populates="dictionary_word")
    #known_words: Mapped[list["KnownWord"]] = relationship("KnownWord", back_populates="dictionary_word")


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
    over the global entry - see service.py's build_user_overlay docstring,
    and Fragment's docstring for the identical priority applied there.
    KnownWord (familiarity) does NOT use this scoping - see its own
    docstring for why. Scoping is what makes it possible to try a custom
    dictionary word (which
    feeds straight into DAG segmentation via the per-request UserOverlay -
    see dag_segmentor.py) against just one text without it silently
    affecting every other analysis.

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
    UserWord/Fragment. This was scoped for a while (scope_analysis_id/
    scope_input_text_id, same design as UserWord/Fragment) but that was
    reversed: familiarity was never meant to vary by text/analysis - "how
    well do I know this word" isn't a per-text question the way "should
    this count toward this text's vocabulary" (UserWord) or "is this a real
    word here or a segmentation artifact" (Fragment) are.
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


class Fragment(Base):
    """
    A word/string the user has decided isn't worth studying, but which is
    still real Chinese content worth annotating and occasionally revisiting —
    unlike GarbageWord, which is for things like numbers or punctuation that
    should never be shown again.

    Deliberately has no relationship to DictionaryWord/UserWord: marking
    something a fragment must never feed the trie/frequency table or the
    per-user segmentation overlay. It's a display-layer annotation only, so a
    flagged fragment carries no risk of reinforcing whatever segmentation
    error produced it in the first place.

    Scoping (scope_analysis_id/scope_input_text_id): see UserWord's
    docstring for the design - identical mutual-exclusivity/uniqueness
    rules. Resolution priority (analysis > text > global) is also the
    same, but what gets resolved is now `is_fragment`'s value at the
    highest-priority applicable row, not just whether a row exists - see
    its own docstring below.
    """
    __tablename__ = "fragments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    word: Mapped[str] = mapped_column(String, nullable=False)
    note: Mapped[str | None] = mapped_column(String, nullable=True)

    # Tri-state per scope: a row's mere existence used to be the only
    # signal ("this is a fragment"), which couldn't express "explicitly
    # NOT a fragment here" as an override of a broader scope's marking -
    # both looked like "no row" at the narrower scope. is_fragment is what
    # turns that into a real ternary: a row can now mean either "is a
    # fragment" or "explicitly not a fragment, overriding a broader
    # scope's marking" without touching or deleting that broader row. No
    # applicable row at any scope still means "not a fragment" (there's
    # nothing to resolve to - see get_word_detail/list_fragments,
    # router.py). Every row that existed before this column was added
    # meant "this is a fragment" (the only thing a row could mean at the
    # time), which is exactly what the migration adding this column
    # backfills.
    is_fragment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    scope_analysis_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("analyses.id"), nullable=True, index=True)
    scope_input_text_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("input_texts.id"), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship("User")

    __table_args__ = (
        Index(
            "ix_fragments_user_word_scope", "user_id", "word", "scope_analysis_id", "scope_input_text_id",
            unique=True, postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "scope_analysis_id IS NULL OR scope_input_text_id IS NULL",
            name="ck_fragments_scope_mutually_exclusive",
        ),
    )


class StarredWord(Base):
    """
    A word/phrase the user has flagged as interesting or worth remembering -
    mirrors Fragment's shape (word + optional note) rather than
    GarbageWord's (no system-wide/is_override concept - this is purely
    personal, there's no "starred by default for everyone" notion).

    Deliberately global only, no scope_analysis_id/scope_input_text_id like
    KnownWord/UserWord/Fragment have - starring something is a lightweight
    personal bookmark, not tied to segmentation or a particular reading
    session, so scoping it wasn't asked for and isn't built here.
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
    __tablename__ = "stopwords"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    word: Mapped[str] = mapped_column(String, nullable=False)
    algo_type: Mapped[str] = mapped_column(String, nullable=False)  # "longest_match" or "tokenization"
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    is_override: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped["User | None"] = relationship("User")

    __table_args__ = (
        Index("ix_stopwords_user_word_algo", "user_id", "word", "algo_type", unique=True),
        CheckConstraint("algo_type IN ('longest_match', 'tokenization')", name="ck_stopwords_algo_type"),
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
    source: Mapped[str] = mapped_column(String, nullable=False)  # "trie", "token", "unknown", "dag", "overlay", "longest_match_only"
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
            "source IN ('trie', 'token', 'unknown', 'dag', 'overlay', 'longest_match_only')",
            name="ck_analysis_results_source",
        ),
    )