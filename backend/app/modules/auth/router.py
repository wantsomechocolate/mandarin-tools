from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.modules.auth import service
from app.modules.auth.schemas import (
    AccountDelete,
    PasswordChange,
    Token,
    UserCreate,
    UserMeResponse,
    UserResponse,
)


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(user_in: UserCreate, db: Session = Depends(get_db)):
    if service.get_user_by_email(db, user_in.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )
    if service.get_user_by_username(db, user_in.username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already taken",
        )
    return service.create_user(db, user_in)


@router.post("/token", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    token = service.login_for_access_token(db, form_data.username, form_data.password)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=token, token_type="bearer")


@router.get("/me", response_model=UserMeResponse)
def read_current_user(current_user: User = Depends(get_current_user)):
    return current_user


@router.put("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: PasswordChange,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not service.change_password(db, current_user, body.current_password, body.new_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    body: AccountDelete,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Deletes the current user's account and every row of theirs across every
    module - see service.delete_user_account's own docstring for the full
    cascade this actually runs. Password-gated (not just "you're logged
    in") since this is the one truly irreversible destructive action in the
    whole app - a valid session alone (e.g. a left-open tab) shouldn't be
    enough on its own.
    """
    if not service.delete_user_account(db, current_user, body.password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password is incorrect")