from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.modules.preferences.models import UserPreference
from app.modules.preferences.schemas import PreferenceResponse, PreferenceUpsert


router = APIRouter(prefix="/preferences", tags=["preferences"])


@router.get("/{key}", response_model=PreferenceResponse)
def get_preference(
    key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Always 200, even when nothing's been saved yet - a null `value` cleanly
    means "no row, use whatever default the caller already has," no 404
    special-casing needed client-side (same pattern GET /word-enrichment/
    {word} already uses).
    """
    row = db.query(UserPreference).filter_by(user_id=current_user.id, key=key).first()
    return PreferenceResponse(key=key, value=row.value if row else None)


@router.put("/{key}", response_model=PreferenceResponse)
def set_preference(
    key: str,
    payload: PreferenceUpsert,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create-or-update, one row per user+key - see UserPreference's docstring."""
    row = db.query(UserPreference).filter_by(user_id=current_user.id, key=key).first()
    if row:
        row.value = payload.value
    else:
        row = UserPreference(user_id=current_user.id, key=key, value=payload.value)
        db.add(row)
    db.commit()
    return PreferenceResponse(key=key, value=payload.value)
