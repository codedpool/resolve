"""Passwords, tokens, and step-up. A one-time-code provider is a stub until a delivery channel exists."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Protocol

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.clock import Clock
from app.core.errors import AppError

ACCESS_MINUTES = 15
REFRESH_DAYS = 14
STEP_UP_MINUTES = 10
TERMS_VERSION = "2026-11-24"


class TokenError(AppError):
    def __init__(self) -> None:
        super().__init__("unauthorized", "Sign in again", status_code=401)


class NotConfigured(AppError):
    def __init__(self, message: str) -> None:
        super().__init__("not_configured", message, status_code=501)


def email_hash(email: str) -> str:
    normalized = email.strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def make_hasher(app_env: str) -> PasswordHasher:
    if app_env == "test":
        return PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1)
    return PasswordHasher()


def hash_password(hasher: PasswordHasher, password: str) -> str:
    return hasher.hash(password)


def verify_password(hasher: PasswordHasher, password_hash: str, password: str) -> bool:
    try:
        return hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def issue_token(secret: str, user_id: str, kind: str, clock: Clock) -> str:
    now = clock.now()
    lifetime = timedelta(minutes=ACCESS_MINUTES) if kind == "access" else timedelta(days=REFRESH_DAYS)
    payload = {"sub": user_id, "typ": kind, "iat": int(now.timestamp()), "exp": int((now + lifetime).timestamp())}
    return jwt.encode(payload, secret, algorithm="HS256")


def read_token(secret: str, token: str, kind: str, clock: Clock) -> str:
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"verify_exp": False, "verify_iat": False, "verify_nbf": False},
        )
    except jwt.PyJWTError as exc:
        raise TokenError() from exc
    if payload.get("typ") != kind or not payload.get("sub"):
        raise TokenError()
    if int(payload["exp"]) <= int(clock.now().timestamp()):
        raise TokenError()
    return str(payload["sub"])


class StepUpProvider(Protocol):
    def grant(self, user, password: str, clock: Clock) -> None: ...


class PasswordStepUp:
    def __init__(self, hasher: PasswordHasher) -> None:
        self.hasher = hasher

    def grant(self, user, password: str, clock: Clock) -> None:
        if not verify_password(self.hasher, user.password_hash, password):
            raise AppError("wrong_password", "Password did not match", status_code=401)
        user.step_up_until = clock.now() + timedelta(minutes=STEP_UP_MINUTES)


class OneTimeCodeStepUp:
    """Reserved for a later delivery channel. Password re-entry is the only method in this version."""

    def grant(self, user, password: str, clock: Clock) -> None:
        raise NotConfigured("One-time codes are not enabled")


def step_up_is_fresh(user, clock: Clock) -> bool:
    until = user.step_up_until
    return until is not None and clock.now() <= until
