"""Application settings. Model ids are read from config/models.yaml only."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVER_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVER_ROOT.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    groq_api_key: str = ""
    rumik_api_key: str = ""
    database_url: str = "postgresql+psycopg://resolve:resolve@127.0.0.1:5434/resolve"
    jwt_secret: str = "dev-only-change-me"
    master_key: str = ""
    app_env: str = "dev"
    cors_origins: str = "http://localhost:3000"
    voice_max_call_seconds: int = 600
    voice_daily_stt_seconds: int = 3600
    voice_daily_tts_chars: int = 200_000
    groq_budget_usd: float = 20
    legal_verifier: str = "llm"
    models_path: Path = Field(default=SERVER_ROOT / "config" / "models.yaml")

    def secret_values(self) -> list[str]:
        values = []
        for value in (self.groq_api_key, self.rumik_api_key, self.jwt_secret, self.master_key):
            if value and len(value) >= 8 and value != "dev-only-change-me":
                values.append(value)
        return values

    def load_models(self) -> dict:
        raw = yaml.safe_load(self.models_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or "roles" not in raw:
            raise ValueError(f"model config at {self.models_path} has no roles")
        return raw


@lru_cache
def get_settings() -> Settings:
    return Settings()
