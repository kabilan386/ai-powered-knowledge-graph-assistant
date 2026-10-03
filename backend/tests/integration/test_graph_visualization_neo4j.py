from uuid import uuid4

import httpx
from test_neo4j_upload import integration_settings, pytestmark  # noqa: F401

from kg_assistant.main import create_app


async def test_real_graph_snapshot_filters_and_read_only():
    settings = integration_settings()
    app = create_app(settings)
    ids = [str(uuid4()), str(uuid4())]
    doc_id = str(uuid4())
    async with app.router.lifespan_context(app):
        async with app.state.neo4j.driver.session(database=settings.neo4j_database) as session:
            try:
                await (
                    await session.run(
                        "CREATE (s:Entity {id:$source, name:'Snapshot Team', "
                        "type:'ORGANIZATION'}), "
                        "(t:Entity {id:$target, name:'Snapshot Service', type:'SERVICE'}), "
                        "(d:Document {id:$document, extraction_status:'completed'}), "
                        "(s)-[:MANAGES {source_document_id:$document}]->(t), "
                        "(s)-[:MANAGES {source_document_id:$document}]->(t), "
                        "(s)-[:MENTIONS]->(t), (s)-[:HAS_CHUNK]->(t)",
                        source=ids[0],
                        target=ids[1],
                        document=doc_id,
                    )
                ).consume()
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.get("/api/graph?node_limit=200&edge_limit=400")
                    assert response.status_code == 200
                    data = response.json()
                    edges = [edge for edge in data["edges"] if edge["source"] == ids[0]]
                    assert len(edges) == 1 and edges[0]["type"] == "MANAGES"
                    assert {node["id"] for node in data["nodes"]}.issuperset(ids)
                    await (
                        await session.run(
                            "MATCH (d:Document {id:$id}) SET d.extraction_status='partial'",
                            id=doc_id,
                        )
                    ).consume()
                    data = (await client.get("/api/graph?node_limit=200&edge_limit=400")).json()
                    assert not any(edge["source"] == ids[0] for edge in data["edges"])
                    # Reads did not remove either support edge or infrastructure relationships.
                    result = await session.run(
                        "MATCH (s:Entity {id:$id})-[r]->() RETURN count(r) AS count", id=ids[0]
                    )
                    assert (await result.single())["count"] == 4
            finally:
                await (
                    await session.run(
                        "MATCH (e:Entity) WHERE e.id IN $ids DETACH DELETE e", ids=ids
                    )
                ).consume()
                await (
                    await session.run("MATCH (d:Document {id:$id}) DETACH DELETE d", id=doc_id)
                ).consume()
