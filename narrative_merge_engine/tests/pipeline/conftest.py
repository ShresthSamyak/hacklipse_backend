"""
Isolated conftest for DemoPipeline unit tests.

Patches required environment variables at import time so tests can run
without a live .env or DATABASE_URL configured.
This must be the FIRST thing executed — hence it lives at module level
before any `from app` imports appear in this package.
"""

import os

# ── Minimum env vars that app.core.config.Settings requires ────────────────
# These are stubs; no real DB/LLM calls happen in unit tests.
_REQUIRED_ENV_STUBS: dict[str, str] = {
    "DATABASE_URL": "postgresql+asyncpg://test:test@localhost:5432/test_db",
    "LLM_API_KEY": "test-key-stub",
    "SECRET_KEY": "test-secret-key-stub",
    "APP_ENV": "development",
}

for _key, _val in _REQUIRED_ENV_STUBS.items():
    os.environ.setdefault(_key, _val)

# ── Clear the lru_cache so Settings re-reads with our patched env ──────────
try:
    from app.core.config import get_settings
    get_settings.cache_clear()
except Exception:
    pass  # not yet imported — nothing to clear

import pytest  # noqa: E402 (must be after env patch)


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"
