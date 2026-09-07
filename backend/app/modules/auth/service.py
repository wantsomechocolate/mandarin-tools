from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.auth import hash_password, verify_password, create_access_token
from app.models.user import User
from app.modules.auth.schemas import UserCreate


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email).first()


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.query(User).filter(User.username == username).first()


def create_user(db: Session, user_in: UserCreate) -> User:
    user = User(
        email=user_in.email,
        username=user_in.username,
        hashed_password=hash_password(user_in.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    user = get_user_by_email(db, email)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def login_for_access_token(db: Session, email: str, password: str) -> str | None:
    user = authenticate_user(db, email, password)
    if not user:
        return None
    return create_access_token(data={"sub": user.email})


def change_password(db: Session, user: User, current_password: str, new_password: str) -> bool:
    """Returns False (no-op) if current_password doesn't match - the router
    turns that into a 400, same pattern authenticate_user's callers use."""
    if not verify_password(current_password, user.hashed_password):
        return False
    user.hashed_password = hash_password(new_password)
    db.commit()
    return True


def delete_user_account(db: Session, user: User, password: str) -> bool:
    """
    Deletes a user and every row of theirs across every module that owns
    user-scoped data. Returns False (does nothing) if password doesn't
    match; the router turns that into a 400.

    No FK here has ON DELETE CASCADE (checked directly against every
    known_words model before writing this) - this is the one place that has
    to know the complete list of user-owned tables and the order deleting
    them actually has to happen in, or Postgres rejects the delete with a
    foreign-key violation:

    - user_words/word_visibility carry their OWN FKs into analyses/
      input_texts (scope_analysis_id/scope_input_text_id), so they have to
      go before analyses/input_texts can be deleted, not after or Postgres
      would be deleting a row those two tables still point to.
    - analysis_results -> analyses -> input_texts, in that order (child
      before parent), same reasoning.
    - garbage_words/stopwords also hold system-default rows (user_id IS
      NULL, shared across every user) - every DELETE below is scoped to
      `user_id = :uid` specifically so a deletion never touches those.

    Same shape as the manual per-table cleanup used for throwaway test
    accounts during this app's own development (ad hoc SQL, run by hand) -
    written here properly once real account deletion needed to exist.
    """
    if not verify_password(password, user.hashed_password):
        return False

    uid = user.id

    db.execute(text("DELETE FROM user_words WHERE user_id = :uid"), {"uid": uid})
    db.execute(text("DELETE FROM word_visibility WHERE user_id = :uid"), {"uid": uid})

    db.execute(text("""
        DELETE FROM analysis_results WHERE analysis_id IN (
            SELECT a.id FROM analyses a
            JOIN input_texts t ON a.input_text_id = t.id
            WHERE t.user_id = :uid
        )
    """), {"uid": uid})
    db.execute(text("""
        DELETE FROM analyses WHERE input_text_id IN (
            SELECT id FROM input_texts WHERE user_id = :uid
        )
    """), {"uid": uid})
    db.execute(text("DELETE FROM input_texts WHERE user_id = :uid"), {"uid": uid})

    for table in ("sample_sentences", "known_words", "garbage_words", "starred_words", "word_notes", "stopwords"):
        db.execute(text(f"DELETE FROM {table} WHERE user_id = :uid"), {"uid": uid})

    db.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": uid})
    db.commit()
    return True