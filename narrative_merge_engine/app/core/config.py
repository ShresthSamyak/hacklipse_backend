"""
Centralised configuration management.
All runtime settings are read from environment variables / .env file.
No value is ever hard-coded here.
"""

from functools import lru_cache
from typing import Literal
import os

from dotenv import load_dotenv
from pydantic import AnyHttpUrl, Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Optional fallback using python-dotenv to ensure variables load correctly
# This catches situations where Pydantic settings might struggle defining relative pathing
load_dotenv(".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ─────────────────────────────────────────────────────────
    APP_ENV: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = False
    PROJECT_NAME: str = "Narrative Merge Engine"
    API_V1_PREFIX: str = "/api/v1"
    ALLOWED_ORIGINS: list[str] | str = Field(default=["http://localhost:3000"])

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_origins(cls, v: str | list | None) -> list[str]:
        if not v:
            return []
        
        if isinstance(v, str):
            # 1. Safely handle JSON strings if provided in .env
            if v.startswith("[") and v.endswith("]"):
                import json
                try:
                    parsed = json.loads(v)
                    if isinstance(parsed, list):
                        return [str(o).strip() for o in parsed if str(o).strip()]
                except json.JSONDecodeError:
                    pass
            # 2. Hande standard comma-separated strings safely
            return [o.strip() for o in v.split(",") if o.strip()]
            
        if isinstance(v, list):
            return [str(o).strip() for o in v if str(o).strip()]
            
        return []

    # ── Security ─────────────────────────────────────────────────────────────
    SECRET_KEY: str = "CHANGE_ME"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # ── Database ─────────────────────────────────────────────────────────────
    DATABASE_URL: PostgresDsn
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20
    DATABASE_ECHO: bool = False

    # ── Redis ────────────────────────────────────────────────────────────────
    REDIS_URL: RedisDsn = Field(default="redis://localhost:6379/0")  # type: ignore[assignment]

    # ── Primary LLM (provider-agnostic) ──────────────────────────────────────
    LLM_PROVIDER: Literal["openai", "anthropic", "gemini", "azure_openai", "groq", "custom"] = "groq"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "llama-3.3-70b-versatile"
    LLM_TEMPERATURE: float = 0.0
    LLM_BASE_URL: str | None = None
    LLM_TIMEOUT_SECONDS: int = 60
    LLM_MAX_RETRIES: int = 2

    # ── Fast / lightweight LLM (optional) ────────────────────────────────────
    # When set, the orchestrator routes lightweight tasks here.
    # When blank, falls back to the primary LLM.
    FAST_LLM_PROVIDER: str = ""          # e.g. "groq", "gemini"
    FAST_LLM_API_KEY: str = ""           # leave blank to reuse LLM_API_KEY
    FAST_LLM_MODEL: str = ""             # e.g. "gemma2-9b-it"

    # ── Speech-to-Text (ASR) ──────────────────────────────────────────────────
    ASR_PROVIDER: str = "groq"           # groq | openai | custom
    ASR_MODEL: str = "whisper-large-v3-turbo"
    ASR_LANGUAGE: str = ""               # ISO 639-1; blank = auto-detect
    ASR_MAX_FILE_BYTES: int = 26_214_400  # 25 MB

    # ── Logging ─────────────────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: Literal["json", "console"] = "json"

    # ── Convenience helpers ──────────────────────────────────────────────────

    @property
    def fast_llm_enabled(self) -> bool:
        """True if a separate fast LLM is configured."""
        return bool(self.FAST_LLM_PROVIDER and self.FAST_LLM_MODEL)

    @property
    def fast_llm_api_key(self) -> str:
        """Return the fast LLM key, falling back to the primary key."""
        return self.FAST_LLM_API_KEY or self.LLM_API_KEY


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton settings instance."""
    return Settings()  # type: ignore[call-arg]


# Module-level shortcut
settings: Settings = get_settings()
