"""Sign-up, login, refresh, and password step-up."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import seal_text
from app.core.errors import AppError
from app.core.security import (
    TERMS_VERSION,
    PasswordStepUp,
    email_hash,
    hash_password,
    issue_token,
    read_token,
    verify_password,
)
from app.db.models import Consent, User
from app.deps import current_user, get_session

router = APIRouter(prefix="/auth", tags=["auth"])


class SignupBody(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=8)
    language: str = "en"


class LoginBody(BaseModel):
    email: str
    password: str


class RefreshBody(BaseModel):
    refresh_token: str


class StepUpBody(BaseModel):
    password: str


def _tokens(request: Request, user_id: str) -> dict:
    secret = request.app.state.settings.jwt_secret
    clock = request.app.state.clock
    return {
        "access_token": issue_token(secret, user_id, "access", clock),
        "refresh_token": issue_token(secret, user_id, "refresh", clock),
    }


@router.post("/signup", status_code=201)
def signup(body: SignupBody, request: Request, session: Session = Depends(get_session)) -> dict:
    if "@" not in body.email:
        raise AppError("invalid_email", "Enter an email address", status_code=400)
    digest = email_hash(body.email)
    existing = session.scalar(select(User).where(User.email_hash == digest))
    if existing is not None:
        raise AppError("email_taken", "An account with that email already exists", status_code=409)
    master = request.app.state.master_key
    user = User(
        email_hash=digest,
        email_enc=seal_text(str(body.email).strip().lower(), master),
        password_hash=hash_password(request.app.state.hasher, body.password),
        language=body.language,
        created_at=request.app.state.clock.now(),
    )
    session.add(user)
    session.flush()
    session.add(
        Consent(
            user_id=user.id,
            kind="terms",
            granted_at=request.app.state.clock.now(),
            terms_version=TERMS_VERSION,
        )
    )
    return {"user_id": str(user.id), **_tokens(request, str(user.id))}


@router.post("/login")
def login(body: LoginBody, request: Request, session: Session = Depends(get_session)) -> dict:
    digest = email_hash(body.email)
    if not request.app.state.login_limiter.allow(digest):
        raise AppError("rate_limited", "Too many sign-in attempts", status_code=429)
    user = session.scalar(select(User).where(User.email_hash == digest))
    if user is None or not verify_password(request.app.state.hasher, user.password_hash, body.password):
        raise AppError("wrong_password", "Email or password did not match", status_code=401)
    return _tokens(request, str(user.id))


@router.post("/refresh")
def refresh(body: RefreshBody, request: Request, session: Session = Depends(get_session)) -> dict:
    user_id = read_token(request.app.state.settings.jwt_secret, body.refresh_token, "refresh", request.app.state.clock)
    user = session.get(User, user_id)
    if user is None:
        raise AppError("unauthorized", "Sign in again", status_code=401)
    return _tokens(request, str(user.id))


@router.post("/step-up")
def step_up(
    body: StepUpBody,
    request: Request,
    session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> dict:
    PasswordStepUp(request.app.state.hasher).grant(user, body.password, request.app.state.clock)
    session.add(user)
    until = user.step_up_until or datetime.now(timezone.utc)
    return {"step_up_until": until.isoformat()}
