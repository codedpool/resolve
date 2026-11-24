"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.core.clock import Clock, SystemClock
from app.core.errors import install_error_handlers
from app.core.idempotency import IdempotencyStore
from app.core.logging import configure_logging


def create_app(
    settings: Settings | None = None,
    clock: Clock | None = None,
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
    install_error_handlers(app)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    return app
