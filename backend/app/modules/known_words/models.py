
from sqlalchemy import ARRAY, BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, SmallInteger, String, func
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

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user: Mapped["User"] = relationship("User")
    dictionary_word: Mapped["DictionaryWord | None"] = relationship("DictionaryWord")
    #dictionary_word: Mapped["DictionaryWord | None"] = relationship("DictionaryWord", back_populates="user_words")
    #known_words: Mapped[list["KnownWord"]] = relationship("KnownWord", back_populates="user_word")

    __table_args__ = (
        # A user can only have one entry per word
        Index("ix_user_words_user_word", "user_id", "word", unique=True),
    )



class KnownWord(Base):
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
    analysis_results: Mapped[list["AnalysisResult"]] = relationship(
        "AnalysisResult", back_populates="input_text", cascade="all, delete-orphan"
    )


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    input_text_id: Mapped[int] = mapped_column(Integer, ForeignKey("input_texts.id"), nullable=False, index=True)
    word: Mapped[str] = mapped_column(String, nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)  # "trie", "token", "unknown"

    input_text: Mapped["InputText"] = relationship("InputText", back_populates="analysis_results")

    __table_args__ = (
        Index("ix_analysis_results_input_text_word", "input_text_id", "word", unique=True),
        CheckConstraint("source IN ('trie', 'token', 'unknown')", name="ck_analysis_results_source"),
    )

