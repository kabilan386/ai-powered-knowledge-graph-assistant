from neo4j import AsyncManagedTransaction

from kg_assistant.core.config import Settings
from kg_assistant.ingestion.normalization import normalize_name
from kg_assistant.models.graph_retrieval import (
    GraphEdge,
    GraphEntity,
    QueryEntity,
    RelationshipEvidence,
)

RESOLVE = """
MATCH (e:Entity {normalized_name: $name})
WHERE $type IS NULL OR e.type = $type
RETURN e.id AS id, e.name AS name, e.type AS type
ORDER BY e.type, e.id LIMIT $limit
"""
NEIGHBORS = """
MATCH (e:Entity {id: $id})-[r]-(n:Entity)
WHERE type(r) IN $types AND NOT type(r) IN ['HAS_CHUNK', 'MENTIONS']
  AND n.id <> e.id
  AND ($direction = 'both' OR
       ($direction = 'outgoing' AND startNode(r) = e) OR
       ($direction = 'incoming' AND endNode(r) = e))
OPTIONAL MATCH (d:Document {id: r.source_document_id})
WITH e, r, n, d WHERE d IS NULL OR d.extraction_status = 'completed'
RETURN DISTINCT n.id AS id, n.name AS name, n.type AS type,
       type(r) AS relationship_type, startNode(r).id AS source_id,
       endNode(r).id AS target_id
ORDER BY relationship_type, source_id, target_id LIMIT $limit
"""
EVIDENCE = """
MATCH (s:Entity {id: $source})-[r]->(t:Entity {id: $target})
WHERE type(r) = $type
OPTIONAL MATCH (origin:Document {id: r.source_document_id})
WITH r, origin WHERE origin IS NULL OR origin.extraction_status = 'completed'
OPTIONAL MATCH (d:Document {id: r.source_document_id})-[:HAS_CHUNK]->
               (c:Chunk {id: r.source_chunk_id})
RETURN r.id AS relationship_id, r.source_chunk_id AS chunk_id,
       r.source_document_id AS document_id, r.evidence_quote AS evidence_quote,
       d.filename AS filename, c.page_number AS page_number, c.chunk_index AS chunk_index
ORDER BY document_id, chunk_id, relationship_id LIMIT $limit
"""


class GraphRetrievalRepository:
    """Bounded single-hop reads in one request-scoped read transaction; never performs DDL."""

    def __init__(self, tx: AsyncManagedTransaction, settings: Settings) -> None:
        self.tx = tx
        self.settings = settings

    async def _read(self, statement: str, **params) -> list[dict]:
        result = await self.tx.run(statement, **params)
        return [dict(row) async for row in result]

    async def resolve(self, entity: QueryEntity) -> tuple[list[GraphEntity], bool]:
        rows = await self._read(
            RESOLVE,
            name=normalize_name(entity.name),
            type=entity.type,
            limit=self.settings.graph_max_anchors + 1,
        )
        return (
            [GraphEntity.model_validate(row) for row in rows[: self.settings.graph_max_anchors]],
            len(rows) > self.settings.graph_max_anchors,
        )

    async def neighbors(
        self, entity_id: str, direction: str
    ) -> tuple[list[tuple[GraphEntity, GraphEdge]], bool]:
        rows = await self._read(
            NEIGHBORS,
            id=entity_id,
            direction=direction,
            types=self.settings.relationship_types,
            limit=self.settings.graph_fan_out + 1,
        )
        return (
            [
                (
                    GraphEntity(id=row["id"], name=row["name"], type=row["type"]),
                    GraphEdge(
                        type=row["relationship_type"],
                        source_id=row["source_id"],
                        target_id=row["target_id"],
                    ),
                )
                for row in rows[: self.settings.graph_fan_out]
            ],
            len(rows) > self.settings.graph_fan_out,
        )

    async def evidence(self, edge: GraphEdge) -> GraphEdge:
        rows = await self._read(
            EVIDENCE,
            source=edge.source_id,
            target=edge.target_id,
            type=edge.type,
            limit=self.settings.graph_max_evidence + 1,
        )
        # An evidence-free relationship must not acquire invented metadata.
        evidence = [
            RelationshipEvidence.model_validate(row)
            for row in rows[: self.settings.graph_max_evidence]
            if any(
                row.get(key) is not None for key in ("chunk_id", "document_id", "evidence_quote")
            )
        ]
        return edge.model_copy(
            update={
                "evidence": evidence,
                "evidence_truncated": len(rows) > self.settings.graph_max_evidence,
            }
        )
