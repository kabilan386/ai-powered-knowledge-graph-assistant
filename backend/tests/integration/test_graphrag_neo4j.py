from unittest.mock import AsyncMock

import httpx
from document_fixtures import pdf_bytes
from graphrag_fixtures import QUESTION, TEXTS, config
from test_neo4j_upload import integration_settings, pytestmark  # noqa: F401

from kg_assistant.api.dependencies import (
    get_answer_provider,
    get_embedding_provider,
    get_extraction_provider,
    get_query_entity_provider,
)
from kg_assistant.main import create_app
from kg_assistant.models.extraction import ExtractedEntity, ExtractedRelationship, ExtractionResult
from kg_assistant.models.graph_retrieval import QueryEntity, QueryExtraction
from kg_assistant.models.graphrag import GroundedAnswer


def extract_chunk(text):
    index = next(i for i, sample in enumerate(TEXTS) if sample in text)
    source, target, source_type, target_type, kind = [
        ("Platform Team", "Payment Service", "ORGANIZATION", "SERVICE", "MANAGES"),
        ("Payment Service", "Redis", "SERVICE", "TECHNOLOGY", "USES"),
        ("Redis", "AWS ElastiCache", "TECHNOLOGY", "CLOUD_SERVICE", "HOSTED_ON"),
    ][index]
    return ExtractionResult(
        entities=[
            ExtractedEntity(key="s", name=source, type=source_type, evidence_quote=source),
            ExtractedEntity(key="t", name=target, type=target_type, evidence_quote=target),
        ],
        relationships=[
            ExtractedRelationship(source="s", target="t", type=kind, evidence_quote=TEXTS[index])
        ],
    )


async def test_real_upload_hybrid_answer_citations_and_insufficient_evidence():
    settings = config()
    neo = integration_settings()
    settings.neo4j_uri = neo.neo4j_uri
    settings.neo4j_password = neo.neo4j_password
    settings.neo4j_database = neo.neo4j_database
    settings.llm_extraction_enabled = True
    app = create_app(settings)
    embeddings, extraction, query, answer = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    embeddings.embed_batch.side_effect = lambda texts: [[1.0, 0.1, 0.1] for text in texts]
    extraction.extract.side_effect = extract_chunk
    query.extract.return_value = QueryExtraction(
        entities=[QueryEntity(name="Platform Team", type="ORGANIZATION")],
        relationship_types=["MANAGES", "USES", "HOSTED_ON"],
        target_type="CLOUD_SERVICE",
        direction="outgoing",
    )
    captured = []

    async def generate(question, context):
        captured.append(context)
        if "CEO" in question:
            return GroundedAnswer(
                answer="CEO information is absent.", citations=[], insufficient_evidence=True
            )
        # Assert that both real Neo4j retrievers contributed to the fused evidence.
        assert context.text_evidence and context.graph_evidence
        path = context.graph_evidence[0]
        assert [edge.type for edge in path.edges] == ["MANAGES", "USES", "HOSTED_ON"]
        assert all(edge.document_backed for edge in path.edges)
        citations = [edge.source_citations[0] for edge in path.edges]
        return GroundedAnswer(
            answer=f"The Payment Service managed by Platform Team [{citations[0]}] "
            f"uses Redis [{citations[1]}], which is hosted on AWS ElastiCache [{citations[2]}].",
            citations=citations,
            insufficient_evidence=False,
        )

    answer.generate.side_effect = generate
    app.dependency_overrides[get_embedding_provider] = lambda: embeddings
    app.dependency_overrides[get_extraction_provider] = lambda: extraction
    app.dependency_overrides[get_query_entity_provider] = lambda: query
    app.dependency_overrides[get_answer_provider] = lambda: answer
    document_id = None
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            try:
                response = await client.post(
                    "/api/documents/upload",
                    files={"file": ("graphrag-sample.pdf", pdf_bytes(TEXTS))},
                )
                assert response.status_code == 201, response.text
                body = response.json()
                document_id = body["document"]["id"]
                assert body["chunk_count"] == 3
                assert (
                    body["extraction"]["status"] == "completed"
                    and body["embeddings"]["status"] == "completed"
                )
                response = await client.post("/api/graphrag/ask", json={"question": QUESTION})
                assert response.status_code == 200, response.text
                result = response.json()
                assert not result["insufficient_evidence"] and len(result["sources"]) == 3
                assert (
                    result["retrieval"]["vector_results"] >= 3
                    and result["retrieval"]["graph_paths"] >= 1
                )
                assert (
                    len(captured[0].text_evidence) == 3
                )  # graph/vector duplicate chunks fused once
                assert result["retrieval"]["context_graph_paths"] == 1  # redundant prefixes removed
                assert "AWS ElastiCache" in result["answer"]
                async with app.state.neo4j.driver.session(
                    database=settings.neo4j_database
                ) as session:
                    for source in result["sources"]:
                        record = await (
                            await session.run(
                                "MATCH (d:Document {id:$doc})-[:HAS_CHUNK]->(c:Chunk {id:$chunk}) "
                                "RETURN d.filename AS filename, c.text AS text, "
                                "c.chunk_index AS chunk_index, c.page_number AS page_number",
                                doc=source["document_id"],
                                chunk=source["chunk_id"],
                            )
                        ).single()
                        assert record is not None
                        assert source["filename"] == record["filename"]
                        assert source["page_number"] == record["page_number"]
                        assert source["chunk_index"] == record["chunk_index"]
                        assert source["excerpt"] in record["text"]
                print("Combined answer:", result["answer"])
                query.extract.return_value = QueryExtraction(
                    entities=[QueryEntity(name="Payment Service", type="SERVICE")]
                )
                response = await client.post(
                    "/api/graphrag/ask", json={"question": "Who is the CEO of Payment Service?"}
                )
                assert response.status_code == 200, response.text
                result = response.json()
                assert (
                    result["insufficient_evidence"]
                    and result["citations"] == []
                    and result["sources"] == []
                )
                print("Insufficient evidence:", result["answer"])
            finally:
                if document_id:
                    async with app.state.neo4j.driver.session(
                        database=settings.neo4j_database
                    ) as session:
                        await (
                            await session.run(
                                "MATCH ()-[r]->() WHERE r.source_document_id=$id DELETE r",
                                id=document_id,
                            )
                        ).consume()
                        await (
                            await session.run(
                                "MATCH (d:Document {id:$id}) "
                                "OPTIONAL MATCH (d)-[:HAS_CHUNK]->(c:Chunk) DETACH DELETE d,c",
                                id=document_id,
                            )
                        ).consume()
