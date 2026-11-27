import json
from pathlib import Path

from app.config import Settings
from app.core.crypto import encode_master_key, generate_key
from app.main import create_app


def test_openapi_snapshot_matches_the_app():
    settings = Settings(
        app_env="test",
        jwt_secret="test-jwt-secret-value-32-bytes-minimum",
        master_key=encode_master_key(generate_key()),
        groq_api_key="",
        rumik_api_key="",
        database_url="postgresql+psycopg://resolve:resolve@127.0.0.1:5434/resolve",
    )
    spec = create_app(settings).openapi()
    saved = json.loads(Path("openapi.json").read_text(encoding="utf-8"))
    assert saved == spec
