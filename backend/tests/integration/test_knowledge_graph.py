import os
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from graph_fixtures import SAMPLE, sample_extraction

from kg_assistant.core.config import Settings
from kg_assistant.core.exceptions import IngestionError
from kg_assistant.db.repositories.knowledge_graph import KnowledgeGraphRepository
from kg_assistant.ingestion.normalization import normalize_extraction
from kg_assistant.main import create_app
from kg_assistant.providers.base import ExtractionError

pytestmark = [
    pytest.mark.neo4j,
    pytest.mark.skipif(
        os.getenv("KG_RUN_NEO4J_TESTS") != "1", reason="Real Neo4j tests are disabled"
    ),
]


def graph_config() -> Settings:
    password = os.getenv("TEST_NEO4J_PASSWORD")
    if not password:
        pytest.fail("Set TEST_NEO4J_PASSWORD")
    return Settings(
        _env_file=None,
        neo4j_password=password,
        neo4j_uri=os.getenv("TEST_NEO4J_URI", "bolt://localhost:7687"),
        neo4j_database=os.getenv("TEST_NEO4J_DATABASE", "neo4j"),
        neo4j_username=os.getenv("TEST_NEO4J_USERNAME", "neo4j"),
        llm_extraction_enabled=True,
        openai_api_key="mock-key",
        llm_model="mock-model",
        llm_retry_backoff=0,
        chunk_size=1000,
        chunk_overlap=0,
    )


async def cleanup(app, config, ids):
    entity_ids = [e.id for e in normalize_extraction(sample_extraction()).entities]
    async with app.state.neo4j.driver.session(database=config.neo4j_database) as session:
        await (
            await session.run(
                "MATCH (:Entity)-[r]->(:Entity) WHERE r.source_document_id IN $ids DELETE r",
                ids=ids,
            )
        ).consume()
        await (
            await session.run(
                "MATCH (d:Document) WHERE d.id IN $ids OPTIONAL MATCH (d)-[:HAS_CHUNK]->(c:Chunk) "
                "DETACH DELETE d,c",
                ids=ids,
            )
        ).consume()
        await (
            await session.run(
                "MATCH (e:Entity) WHERE e.id IN $ids AND NOT (e)--() DELETE e",
                ids=entity_ids,
            )
        ).consume()


async def test_sample_graph_normalization_and_provenance():
    config = graph_config()
    provider = AsyncMock()
    lowercase = sample_extraction()
    for entity in lowercase.entities:
        entity.name = entity.name.replace("Redis", "redis")
        entity.evidence_quote = entity.evidence_quote.replace("Redis", "redis")
    for relationship in lowercase.relationships:
        relationship.evidence_quote = relationship.evidence_quote.replace("Redis", "redis")
    provider.extract.side_effect = [sample_extraction(), lowercase]
    app = create_app(config)
    ids = []
    with patch("kg_assistant.main.OpenAIExtractionProvider", return_value=provider):
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                try:
                    for text in (SAMPLE, SAMPLE.replace("Redis", "redis")):
                        response = await client.post(
                            "/api/documents/upload", files={"file": ("sample.txt", text.encode())}
                        )
                        assert response.status_code == 201, response.text
                        body = response.json()
                        ids.append(body["document"]["id"])
                        assert body["extraction"]["status"] == "completed"
                    async with app.state.neo4j.driver.session(
                        database=config.neo4j_database
                    ) as session:
                        result = await session.run(
                            "MATCH (d:Document)-[:HAS_CHUNK]->(c:Chunk)-[:MENTIONS]->(e:Entity) "
                            "WHERE d.id IN $ids RETURN count(DISTINCT e) AS entities, "
                            "count(*) AS mentions",
                            ids=ids,
                        )
                        record = await result.single()
                        assert record["entities"] == 4 and record["mentions"] == 8
                        result = await session.run(
                            "MATCH (s:Entity)-[r]->(t:Entity) WHERE r.source_document_id IN $ids "
                            "RETURN s.name AS source, type(r) AS type, t.name AS target, "
                            "r.source_chunk_id AS chunk_id, r.evidence_quote AS quote",
                            ids=ids,
                        )
                        records = [dict(r) async for r in result]
                        assert len(records) == 6
                        assert {(r["source"], r["type"], r["target"]) for r in records} == {
                            ("Platform Team", "MANAGES", "Payment Service"),
                            ("Payment Service", "USES", "Redis"),
                            ("Redis", "HOSTED_ON", "AWS ElastiCache"),
                        }
                        assert all(r["chunk_id"] and r["quote"] for r in records)
                    retry = await client.post(f"/api/documents/{ids[0]}/extract")
                    assert retry.json()["completed"] == 1
                    assert provider.extract.await_count == 2
                finally:
                    await cleanup(app, config, ids)
    provider.close.assert_awaited_once()


async def test_failed_chunk_retry_and_empty_extraction():
    config = graph_config()
    config.chunk_size = len(SAMPLE) + 1
    provider = AsyncMock()
    provider.extract.side_effect = [
        sample_extraction(),
        ExtractionError("llm_invalid_response"),
        ExtractionError("llm_invalid_response"),
    ]
    app = create_app(config)
    ids = []
    with patch("kg_assistant.main.OpenAIExtractionProvider", return_value=provider):
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                try:
                    response = await client.post(
                        "/api/documents/upload",
                        files={"file": ("failed.txt", (SAMPLE + "\n" + SAMPLE).encode())},
                    )
                    body = response.json()
                    ids.append(body["document"]["id"])
                    assert body["extraction"]["status"] == "partial"
                    assert body["extraction"]["completed"] == 1
                    assert body["extraction"]["errors"][0]["attempts"] == 2
                    async with app.state.neo4j.driver.session(
                        database=config.neo4j_database
                    ) as session:
                        result = await session.run(
                            "MATCH (:Document {id: $id})-[:HAS_CHUNK]->(c:Chunk) "
                            "OPTIONAL MATCH (c)-[m:MENTIONS]->() "
                            "RETURN count(DISTINCT c) AS chunks, count(m) AS mentions",
                            id=ids[0],
                        )
                        record = await result.single()
                        assert record["chunks"] == 2 and record["mentions"] == 4
                    provider.extract.side_effect = None
                    provider.extract.return_value = sample_extraction()
                    response = await client.post(f"/api/documents/{ids[0]}/extract")
                    assert response.json()["status"] == "completed"
                    empty = type(sample_extraction())(entities=[], relationships=[])
                    provider.extract.return_value = empty
                    response = await client.post(
                        "/api/documents/upload",
                        files={"file": ("empty-entities.txt", b"No entities")},
                    )
                    ids.append(response.json()["document"]["id"])
                    assert response.json()["extraction"]["status"] == "completed"
                finally:
                    await cleanup(app, config, ids)


async def test_per_chunk_rollback_lease_and_idempotency(monkeypatch):
    config = graph_config()
    # Upload raw chunks with extraction disabled, then exercise the graph transaction directly.
    config.llm_extraction_enabled = False
    app = create_app(config)
    ids = []
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            try:
                response = await client.post(
                    "/api/documents/upload", files={"file": ("atomic.txt", SAMPLE.encode())}
                )
                ids.append(response.json()["document"]["id"])
                repo = KnowledgeGraphRepository(
                    app.state.neo4j, 30, config.entity_types, config.relationship_types, 120
                )
                token = await repo.begin(ids[0])
                with pytest.raises(IngestionError) as caught:
                    await repo.begin(ids[0])
                assert caught.value.status_code == 409
                chunk = (await repo.pending_chunks(ids[0]))[0]
                normalized = normalize_extraction(sample_extraction())
                original = repo._save_transaction

                async def fail_after_write(*args):
                    await original(*args)
                    raise RuntimeError("Simulated failure")

                monkeypatch.setattr(repo, "_save_transaction", fail_after_write)
                with pytest.raises(RuntimeError):
                    await repo.save_chunk(chunk, normalized, 1, token, "mock-model")
                async with app.state.neo4j.driver.session(
                    database=config.neo4j_database
                ) as session:
                    result = await session.run(
                        "MATCH (c:Chunk {id: $id}) OPTIONAL MATCH (c)-[m:MENTIONS]->() "
                        "RETURN count(m) AS mentions, c.extraction_status AS status",
                        id=chunk.id,
                    )
                    record = await result.single()
                    assert record["mentions"] == 0 and record["status"] == "disabled"
                monkeypatch.setattr(repo, "_save_transaction", original)
                async with app.state.neo4j.driver.session(
                    database=config.neo4j_database
                ) as session:
                    await (
                        await session.run(
                            "MATCH (d:Document {id: $id}) SET d.extraction_lease_until = "
                            "datetime() - duration({seconds: 1})",
                            id=ids[0],
                        )
                    ).consume()
                new_token = await repo.begin(ids[0])
                with pytest.raises(IngestionError) as caught:
                    await repo.save_chunk(chunk, normalized, 1, token, "mock-model")
                assert caught.value.code == "extraction_superseded"
                token = new_token
                await repo.save_chunk(chunk, normalized, 1, token, "mock-model")
                await repo.save_chunk(chunk, normalized, 1, token, "mock-model")
                assert (await repo.finish(ids[0], token)).status == "completed"
                async with app.state.neo4j.driver.session(
                    database=config.neo4j_database
                ) as session:
                    result = await session.run(
                        "MATCH (:Entity)-[r]->(:Entity) WHERE r.source_chunk_id = $id "
                        "RETURN count(r) AS count",
                        id=chunk.id,
                    )
                    assert (await result.single())["count"] == 3
            finally:
                await cleanup(app, config, ids)
