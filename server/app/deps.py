"""Request dependencies."""

from __future__ import annotations

import uuid

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import read_token, step_up_is_fresh
from app.db.models import User
from app.db.session import make_session_factory


def get_session(request: Request):
    factory = request.app.state.session_factory or make_session_factory(request.app.state.settings)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def current_user(
    request: Request,
    session: Session = Depends(get_session),
    authorization: str | None = Header(default=None),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AppError("unauthorized", "Sign in again", status_code=401)
    token = authorization.split(" ", 1)[1].strip()
    user_id = read_token(request.app.state.settings.jwt_secret, token, "access", request.app.state.clock)
    user = session.get(User, uuid.UUID(user_id))
    if user is None:
        raise AppError("unauthorized", "Sign in again", status_code=401)
    return user


def require_step_up(request: Request, user: User = Depends(current_user)) -> User:
    if not step_up_is_fresh(user, request.app.state.clock):
        raise AppError("step_up_required", "Enter your password again", status_code=403)
    return user
