from unittest.mock import AsyncMock

import httpx
import pytest
from neo4j.exceptions import ServiceUnavailable
from pydantic import ValidationError
from test_embeddings import embedding_settings

from kg_assistant.api.dependencies import get_embedding_ingestion, get_vector_retrieval
from kg_assistant.core.exceptions import IngestionError
from kg_assistant.db.repositories.vectors import VectorRepository
from kg_assistant.main import create_app
from kg_assistant.models.embeddings import BackfillResponse
from kg_assistant.models.retrieval import VectorSearchRequest
from kg_assistant.providers.embeddings import EmbeddingError
from kg_assistant.retrieval.vector import VectorRetrievalService


@pytest.mark.parametrize(
    "body",
    [
        {"query": ""},
        {"query": "  \n "},
        {"query": "valid", "top_k": 0},
        {"query": "valid", "top_k": 101},
        {"query": "valid", "top_k": True},
        {"query": "valid", "top_k": "5"},
        {"query": "valid", "top_k": 1.5},
    ],
)
def test_request_validation(body):
    with pytest.raises(ValidationError):
        VectorSearchRequest(**body)


async def test_result_mapping_and_parameterized_query():
    repository = VectorRepository(AsyncMock(), embedding_settings())
    repository._run = AsyncMock(
        return_value=[
            {
                "chunk_id": "c",
                "text": "Redis caches payments",
                "score": 0.91,
                "document_id": "d",
                "filename": "payments.pdf",
                "page_number": 2,
                "chunk_index": 4,
            }
        ]
    )
    results = await repository.search([1.0, 2.0, 3.0], 5)
    assert results[0].filename == "payments.pdf"
    assert results[0].page_number == 2
    assert results[0].chunk_index == 4
    assert results[0].document_id == "d"
    statement = repository._run.call_args.args[0]
    assert "HAS_CHUNK" in statement
    assert "$vector" in statement and "$top_k" in statement
    assert repository._run.call_args.kwargs["vector"] == [1.0, 2.0, 3.0]


async def test_search_calls_same_embedding_service_and_empty_results():
    repo, embedder = AsyncMock(), AsyncMock()
    embedder.embed_text.return_value = [1.0, 2.0, 3.0]
    repo.search.return_value = []
    service = VectorRetrievalService(embedding_settings(), repo, embedder)
    response = await service.search(VectorSearchRequest(query="  missing evidence  ", top_k=2))
    assert response.query == "missing evidence"
    assert response.results == []
    embedder.embed_text.assert_awaited_once_with("missing evidence")
    repo.search.assert_awaited_once_with([1.0, 2.0, 3.0], 2)


@pytest.mark.parametrize(
    "code,status",
    [
        ("embedding_dimension_mismatch", 502),
        ("embedding_provider_unavailable", 502),
        ("embedding_input_too_large", 422),
    ],
)
async def test_query_embedding_failures(code, status):
    repo, embedder = AsyncMock(), AsyncMock()
    embedder.embed_text.side_effect = EmbeddingError(code)
    with pytest.raises(IngestionError) as failure:
        await VectorRetrievalService(embedding_settings(), repo, embedder).search(
            VectorSearchRequest(query="query")
        )
    assert failure.value.code == code
    assert failure.value.status_code == status
    repo.search.assert_not_awaited()


async def test_runtime_top_k_database_and_disabled(settings):
    repo, embedder = AsyncMock(), AsyncMock()
    with pytest.raises(IngestionError, match="configured maximum"):
        await VectorRetrievalService(embedding_settings(vector_max_top_k=2), repo, embedder).search(
            VectorSearchRequest(query="query", top_k=3)
        )
    repo.ensure_index.side_effect = ServiceUnavailable("sensitive")
    with pytest.raises(IngestionError) as failure:
        await VectorRetrievalService(embedding_settings(), repo, embedder).search(
            VectorSearchRequest(query="query")
        )
    assert failure.value.status_code == 503
    assert "sensitive" not in failure.value.message
    with pytest.raises(IngestionError) as failure:
        await VectorRetrievalService(settings, repo, None).search(
            VectorSearchRequest(query="query")
        )
    assert failure.value.code == "embeddings_disabled"


async def test_vector_and_backfill_api_validation(settings):
    app = create_app(settings)
    retrieval = AsyncMock()
    retrieval.search.return_value = {"query": "query", "results": []}
    backfill = AsyncMock()
    backfill.backfill.return_value = BackfillResponse(updated=1, processed=1)
    app.dependency_overrides[get_vector_retrieval] = lambda: retrieval
    app.dependency_overrides[get_embedding_ingestion] = lambda: backfill
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.post("/api/retrieval/vector-search", json={"query": "query"})
        assert result.status_code == 200
        assert result.json() == {"query": "query", "results": []}
        for body in (
            {"query": " "},
            {"query": "query", "top_k": 0},
            {"query": "query", "top_k": 101},
        ):
            assert (await client.post("/api/retrieval/vector-search", json=body)).status_code == 422
        assert (await client.post("/api/embeddings/backfill", json={"limit": 0})).status_code == 422
        assert (
            await client.post("/api/embeddings/backfill", json={"limit": 1001})
        ).status_code == 422
        result = await client.post(
            "/api/embeddings/backfill", json={"document_id": "d", "limit": 3}
        )
        assert result.json()["updated"] == 1
        backfill.backfill.assert_awaited_once_with("d", 3)
