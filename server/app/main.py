"""FastAPI application factory."""

from __future__ import annotations

from datetime import timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.approvals import router as approvals_router
from app.api.auth import router as auth_router
from app.api.cases import router as cases_router
from app.api.evidence import router as evidence_router
from app.api.intake import router as intake_router
from app.api.mandates import router as mandates_router
from app.api.notifications import router as notifications_router
from app.api.runs import router as runs_router
from app.api.voice import router as voice_router
from app.config import SERVER_ROOT, Settings, get_settings
from app.core.clock import Clock, SystemClock
from app.core.crypto import decode_master_key
from app.core.errors import install_error_handlers
from app.core.idempotency import IdempotencyStore
from app.core.logging import configure_logging
from app.core.objects import EncryptedObjectStore
from app.core.ratelimit import RateLimiter
from app.core.security import make_hasher


def create_app(
    settings: Settings | None = None,
    clock: Clock | None = None,
    session_factory=None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.secret_values())
    app = FastAPI(title="Resolve", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = settings
    app.state.clock = clock or SystemClock()
    app.state.idempotency = IdempotencyStore()
    app.state.session_factory = session_factory
    app.state.hasher = make_hasher(settings.app_env)
    app.state.master_key = decode_master_key(settings.master_key) if settings.master_key else b""
    if settings.app_env in {"dev", "prod"} and not app.state.master_key:
        raise RuntimeError("MASTER_KEY is not set. Run scripts/init_env.py to create one in .env.")
    app.state.login_limiter = RateLimiter(limit=5, window=timedelta(minutes=1), clock=app.state.clock)
    app.state.objects = EncryptedObjectStore(SERVER_ROOT / "data" / "objects")
    install_error_handlers(app)
    app.include_router(auth_router)
    app.include_router(cases_router)
    app.include_router(evidence_router)
    app.include_router(intake_router)
    app.include_router(mandates_router)
    app.include_router(approvals_router)
    app.include_router(runs_router)
    app.include_router(notifications_router)
    app.include_router(voice_router)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    return app
