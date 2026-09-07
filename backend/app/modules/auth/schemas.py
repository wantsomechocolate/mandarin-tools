from datetime import datetime

from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    email: EmailStr
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    email: str
    username: str
    is_active: bool

    model_config = {"from_attributes": True}


# Separate from UserResponse (used by /auth/register) rather than adding
# created_at there too - register's caller has no use for it, and this is
# specifically the Account page's own "member since" display, not a general
# user-summary shape every endpoint should carry.
class UserMeResponse(BaseModel):
    id: int
    email: str
    username: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class AccountDelete(BaseModel):
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    email: str | None = None