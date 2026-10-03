from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from graph_fixtures import SAMPLE, sample_extraction
from neo4j.exceptions import ServiceUnavailable

from kg_assistant.api.dependencies import (
    get_document_repository,
    get_extraction_provider,
    get_graph_repository,
)
from kg_assistant.core.exceptions import IngestionError
from kg_assistant.ingestion.entity_extraction import EntityExtractionService
from kg_assistant.main import create_app
from kg_assistant.models.documents import Chunk
from kg_assistant.models.extraction import ExtractionSummary
from kg_assistant.providers.base import ExtractionError
from kg_assistant.services.knowledge_graph import GraphIngestionService


async def test_chunk_failure_does_not_stop_other_chunks(settings):
    chunks = [Chunk(id=str(i), document_id="doc", text=SAMPLE, chunk_index=i) for i in range(3)]
    settings.llm_max_attempts = 1
    repo = AsyncMock()
    repo.begin.return_value = "run"
    repo.pending_chunks.return_value = chunks
    repo.finish.return_value = ExtractionSummary(status="partial", total=3, completed=2, failed=1)
    provider = AsyncMock()
    provider.extract.side_effect = [
        sample_extraction(),
        ExtractionError("llm_invalid_response"),
        sample_extraction(),
    ]
    service = GraphIngestionService(settings, repo, EntityExtractionService(provider, settings))
    assert (await service.ingest("doc")).status == "partial"
    assert repo.save_chunk.await_count == 2
    repo.fail_chunk.assert_awaited_once_with(chunks[1], "llm_invalid_response", 1, "run")
    repo.finish.assert_awaited_once()


async def test_graph_write_failure_is_recorded(settings):
    repo = AsyncMock()
    repo.begin.return_value = "run"
    chunk = Chunk(id="c", document_id="d", text=SAMPLE, chunk_index=0)
    repo.pending_chunks.return_value = [chunk]
    repo.save_chunk.side_effect = ServiceUnavailable("sensitive details")
    provider = AsyncMock()
    provider.extract.return_value = sample_extraction()
    service = GraphIngestionService(settings, repo, EntityExtractionService(provider, settings))
    await service.ingest("d")
    repo.fail_chunk.assert_awaited_once_with(chunk, "graph_write_failed", 1, "run")


async def test_storage_failure_returns_saved_document_id(settings):
    repo = AsyncMock()
    repo.begin.side_effect = ServiceUnavailable("secret")
    service = GraphIngestionService(settings, repo, AsyncMock())
    with pytest.raises(IngestionError) as caught:
        await service.ingest("saved-id")
    assert caught.value.status_code == 503
    assert "saved-id" in caught.value.message and "secret" not in caught.value.message


def test_upload_invokes_extraction_and_retry_skips_completed(settings):
    settings.llm_extraction_enabled = True
    settings.llm_model = "mock-model"
    documents = AsyncMock()
    graph = AsyncMock()
    graph.begin.return_value = "run"
    chunk = Chunk(id="c", document_id="doc", text=SAMPLE, chunk_index=0)
    graph.pending_chunks.side_effect = [[chunk], []]
    graph.finish.return_value = ExtractionSummary(status="completed", total=1, completed=1)
    provider = AsyncMock()
    provider.extract.return_value = sample_extraction()
    app = create_app(settings)
    app.dependency_overrides[get_document_repository] = lambda: documents
    app.dependency_overrides[get_graph_repository] = lambda: graph
    app.dependency_overrides[get_extraction_provider] = lambda: provider
    driver = MagicMock()
    driver.close = AsyncMock()
    with (
        patch("kg_assistant.db.neo4j.AsyncGraphDatabase.driver", return_value=driver),
        patch("kg_assistant.main.OpenAIExtractionProvider", return_value=AsyncMock()),
    ):
        with TestClient(app) as client:
            upload = client.post(
                "/api/documents/upload", files={"file": ("sample.txt", SAMPLE.encode())}
            )
            assert upload.status_code == 201
            assert upload.json()["extraction"]["status"] == "completed"
            assert upload.json()["document"]["extraction_status"] == "completed"
            documents.save.assert_awaited_once()
            graph.save_chunk.assert_awaited_once()
            assert client.post("/api/documents/doc/extract").status_code == 200
            provider.extract.assert_awaited_once()
            graph.summary.return_value = ExtractionSummary(status="completed", total=1, completed=1)
            assert client.get("/api/documents/doc/extraction").json()["status"] == "completed"


def test_retry_disabled_and_missing_document(settings):
    app = create_app(settings)
    graph = AsyncMock()
    app.dependency_overrides[get_graph_repository] = lambda: graph
    driver = MagicMock()
    driver.close = AsyncMock()
    with patch("kg_assistant.db.neo4j.AsyncGraphDatabase.driver", return_value=driver):
        with TestClient(app) as client:
            assert client.post("/api/documents/doc/extract").status_code == 503
            graph.summary.side_effect = IngestionError("document_not_found", "Not found", 404)
            assert client.get("/api/documents/absent/extraction").status_code == 404
