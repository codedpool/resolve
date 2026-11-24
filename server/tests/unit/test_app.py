from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.config import Settings
from app.core.clock import FrozenClock
from app.core.errors import AppError
from app.core.idempotency import IdempotencyStore
from app.core.ratelimit import RateLimiter
from app.main import create_app


def test_health_returns_200():
    client = TestClient(create_app(settings=Settings(groq_api_key="", rumik_api_key="")))
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_app_error_uses_the_shared_shape():
    app = create_app(settings=Settings(groq_api_key="", rumik_api_key=""))

    @app.get("/boom")
    def boom():
        raise AppError("bad_request", "No", status_code=400, details={"why": "test"})

    response = TestClient(app).get("/boom")
    assert response.status_code == 400
    assert response.json() == {"error": {"code": "bad_request", "message": "No", "details": {"why": "test"}}}


def test_idempotency_store_returns_the_first_value():
    store = IdempotencyStore()
    first, created = store.remember("key-1", {"run_id": "a"})
    second, again = store.remember("key-1", {"run_id": "b"})
    assert created is True
    assert again is False
    assert first == second == {"run_id": "a"}


def test_rate_limiter_blocks_after_the_window_is_full():
    clock = FrozenClock(datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc))
    limiter = RateLimiter(limit=2, window=timedelta(minutes=1), clock=clock)
    assert limiter.allow("user") is True
    assert limiter.allow("user") is True
    assert limiter.allow("user") is False
    clock.advance(seconds=61)
    assert limiter.allow("user") is True
