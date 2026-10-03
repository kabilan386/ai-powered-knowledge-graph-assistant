import asyncio
import logging
from collections import deque

from neo4j import READ_ACCESS
from neo4j.exceptions import DriverError, Neo4jError

from kg_assistant.core.config import Settings
from kg_assistant.core.exceptions import IngestionError
from kg_assistant.db.neo4j import Neo4jConnectionManager
from kg_assistant.db.repositories.graph_retrieval import GraphRetrievalRepository
from kg_assistant.models.graph_retrieval import (
    GraphEntity,
    GraphPath,
    GraphSearchRequest,
    GraphSearchResponse,
    QueryExtraction,
)
from kg_assistant.providers.base import ExtractionError
from kg_assistant.retrieval.query_entities import QueryEntityExtractionService

logger = logging.getLogger(__name__)


def rank_path(path: GraphPath, intent: QueryExtraction) -> float:
    # Ordered prefix coverage rewards reaching the requested chain, then the target type.
    matched = 0
    for expected, actual in zip(intent.relationship_types, path.relationships, strict=False):
        if expected != actual:
            break
        matched += 1
    relevance = 60 * matched / len(intent.relationship_types) if intent.relationship_types else 0
    target = 25 if intent.target_type and path.nodes[-1].type == intent.target_type else 0
    support = 5 * sum(bool(edge.evidence) for edge in path.edges) / path.hop_count
    return round(relevance + target + 10 / path.hop_count + support, 6)


class GraphTraversal:
    def __init__(self, settings: Settings, repository: GraphRetrievalRepository) -> None:
        self.settings = settings
        self.repository = repository

    async def retrieve(
        self, query: str, intent: QueryExtraction, max_hops: int
    ) -> GraphSearchResponse:
        anchors: dict[str, GraphEntity] = {}
        unresolved = []
        truncated = False
        for entity in intent.entities:
            matches, limited = await self.repository.resolve(entity)
            truncated |= limited
            if not matches:
                unresolved.append(entity)
            for match in matches:
                if match.id in anchors:
                    continue
                if len(anchors) >= self.settings.graph_max_anchors:
                    truncated = True
                    continue
                anchors[match.id] = match
        if not anchors:
            return GraphSearchResponse(
                query=query,
                anchors=[],
                paths=[],
                unresolved_entities=unresolved,
                status="unresolved_anchors" if unresolved else "no_anchors",
                truncated=truncated,
            )
        queue = deque(([anchor], []) for anchor in anchors.values())
        paths: dict[tuple, GraphPath] = {}
        adjacency = {}
        evidence_cache = {}
        while queue:
            nodes, edges = queue.popleft()
            if len(edges) >= max_hops:
                continue
            current = nodes[-1]
            if current.id not in adjacency:
                adjacency[current.id] = await self.repository.neighbors(
                    current.id, intent.direction
                )
            neighbors, limited = adjacency[current.id]
            truncated |= limited
            for neighbor, edge in neighbors:
                if neighbor.id in {node.id for node in nodes}:
                    continue
                # Defense in depth: only server-allowlisted Entity domain edges can be returned.
                if edge.type not in self.settings.relationship_types or edge.type in {
                    "HAS_CHUNK",
                    "MENTIONS",
                }:
                    continue
                key = (edge.source_id, edge.type, edge.target_id)
                path_key = (
                    tuple(node.id for node in nodes + [neighbor]),
                    tuple((e.source_id, e.type, e.target_id) for e in edges + [edge]),
                )
                if path_key in paths:
                    continue
                if len(paths) >= self.settings.graph_max_candidates:
                    truncated = True
                    queue.clear()
                    break
                if key not in evidence_cache:
                    evidence_cache[key] = await self.repository.evidence(edge)
                full_edges = edges + [evidence_cache[key]]
                path = GraphPath(
                    hop_count=len(full_edges),
                    nodes=nodes + [neighbor],
                    edges=full_edges,
                    relationships=[e.type for e in full_edges],
                )
                path.score = rank_path(path, intent)
                paths[path_key] = path
                queue.append((path.nodes, path.edges))
        ranked = sorted(
            paths.values(),
            key=lambda path: (
                -path.score,
                path.hop_count,
                tuple(n.id for n in path.nodes),
                tuple((e.type, e.source_id, e.target_id) for e in path.edges),
            ),
        )
        truncated |= len(ranked) > self.settings.graph_max_results
        return GraphSearchResponse(
            query=query,
            anchors=list(anchors.values()),
            unresolved_entities=unresolved,
            paths=ranked[: self.settings.graph_max_results],
            status="ok" if ranked else "no_paths",
            truncated=truncated,
        )


class GraphRetrievalService:
    def __init__(
        self,
        settings: Settings,
        connection: Neo4jConnectionManager,
        extractor: QueryEntityExtractionService | None,
    ) -> None:
        self.settings = settings
        self.connection = connection
        self.extractor = extractor

    async def search(self, request: GraphSearchRequest) -> GraphSearchResponse:
        max_hops = (
            request.max_hops if request.max_hops is not None else self.settings.graph_max_hops
        )
        if max_hops > self.settings.graph_max_hops:
            raise IngestionError(
                "invalid_max_hops", "max_hops exceeds the configured maximum.", 422
            )
        if not self.settings.graph_retrieval_enabled or self.extractor is None:
            raise IngestionError(
                "graph_retrieval_disabled", "Enable and configure graph retrieval first.", 503
            )
        try:
            intent = await self.extractor.extract(request.query)
        except ExtractionError as exc:
            raise IngestionError(
                exc.code, "Unable to extract graph anchors from the query.", 502
            ) from exc
        try:
            async with asyncio.timeout(self.settings.graph_retrieval_timeout):
                async with self.connection.driver.session(
                    database=self.settings.neo4j_database, default_access_mode=READ_ACCESS
                ) as session:

                    async def read(tx):
                        repository = GraphRetrievalRepository(tx, self.settings)
                        return await GraphTraversal(self.settings, repository).retrieve(
                            request.query, intent, max_hops
                        )

                    return await session.execute_read(read)
        except (Neo4jError, DriverError, TimeoutError, OSError) as exc:
            logger.warning("graph_retrieval_failed:%s", type(exc).__name__)
            raise IngestionError(
                "graph_retrieval_unavailable", "Graph retrieval unavailable or timed out.", 503
            ) from exc
