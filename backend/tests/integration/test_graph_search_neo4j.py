from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx
from pydantic import SecretStr
from test_graph_retrieval import QUESTIONS, intent_for
from test_neo4j_upload import integration_settings, pytestmark  # noqa: F401

from kg_assistant.api.dependencies import get_query_entity_provider
from kg_assistant.db.repositories.documents import DocumentRepository
from kg_assistant.ingestion.normalization import normalize_name
from kg_assistant.main import create_app
from kg_assistant.models.documents import Chunk, Document
from kg_assistant.models.graph_retrieval import QueryEntity, QueryExtraction


async def test_real_multi_hop_read_only_ranking_and_provenance():
    config = integration_settings()
    config.graph_retrieval_enabled = True
    config.openai_api_key = SecretStr("mock-only")
    config.llm_model = "mock-structured"
    app = create_app(config)
    provider = AsyncMock()
    app.dependency_overrides[get_query_entity_provider] = lambda: provider
    doc = Document(
        id=str(uuid4()), filename="technical.pdf", file_type="pdf", created_at=datetime.now(UTC)
    )
    chunk = Chunk(
        id=str(uuid4()),
        document_id=doc.id,
        text="Test graph evidence",
        chunk_index=7,
        page_number=3,
    )
    definitions = [
        ("Platform Team", "ORGANIZATION"),
        ("Payment Service", "SERVICE"),
        ("Redis", "TECHNOLOGY"),
        ("AWS ElastiCache", "CLOUD_SERVICE"),
        ("PostgreSQL", "DATABASE"),
        ("Analytics Team", "ORGANIZATION"),
        ("Analytics Service", "SERVICE"),
        ("Neo4j", "TECHNOLOGY"),
    ]
    entities = [
        dict(
            id=str(uuid5(NAMESPACE_URL, f"entity:{kind}:{normalize_name(name)}")),
            name=name,
            type=kind,
            normalized_name=normalize_name(name),
        )
        for name, kind in definitions
    ]
    facts = [
        (0, "MANAGES", 1),
        (1, "USES", 2),
        (2, "HOSTED_ON", 3),
        (1, "DEPENDS_ON", 4),
        (5, "MANAGES", 6),
        (6, "USES", 7),
        (2, "RELATED_TO", 0),
        (0, "MENTIONS", 7),
    ]
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            async with app.state.neo4j.driver.session(database=config.neo4j_database) as session:
                try:
                    await DocumentRepository(app.state.neo4j, 30).save(doc, [chunk])
                    await (
                        await session.run(
                            "UNWIND $entities AS item "
                            "MERGE (e:Entity {type:item.type, "
                            "normalized_name:item.normalized_name}) "
                            "ON CREATE SET e.id=item.id, e.name=item.name",
                            entities=entities,
                        )
                    ).consume()
                    for source, kind, target in facts:
                        # Fixed fixture allowlist, no query/API input can supply these identifiers.
                        await (
                            await session.run(
                                f"MATCH (s:Entity {{id:$source}}),(t:Entity {{id:$target}}) "
                                f"CREATE (s)-[r:{kind} {{id:$id, source_chunk_id:$chunk, "
                                "source_document_id:$doc, evidence_quote:$quote}]->(t)",
                                source=entities[source]["id"],
                                target=entities[target]["id"],
                                id=str(uuid4()),
                                chunk=chunk.id,
                                doc=doc.id,
                                quote=f"{definitions[source][0]} {kind} {definitions[target][0]}",
                            )
                        ).consume()
                    await (
                        await session.run(
                            "MATCH (d:Document {id:$id}) SET d.extraction_status='completed'",
                            id=doc.id,
                        )
                    ).consume()
                    before = await (
                        await session.run("MATCH (n) RETURN count(n) AS count")
                    ).single()
                    edges_before = await (
                        await session.run("MATCH ()-[r]->() RETURN count(r) AS count")
                    ).single()
                    for index, (question, _, expected, _) in enumerate(QUESTIONS):
                        provider.extract.return_value = intent_for(index)
                        response = await client.post(
                            "/api/retrieval/graph-search", json={"query": question, "max_hops": 3}
                        )
                        assert response.status_code == 200, response.text
                        body = response.json()
                        assert body["status"] == "ok"
                        assert body["paths"][0]["relationships"] == expected
                        assert body["paths"][0]["hop_count"] == len(expected)
                        assert all(
                            len({node["id"] for node in path["nodes"]}) == len(path["nodes"])
                            for path in body["paths"]
                        )
                        assert all(
                            "MENTIONS" not in path["relationships"] for path in body["paths"]
                        )
                        assert not any(
                            "Analytics" in node["name"]
                            for path in body["paths"]
                            for node in path["nodes"]
                        )
                        evidence = body["paths"][0]["edges"][0]["evidence"][0]
                        assert (
                            evidence["document_id"] == doc.id and evidence["chunk_id"] == chunk.id
                        )
                        assert (
                            evidence["filename"] == "technical.pdf"
                            and evidence["page_number"] == 3
                            and evidence["chunk_index"] == 7
                        )
                        if index == 3:
                            print(
                                "Three-hop result:",
                                " -> ".join(node["name"] for node in body["paths"][0]["nodes"]),
                            )
                            print("Relationships:", body["paths"][0]["relationships"])
                    provider.extract.return_value = intent_for(3)
                    result = await client.post(
                        "/api/retrieval/graph-search",
                        json={"query": QUESTIONS[3][0], "max_hops": 2},
                    )
                    assert all(path["hop_count"] <= 2 for path in result.json()["paths"])
                    # Case-folded anchor and a reverse traversal preserve the stored edge direction.
                    provider.extract.return_value = QueryExtraction(
                        entities=[QueryEntity(name="payment service", type="SERVICE")],
                        relationship_types=["MANAGES"],
                        direction="incoming",
                    )
                    result = await client.post(
                        "/api/retrieval/graph-search",
                        json={"query": "Who manages PAYMENT SERVICE?", "max_hops": 1},
                    )
                    path = result.json()["paths"][0]
                    assert (
                        path["nodes"][0]["name"] == "Payment Service"
                        and path["nodes"][1]["name"] == "Platform Team"
                    )
                    assert path["edges"][0]["source_id"] == entities[0]["id"]
                    provider.extract.return_value = QueryExtraction(
                        entities=[QueryEntity(name="Missing Service", type="SERVICE")]
                    )
                    result = await client.post(
                        "/api/retrieval/graph-search", json={"query": "Who uses Missing Service?"}
                    )
                    assert (
                        result.json()["status"] == "unresolved_anchors"
                        and result.json()["paths"] == []
                    )
                    provider.extract.return_value = QueryExtraction(entities=[])
                    result = await client.post(
                        "/api/retrieval/graph-search", json={"query": "What is available?"}
                    )
                    assert result.json()["status"] == "no_anchors"
                    # Preserve publication semantics while a supported document is incomplete.
                    provider.extract.return_value = intent_for(3)
                    await (
                        await session.run(
                            "MATCH (d:Document {id:$id}) SET d.extraction_status='partial'",
                            id=doc.id,
                        )
                    ).consume()
                    result = await client.post(
                        "/api/retrieval/graph-search", json={"query": QUESTIONS[3][0]}
                    )
                    assert result.json()["status"] == "no_paths"
                    await (
                        await session.run(
                            "MATCH (d:Document {id:$id}) SET d.extraction_status='completed'",
                            id=doc.id,
                        )
                    ).consume()
                    after = await (await session.run("MATCH (n) RETURN count(n) AS count")).single()
                    edges_after = await (
                        await session.run("MATCH ()-[r]->() RETURN count(r) AS count")
                    ).single()
                    assert (
                        before["count"] == after["count"]
                        and edges_before["count"] == edges_after["count"]
                    )
                finally:
                    await (
                        await session.run(
                            "MATCH ()-[r]->() WHERE r.source_document_id=$id DELETE r", id=doc.id
                        )
                    ).consume()
                    await (
                        await session.run(
                            "MATCH (n) WHERE n.id IN $ids DETACH DELETE n", ids=[doc.id, chunk.id]
                        )
                    ).consume()
