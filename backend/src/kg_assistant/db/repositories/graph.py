import asyncio
import json
import logging
from uuid import NAMESPACE_URL, uuid5

from neo4j import READ_ACCESS, unit_of_work
from neo4j.exceptions import DriverError, Neo4jError

from kg_assistant.core.config import Settings
from kg_assistant.core.exceptions import IngestionError
from kg_assistant.db.neo4j import Neo4jConnectionManager
from kg_assistant.models.graph import GraphNode, GraphResponse, VisualizationEdge

logger = logging.getLogger(__name__)

NODES = """
MATCH (e:Entity)
WHERE e.id IS NOT NULL AND e.name IS NOT NULL AND e.type IS NOT NULL
RETURN e.id AS id, e.name AS label, e.type AS type,
       substring(e.description, 0, 1000) AS description
ORDER BY id LIMIT $limit
"""
EDGES = """
MATCH (s:Entity)-[r]->(t:Entity)
WHERE s.id IN $ids AND t.id IN $ids
  AND type(r) IN $types AND NOT type(r) IN ['HAS_CHUNK', 'MENTIONS']
OPTIONAL MATCH (d:Document {id: r.source_document_id})
WITH s, r, t, d WHERE d IS NULL OR d.extraction_status = 'completed'
RETURN DISTINCT s.id AS source, t.id AS target, type(r) AS type
ORDER BY source, target, type LIMIT $limit
"""


class GraphVisualizationRepository:
    """Bounded read snapshot; merge parallel support edges for display, never mutate facts."""

    def __init__(self, connection: Neo4jConnectionManager, settings: Settings) -> None:
        self.connection = connection
        self.settings = settings

    async def snapshot(self, node_limit: int, edge_limit: int) -> GraphResponse:
        try:
            async with asyncio.timeout(self.settings.graph_retrieval_timeout):
                async with self.connection.driver.session(
                    database=self.settings.neo4j_database, default_access_mode=READ_ACCESS
                ) as session:

                    @unit_of_work(timeout=self.settings.graph_retrieval_timeout)
                    async def read(tx):
                        result = await tx.run(
                            NODES,
                            limit=node_limit + 1,
                        )
                        rows = [dict(row) async for row in result]
                        nodes = [GraphNode.model_validate(row) for row in rows[:node_limit]]
                        if not nodes:
                            return GraphResponse(nodes=[], edges=[])
                        result = await tx.run(
                            EDGES,
                            ids=[node.id for node in nodes],
                            types=self.settings.relationship_types,
                            limit=edge_limit + 1,
                        )
                        edges = [dict(row) async for row in result]
                        # Structured identity avoids collisions with arbitrary entity IDs/types.
                        mapped = [
                            VisualizationEdge(
                                id=str(uuid5(NAMESPACE_URL, json.dumps(row, sort_keys=True))),
                                **row,
                            )
                            for row in edges[:edge_limit]
                        ]
                        return GraphResponse(
                            nodes=nodes,
                            edges=mapped,
                            truncated=len(rows) > node_limit or len(edges) > edge_limit,
                        )

                    return await session.execute_read(read)
        except (Neo4jError, DriverError, TimeoutError, OSError) as exc:
            logger.warning("graph_snapshot_failed:%s", type(exc).__name__)
            raise IngestionError(
                "graph_unavailable", "Knowledge graph is temporarily unavailable", 503
            ) from exc
