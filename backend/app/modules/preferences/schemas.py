from typing import Any

from pydantic import BaseModel


class PreferenceResponse(BaseModel):
    key: str
    # None when no row exists yet for this user+key - always 200, never a
    # 404, same "no row means show client-side defaults" pattern this
    # codebase already uses for GET /word-enrichment/{word}. Callers own
    # their own default value entirely; this module has no opinion on it.
    value: Any | None = None


class PreferenceUpsert(BaseModel):
    value: Any
