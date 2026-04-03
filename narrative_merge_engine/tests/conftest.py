"""
Shared pytest fixtures for integration and unit tests.

The FastAPI app import is deferred to inside the `client` fixture so that
unit tests (e.g. DemoPipeline tests) can run without a DATABASE_URL or .env
in the environment.  Only tests that explicitly request the `client` fixture
will trigger the full app import chain.
"""

import pytest


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture()
async def client():
    """Async HTTP test client for FastAPI endpoints.

    Lazily imports the app so that unit tests which don't use this fixture
    can run without a DATABASE_URL configured.
    """
    from httpx import ASGITransport, AsyncClient
    from main import app  # deferred — only loads when client is requested

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
