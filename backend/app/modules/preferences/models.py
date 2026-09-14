from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from datetime import datetime
from app.models.user import User


class UserPreference(Base):
    """
    One row per user+key, value stored as an opaque JSONB blob - a generic
    settings store, not specific to any one feature. This module doesn't
    know or care what any given `key` means (no allowlist, no per-key
    schema); that's entirely up to whichever caller reads/writes it (the
    export feature uses key "export" - see known_words - but the shape here
    supports any number of future keys without a migration each time).

    First real user of this table is the Pleco-export preferences (pinyin/
    definition-source toggles), replacing this app's earlier "preferences
    are always localStorage" convention (theme, word-detail-panel section
    defaults, context length) - deliberately NOT migrating those three here
    in the same pass; this table's shape supports that as later, focused
    follow-up work, not something this feature needs to take on.
    """
    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship("User")

    __table_args__ = (
        Index("ix_user_preferences_user_key", "user_id", "key", unique=True),
    )
