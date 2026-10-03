from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from test_embeddings import embedding_settings
from test_neo4j_upload import integration_settings, pytestmark  # noqa: F401

from kg_assistant.api.dependencies import get_embedding_provider, get_extraction_provider
from kg_assistant.core.exceptions import IngestionError
from kg_assistant.db.repositories.documents import DocumentRepository
from kg_assistant.db.repositories.vectors import VectorRepository
from kg_assistant.main import create_app
from kg_assistant.models.documents import Chunk, Document
from kg_assistant.providers.embeddings import EmbeddingError

SAMPLES = [
    "Platform Team manages Payment Service.",
    "Payment Service uses Redis for caching.",
    "Redis is hosted on AWS ElastiCache.",
    "Customer Service stores transactional data in PostgreSQL.",
]
QUERY = "What caching technology does the payment application use?"


def vector_settings(**overrides):
    base = integration_settings()
    config = embedding_settings(**overrides)
    config.neo4j_uri = base.neo4j_uri
    config.neo4j_password = base.neo4j_password
    config.neo4j_database = base.neo4j_database
    config.chunk_size = 1000
    config.chunk_overlap = 0
    return config


async def clean(connection, document_ids):
    async with connection.driver.session(database=connection.settings.neo4j_database) as session:
        result = await session.run(
            "MATCH (d:Document) WHERE d.id IN $ids "
            "OPTIONAL MATCH (d)-[:HAS_CHUNK]->(c:Chunk) DETACH DELETE d, c",
            ids=document_ids,
        )
        await result.consume()


async def test_real_upload_vector_ranking_provenance_and_index_guard():
    config = vector_settings()
    app = create_app(config)
    provider = AsyncMock()
    # Fixed embeddings exercise actual Neo4j cosine ranking without any API calls.
    vectors = dict(
        zip(
            SAMPLES,
            [[0.0, 1.0, 0.1], [1.0, 0.0, 0.1], [0.3, 0.8, 0.1], [0.1, -0.9, 0.1]],
            strict=True,
        )
    )
    vectors[QUERY] = [1.0, 0.0, 0.1]
    provider.embed_batch.side_effect = lambda texts: [vectors[text] for text in texts]
    app.dependency_overrides[get_embedding_provider] = lambda: provider
    ids = []
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            try:
                for index, sample in enumerate(SAMPLES):
                    response = await client.post(
                        "/api/documents/upload", files={"file": (f"sample{index}.txt", sample)}
                    )
                    assert response.status_code == 201, response.text
                    body = response.json()
                    ids.append(body["document"]["id"])
                    assert body["embeddings"]["status"] == "completed"
                    assert body["extraction"]["status"] == "disabled"
                repo = VectorRepository(app.state.neo4j, config)
                await repo.ensure_index()
                await repo.ensure_index()
                async with app.state.neo4j.driver.session(
                    database=config.neo4j_database
                ) as session:
                    # Explicit visibility boundary for recently committed vector index changes.
                    await (await session.run("CALL db.awaitIndexes(30)")).consume()
                    result = await session.run(
                        "MATCH (d:Document)-[:HAS_CHUNK]->(c:Chunk) WHERE d.id IN $ids "
                        "RETURN c.embedding AS vector, size(c.embedding) AS dimensions, "
                        "c.embedding_model AS model, d.embedding AS document_embedding",
                        ids=ids,
                    )
                    records = [dict(record) async for record in result]
                    assert len(records) == 4
                    assert all(
                        row["dimensions"] == 3 and row["model"] == "mock-embedding"
                        for row in records
                    )
                    assert all(row["document_embedding"] is None for row in records)
                response = await client.post(
                    "/api/retrieval/vector-search", json={"query": QUERY, "top_k": 3}
                )
                assert response.status_code == 200, response.text
                results = response.json()["results"]
                assert len(results) == 3
                assert results[0]["text"] == SAMPLES[1]
                assert results[0]["document_id"] == ids[1]
                assert results[0]["filename"] == "sample1.txt"
                assert results[0]["chunk_index"] == 0
                assert results[0]["page_number"] is None
                assert results[0]["score"] > 0.99
                calls = provider.embed_batch.await_count
                response = await client.post(
                    "/api/embeddings/backfill", json={"document_id": ids[1]}
                )
                assert response.json()["processed"] == 0
                assert response.json()["remaining"] == 0
                assert provider.embed_batch.await_count == calls
                for change in ({"embedding_dimensions": 4}, {"embedding_model": "other-model"}):
                    incompatible = config.model_copy(update=change)
                    with pytest.raises(IngestionError) as failure:
                        await VectorRepository(app.state.neo4j, incompatible).ensure_index()
                    assert failure.value.code == "embedding_space_mismatch"
            finally:
                await clean(app.state.neo4j, ids)


async def test_backfill_partial_failure_retry_and_stale_claim():
    config = vector_settings(embedding_batch_size=1)
    app = create_app(config)
    provider = AsyncMock()
    app.dependency_overrides[get_embedding_provider] = lambda: provider
    doc = Document(
        id=str(uuid4()), filename="legacy.txt", file_type="txt", created_at=datetime.now(UTC)
    )
    chunks = [
        Chunk(id=str(uuid4()), document_id=doc.id, text=text, chunk_index=index)
        for index, text in enumerate(SAMPLES[:2])
    ]
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            try:
                await DocumentRepository(app.state.neo4j, 30).save(doc, chunks)
                repo = VectorRepository(app.state.neo4j, config)
                await repo.ensure_index()
                provider.embed_batch.side_effect = [
                    [[0.0, 1.0, 0.1]],
                    EmbeddingError("embedding_provider_error"),
                ]
                response = await client.post(
                    "/api/embeddings/backfill", json={"document_id": doc.id, "limit": 2}
                )
                assert response.status_code == 200, response.text
                body = response.json()
                assert body["updated"] == 1 and body["remaining"] == 1
                assert body["errors"] == [
                    {"chunk_id": chunks[1].id, "code": "embedding_provider_error"}
                ]
                assert await repo.search([0.0, 1.0, 0.1], 5) == []  # incomplete document excluded
                provider.embed_batch.side_effect = None
                provider.embed_batch.return_value = [[1.0, 0.0, 0.1]]
                response = await client.post(
                    "/api/embeddings/backfill", json={"document_id": doc.id}
                )
                assert response.json()["updated"] == 1
                assert response.json()["remaining"] == 0
                assert (await repo.summary(doc.id)).status == "completed"
                async with app.state.neo4j.driver.session(
                    database=config.neo4j_database
                ) as session:
                    result = await session.run(
                        "MATCH (c:Chunk {id: $id}) RETURN c.embedding AS vector", id=chunks[0].id
                    )
                    assert (await result.single())["vector"] == [0.0, 1.0, 0.1]
                    # Simulate an expired in-flight attempt for one missing vector.
                    await (
                        await session.run(
                            "MATCH (c:Chunk {id: $id}) REMOVE c.embedding "
                            "SET c.embedding_run_id = 'stale', "
                            "c.embedding_lease_until = datetime() - duration({seconds: 1})",
                            id=chunks[1].id,
                        )
                    ).consume()
                owner, pending = await repo.claim(doc.id, 2, [])
                assert [chunk.id for chunk in pending] == [chunks[1].id]
                _, competing = await repo.claim(doc.id, 2, [])
                assert competing == []
                assert await repo.store("stale", pending, [[0.9, 0.9, 0.1]]) == 0
                assert await repo.store(owner, pending, [[1.0, 0.0, 0.1]]) == 1
                assert await repo.store(owner, pending, [[0.9, 0.9, 0.1]]) == 0
                assert (await repo.summary(doc.id)).completed == 2
                missing = await client.post(
                    "/api/embeddings/backfill", json={"document_id": "missing"}
                )
                assert missing.status_code == 404
            finally:
                await clean(app.state.neo4j, [doc.id])


async def test_embedding_failure_keeps_existing_graph_pipeline():
    from graph_fixtures import SAMPLE, sample_extraction

    config = vector_settings()
    config.llm_extraction_enabled = True
    config.llm_model = "mock-structured-model"
    app = create_app(config)
    provider = AsyncMock()
    provider.embed_batch.side_effect = EmbeddingError("embedding_provider_unavailable")
    extraction = AsyncMock()
    extraction.extract.return_value = sample_extraction()
    app.dependency_overrides[get_embedding_provider] = lambda: provider
    app.dependency_overrides[get_extraction_provider] = lambda: extraction
    ids = []
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            try:
                response = await client.post(
                    "/api/documents/upload", files={"file": ("graph.txt", SAMPLE)}
                )
                assert response.status_code == 201, response.text
                body = response.json()
                ids.append(body["document"]["id"])
                assert body["embeddings"]["status"] == "failed"
                assert body["embeddings"]["errors"][0]["code"] == "embedding_provider_unavailable"
                assert body["extraction"]["status"] == "completed"
                async with app.state.neo4j.driver.session(
                    database=config.neo4j_database
                ) as session:
                    result = await session.run(
                        "MATCH (d:Document {id: $id})-[:HAS_CHUNK]->(:Chunk)"
                        "-[:MENTIONS]->(e:Entity) RETURN count(e) AS count",
                        id=ids[0],
                    )
                    assert (await result.single())["count"] == 4
            finally:
                # Remove only facts/mentions supported by this test; preserve shared entities.
                if ids:
                    async with app.state.neo4j.driver.session(
                        database=config.neo4j_database
                    ) as session:
                        await (
                            await session.run(
                                "MATCH ()-[r]->() WHERE r.source_document_id IN $ids DELETE r",
                                ids=ids,
                            )
                        ).consume()
                await clean(app.state.neo4j, ids)
