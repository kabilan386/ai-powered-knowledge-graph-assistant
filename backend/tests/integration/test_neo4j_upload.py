import os
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from document_fixtures import docx_bytes, pdf_bytes

from kg_assistant.core.config import Settings
from kg_assistant.db.repositories.documents import DocumentRepository
from kg_assistant.main import create_app
from kg_assistant.models.documents import Chunk, Document

pytestmark = [
    pytest.mark.neo4j,
    pytest.mark.skipif(
        os.getenv("KG_RUN_NEO4J_TESTS") != "1", reason="Opt-in real Neo4j tests are disabled"
    ),
]


def integration_settings() -> Settings:
    password = os.getenv("TEST_NEO4J_PASSWORD")
    if not password:
        pytest.fail("Set TEST_NEO4J_PASSWORD for the isolated test database")
    return Settings(
        _env_file=None,
        neo4j_uri=os.getenv("TEST_NEO4J_URI", "bolt://localhost:7687"),
        neo4j_username=os.getenv("TEST_NEO4J_USERNAME", "neo4j"),
        neo4j_database=os.getenv("TEST_NEO4J_DATABASE", "neo4j"),
        neo4j_password=password,
        chunk_size=20,
        chunk_overlap=5,
    )


@pytest.mark.parametrize(
    "filename,content,pages",
    [
        ("integration.txt", b"Integration text longer than a chunk", None),
        ("integration.pdf", pdf_bytes(["First page", "Second page"]), [1, 2]),
        ("integration.docx", docx_bytes(), None),
    ],
)
async def test_upload_stores_real_graph(filename, content, pages):
    config = integration_settings()
    app = create_app(config)
    document_id = None
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            try:
                response = await client.post(
                    "/api/documents/upload", files={"file": (filename, content)}
                )
                assert response.status_code == 201, response.text
                body = response.json()
                document_id = body["document"]["id"]
                async with app.state.neo4j.driver.session(
                    database=config.neo4j_database
                ) as session:
                    result = await session.run(
                        "MATCH (d:Document {id: $id})-[:HAS_CHUNK]->(c:Chunk) "
                        "RETURN d.filename AS filename, d.file_type AS file_type, "
                        "d.created_at AS created_at, c.document_id AS document_id, "
                        "c.text AS text, c.chunk_index AS chunk_index, "
                        "c.page_number AS page_number "
                        "ORDER BY c.chunk_index",
                        id=document_id,
                    )
                    records = [dict(record) async for record in result]
                assert len(records) == body["chunk_count"]
                assert [r["chunk_index"] for r in records] == list(range(len(records)))
                assert all(
                    r["filename"] == filename and r["document_id"] == document_id for r in records
                )
                assert all(r["text"] and r["created_at"] is not None for r in records)
                if pages is None:
                    assert all(r["page_number"] is None for r in records)
                else:
                    assert [r["page_number"] for r in records] == pages
            finally:
                if document_id:
                    async with app.state.neo4j.driver.session(
                        database=config.neo4j_database
                    ) as session:
                        result = await session.run(
                            "MATCH (d:Document {id: $id}) "
                            "OPTIONAL MATCH (d)-[:HAS_CHUNK]->(c:Chunk) "
                            "DETACH DELETE d, c",
                            id=document_id,
                        )
                        await result.consume()


async def test_repository_retry_and_rollback(monkeypatch):
    config = integration_settings()
    app = create_app(config)
    doc = Document(
        id=str(uuid4()), filename="retry.txt", file_type="txt", created_at=datetime.now(UTC)
    )
    chunks = [
        Chunk(
            id=str(uuid4()), document_id=doc.id, text="' }) CREATE (:Unexpected) //", chunk_index=0
        )
    ]
    failed_doc = Document(
        id=str(uuid4()), filename="rollback.txt", file_type="txt", created_at=datetime.now(UTC)
    )
    failed_chunks = [
        Chunk(id=str(uuid4()), document_id=failed_doc.id, text="rollback", chunk_index=0)
    ]
    async with app.router.lifespan_context(app):
        repo = DocumentRepository(app.state.neo4j, config.neo4j_write_timeout)
        try:
            await repo.save(doc, chunks)
            await repo.save(doc, chunks)
            async with app.state.neo4j.driver.session(database=config.neo4j_database) as session:
                result = await session.run(
                    "MATCH (d:Document {id: $id})-[r:HAS_CHUNK]->(c:Chunk) "
                    "RETURN count(r) AS edges, collect(c.text) AS texts",
                    id=doc.id,
                )
                record = await result.single()
                assert record["edges"] == 1
                assert record["texts"] == [chunks[0].text]

            async def fail_after_write(tx, document, chunk_data):
                await DocumentRepository._save_transaction(tx, document, chunk_data)
                raise RuntimeError("Simulated failure before commit")

            monkeypatch.setattr(repo, "_save_transaction", fail_after_write)
            with pytest.raises(RuntimeError):
                await repo.save(failed_doc, failed_chunks)
            async with app.state.neo4j.driver.session(database=config.neo4j_database) as session:
                result = await session.run(
                    "MATCH (n) WHERE n.id IN $ids RETURN count(n) AS count",
                    ids=[failed_doc.id, failed_chunks[0].id],
                )
                assert (await result.single())["count"] == 0
        finally:
            async with app.state.neo4j.driver.session(database=config.neo4j_database) as session:
                result = await session.run(
                    "MATCH (n) WHERE n.id IN $ids DETACH DELETE n",
                    ids=[doc.id, chunks[0].id, failed_doc.id, failed_chunks[0].id],
                )
                await result.consume()
