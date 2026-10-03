from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from neo4j import READ_ACCESS
from neo4j.exceptions import ServiceUnavailable

from kg_assistant.api.dependencies import get_graph_visualization
from kg_assistant.core.exceptions import IngestionError
from kg_assistant.db.repositories.graph import EDGES, NODES, GraphVisualizationRepository
from kg_assistant.main import create_app
from kg_assistant.models.graph import GraphResponse


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def __aiter__(self):
        async def iterate():
            for row in self.rows:
                yield row

        return iterate()


def repository(settings, nodes, edges):
    connection = MagicMock()
    session = AsyncMock()
    connection.driver.session.return_value.__aenter__.return_value = session
    tx = AsyncMock()
    tx.run.side_effect = [Rows(nodes), Rows(edges)]

    async def read(callback):
        return await callback(tx)

    session.execute_read.side_effect = read
    return GraphVisualizationRepository(connection, settings), connection, tx


async def test_read_snapshot_and_stable_edge_identity(settings):
    nodes = [
        {"id": "team", "label": "Platform Team", "type": "ORGANIZATION", "description": None},
        {"id": "service", "label": "Payment Service", "type": "SERVICE", "description": "API"},
    ]
    edges = [{"source": "team", "target": "service", "type": "MANAGES"}]
    repo, connection, tx = repository(settings, nodes, edges)
    result = await repo.snapshot(100, 200)
    assert result.nodes[1].description == "API"
    assert result.edges[0].source == "team"
    assert not result.truncated
    connection.driver.session.assert_called_once_with(
        database=settings.neo4j_database, default_access_mode=READ_ACCESS
    )
    assert tx.run.call_args_list[0].kwargs == {"limit": 101}
    assert tx.run.call_args_list[1].kwargs["ids"] == ["team", "service"]
    assert tx.run.call_args_list[1].kwargs["limit"] == 201
    other, _, _ = repository(settings, nodes, edges)
    assert (await other.snapshot(100, 200)).edges[0].id == result.edges[0].id
    assert "DISTINCT" in EDGES
    assert "['HAS_CHUNK', 'MENTIONS']" in EDGES
    assert "d.extraction_status = 'completed'" in EDGES
    assert all(word not in (NODES + EDGES).upper() for word in ["CREATE ", "MERGE ", "DELETE "])


async def test_snapshot_limits_and_empty(settings):
    nodes = [
        {"id": str(i), "label": str(i), "type": "CONCEPT", "description": None} for i in range(3)
    ]
    edges = [
        {"source": "0", "target": "1", "type": "RELATED_TO"},
        {"source": "1", "target": "0", "type": "USES"},
    ]
    repo, _, _ = repository(settings, nodes, edges)
    result = await repo.snapshot(2, 1)
    assert len(result.nodes) == 2 and len(result.edges) == 1 and result.truncated
    repo, _, tx = repository(settings, [], [])
    assert (await repo.snapshot(2, 1)).model_dump() == {
        "nodes": [],
        "edges": [],
        "truncated": False,
    }
    assert tx.run.await_count == 1


@pytest.mark.parametrize("error", [ServiceUnavailable("private"), TimeoutError()])
async def test_snapshot_failure(settings, error):
    repo, connection, _ = repository(settings, [], [])
    connection.driver.session.side_effect = error
    with pytest.raises(IngestionError) as captured:
        await repo.snapshot(100, 200)
    assert captured.value.status_code == 503
    assert "private" not in captured.value.message


def test_endpoint_validation_and_dependency(settings):
    app = create_app(settings)
    repo = MagicMock()
    repo.snapshot = AsyncMock(return_value=GraphResponse(nodes=[], edges=[]))
    app.dependency_overrides[get_graph_visualization] = lambda: repo
    driver = MagicMock()
    driver.close = AsyncMock()
    with patch("kg_assistant.db.neo4j.AsyncGraphDatabase.driver", return_value=driver):
        with TestClient(app) as client:
            assert client.get("/api/graph").json() == {"nodes": [], "edges": [], "truncated": False}
            repo.snapshot.assert_awaited_once_with(100, 200)
            for query in ["node_limit=0", "node_limit=201", "edge_limit=401", "edge_limit=-1"]:
                assert client.get(f"/api/graph?{query}").status_code == 422
            repo.snapshot.side_effect = IngestionError("graph_unavailable", "Try again", 503)
            assert client.get("/api/graph").status_code == 503
