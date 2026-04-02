"""
Tests: Testimony ingestion service unit tests.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest

from app.core.ai.base_provider import LLMResponse
from app.models.schemas.testimony import TestimonyCreate


@pytest.fixture()
def mock_llm():
    llm = MagicMock()
    llm.complete = AsyncMock(
        return_value=LLMResponse(
            content="A witness described events on the night of the incident...",
            model="gpt-4o",
            usage={"total_tokens": 42},
        )
    )
    return llm


@pytest.fixture()
def mock_db():
    return AsyncMock()


@pytest.mark.asyncio
async def test_ingest_creates_testimony(mock_db, mock_llm):
    from app.services.testimony_service import TestimonyIngestionService
    from app.models.orm.testimony import Testimony, TestimonyStatus

    # Patch the repository create to return a fake testimony
    fake_testimony = Testimony(
        id=uuid.uuid4(),
        title="Witness A",
        witness_id="W001",
        raw_text="I saw the incident at 10pm near the bridge.",
        source_type="text",
        language="en",
        status=TestimonyStatus.PROCESSED,
        summary="A witness described events...",
        meta={},
    )

    with patch("app.services.testimony_service.TestimonyRepository") as MockRepo:
        instance = MockRepo.return_value
        instance.create = AsyncMock(return_value=fake_testimony)
        instance.update = AsyncMock(return_value=fake_testimony)
        instance.update_status = AsyncMock(return_value=fake_testimony)

        svc = TestimonyIngestionService(db=mock_db, llm=mock_llm)
        payload = TestimonyCreate(
            title="Witness A",
            witness_id="W001",
            raw_text="I saw the incident at 10pm near the bridge.",
        )
        result = await svc.ingest(payload)

    assert result.witness_id == "W001"
    assert result.title == "Witness A"


@pytest.mark.asyncio
async def test_get_testimony_not_found(mock_db, mock_llm):
    from app.services.testimony_service import TestimonyIngestionService
    from app.core.exceptions import NotFoundError

    with patch("app.services.testimony_service.TestimonyRepository") as MockRepo:
        instance = MockRepo.return_value
        instance.get_by_id = AsyncMock(return_value=None)

        svc = TestimonyIngestionService(db=mock_db, llm=mock_llm)

        with pytest.raises(NotFoundError):
            await svc.get(uuid.uuid4())
