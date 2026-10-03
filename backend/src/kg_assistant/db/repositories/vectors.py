import asyncio
from uuid import uuid4

from kg_assistant.core.config import Settings
from kg_assistant.core.exceptions import IngestionError
from kg_assistant.db.migrations.vectors import CREATE_INDEX, INDEX_NAME, SPACE_CONSTRAINT
from kg_assistant.db.neo4j import Neo4jConnectionManager
from kg_assistant.models.documents import Chunk
from kg_assistant.models.embeddings import EmbeddingFailure, EmbeddingSummary
from kg_assistant.models.retrieval import VectorSearchResult

CLAIM = """
MATCH (d:Document)-[:HAS_CHUNK]->(c:Chunk)
WHERE ($document_id IS NULL OR d.id = $document_id)
  AND c.embedding IS NULL AND NOT c.id IN $excluded
  AND (c.embedding_lease_until IS NULL OR c.embedding_lease_until < datetime())
WITH d, c ORDER BY d.created_at, c.chunk_index, c.id LIMIT $limit
SET c.embedding_lock = coalesce(c.embedding_lock, 0) + 1
WITH d, c
WHERE c.embedding IS NULL
  AND (c.embedding_lease_until IS NULL OR c.embedding_lease_until < datetime())
SET c.embedding_run_id = $run_id, c.embedding_status = 'processing',
    c.embedding_lease_until = datetime() + duration({seconds: $lease})
RETURN c.id AS id, d.id AS document_id, c.text AS text,
       c.chunk_index AS chunk_index, c.page_number AS page_number
"""

STORE = """
UNWIND $items AS item
MATCH (c:Chunk {id: item.id})
SET c.embedding_lock = coalesce(c.embedding_lock, 0) + 1
WITH c, item WHERE c.embedding IS NULL AND c.embedding_run_id = $run_id
SET c.embedding = item.vector, c.embedding_provider = $provider,
    c.embedding_model = $model, c.embedding_dimensions = $dimensions,
    c.embedding_status = 'completed'
REMOVE c.embedding_run_id, c.embedding_lease_until, c.embedding_error
RETURN count(c) AS updated
"""

FAIL = """
MATCH (c:Chunk) WHERE c.id IN $ids
SET c.embedding_lock = coalesce(c.embedding_lock, 0) + 1
WITH c WHERE c.embedding IS NULL AND c.embedding_run_id = $run_id
SET c.embedding_status = 'failed', c.embedding_error = $code
REMOVE c.embedding_run_id, c.embedding_lease_until
RETURN count(c) AS updated
"""

# Source traversal is limited to HAS_CHUNK; no graph evidence retrieval in this milestone.
SEARCH = """
CALL db.index.vector.queryNodes($name, $candidates, $vector) YIELD node, score
MATCH (d:Document)-[:HAS_CHUNK]->(node)
WHERE node.embedding_provider = $provider AND node.embedding_model = $model
  AND node.embedding_dimensions = $dimensions
  AND NOT EXISTS {
      MATCH (d)-[:HAS_CHUNK]->(other:Chunk) WHERE other.embedding IS NULL
  }
RETURN node.id AS chunk_id, node.text AS text, score, d.id AS document_id,
       d.filename AS filename, node.page_number AS page_number,
       node.chunk_index AS chunk_index
ORDER BY score DESC, chunk_id LIMIT $top_k
"""


class VectorRepository:
    def __init__(self, connection: Neo4jConnectionManager, settings: Settings) -> None:
        self.connection = connection
        self.settings = settings
        self.identity = {
            "provider": settings.embedding_provider,
            "model": settings.embedding_model,
            "dimensions": settings.embedding_dimensions,
        }

    async def _run(self, statement: str, **parameters) -> list[dict]:
        async with asyncio.timeout(self.settings.neo4j_write_timeout):
            async with self.connection.driver.session(
                database=self.settings.neo4j_database
            ) as session:
                result = await session.run(statement, **parameters)
                return [dict(record) async for record in result]

    async def ensure_index(self) -> None:
        await self._run(CREATE_INDEX, dimensions=self.settings.embedding_dimensions)
        rows = await self._run(
            "SHOW INDEXES YIELD name, type, labelsOrTypes, properties, options "
            "WHERE name = $name RETURN type, labelsOrTypes, properties, options",
            name=INDEX_NAME,
        )
        row = rows[0] if rows else {}
        options = row.get("options", {}).get("indexConfig", {})
        if (
            row.get("type") != "VECTOR"
            or row.get("labelsOrTypes") != ["Chunk"]
            or row.get("properties") != ["embedding"]
            or options.get("vector.dimensions") != self.settings.embedding_dimensions
            or str(options.get("vector.similarity_function", "")).lower() != "cosine"
        ):
            raise IngestionError(
                "embedding_space_mismatch", "Vector index configuration differs.", 409
            )
        await self._run(SPACE_CONSTRAINT)
        space = await self._run(
            "MERGE (s:EmbeddingSpace {id: $name}) "
            "ON CREATE SET s.provider = $provider, s.model = $model, s.dimensions = $dimensions "
            "SET s.lock = coalesce(s.lock, 0) + 1 "
            "RETURN s.provider AS provider, s.model AS model, s.dimensions AS dimensions",
            name=INDEX_NAME,
            **self.identity,
        )
        if space[0] != self.identity:
            raise IngestionError(
                "embedding_space_mismatch",
                "Existing embeddings use another provider or model.",
                409,
            )
        incompatible = await self._run(
            "MATCH (c:Chunk) WHERE c.embedding IS NOT NULL AND "
            "(coalesce(c.embedding_provider, '') <> $provider OR "
            "coalesce(c.embedding_model, '') <> $model OR "
            "coalesce(c.embedding_dimensions, -1) <> $dimensions OR "
            "size(c.embedding) <> $dimensions) RETURN c.id LIMIT 1",
            **self.identity,
        )
        if incompatible:
            raise IngestionError(
                "embedding_space_mismatch",
                "Existing chunk embeddings have incompatible metadata.",
                409,
            )
        async with asyncio.timeout(self.settings.vector_index_timeout + 1):
            async with self.connection.driver.session(
                database=self.settings.neo4j_database
            ) as session:
                result = await session.run(
                    "CALL db.awaitIndex($name, $timeout)",
                    name=INDEX_NAME,
                    timeout=int(self.settings.vector_index_timeout) or 1,
                )
                await result.consume()

    async def claim(
        self, document_id: str | None, limit: int, excluded: list[str]
    ) -> tuple[str, list[Chunk]]:
        run_id = str(uuid4())
        lease = int(
            self.settings.embedding_request_timeout * self.settings.embedding_max_attempts
            + self.settings.embedding_retry_backoff * self.settings.embedding_max_attempts**2
            + self.settings.neo4j_write_timeout
            + 30
        )
        rows = await self._run(
            CLAIM,
            document_id=document_id,
            limit=limit,
            excluded=excluded,
            run_id=run_id,
            lease=lease,
        )
        return run_id, [Chunk.model_validate(row) for row in rows]

    async def store(self, run_id: str, chunks: list[Chunk], vectors: list[list[float]]) -> int:
        if len(chunks) != len(vectors):
            raise ValueError("Every chunk must have a vector")
        rows = await self._run(
            STORE,
            run_id=run_id,
            items=[
                {"id": chunk.id, "vector": vector}
                for chunk, vector in zip(chunks, vectors, strict=True)
            ],
            **self.identity,
        )
        return rows[0]["updated"]

    async def fail(self, run_id: str, chunks: list[Chunk], code: str) -> None:
        await self._run(FAIL, run_id=run_id, ids=[chunk.id for chunk in chunks], code=code)

    async def summary(self, document_id: str | None) -> EmbeddingSummary:
        rows = await self._run(
            "MATCH (d:Document)-[:HAS_CHUNK]->(c:Chunk) "
            "WHERE $document_id IS NULL OR d.id = $document_id "
            "RETURN count(c) AS total, count(c.embedding) AS completed, "
            "sum(CASE WHEN c.embedding IS NULL AND c.embedding_status = 'failed' "
            "THEN 1 ELSE 0 END) AS failed, "
            "collect(CASE WHEN c.embedding IS NULL AND c.embedding_status = 'failed' "
            "THEN {chunk_id: c.id, code: c.embedding_error} ELSE null END) AS errors",
            document_id=document_id,
        )
        counts = rows[0]
        total, completed, failed = counts["total"], counts["completed"], counts["failed"]
        status = (
            "completed"
            if total == completed
            else "partial"
            if completed
            else "failed"
            if failed == total
            else "pending"
        )
        errors = [EmbeddingFailure.model_validate(row) for row in counts.pop("errors")]
        return EmbeddingSummary(status=status, errors=errors, **counts)

    async def document_exists(self, document_id: str) -> bool:
        rows = await self._run("MATCH (d:Document {id: $id}) RETURN d.id", id=document_id)
        return bool(rows)

    async def search(self, vector: list[float], top_k: int) -> list[VectorSearchResult]:
        # Bounded oversampling compensates for partially embedded documents filtered below.
        rows = await self._run(
            SEARCH,
            name=INDEX_NAME,
            vector=vector,
            top_k=top_k,
            candidates=min(1000, top_k * 10),
            **self.identity,
        )
        return [VectorSearchResult.model_validate(row) for row in rows]
