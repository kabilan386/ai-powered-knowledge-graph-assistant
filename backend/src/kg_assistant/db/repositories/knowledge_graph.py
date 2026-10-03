import asyncio
from uuid import NAMESPACE_URL, uuid4, uuid5

from neo4j import AsyncManagedTransaction

from kg_assistant.core.exceptions import IngestionError
from kg_assistant.core.graph_types import validate_types
from kg_assistant.db.migrations.entities import CONSTRAINTS
from kg_assistant.db.neo4j import Neo4jConnectionManager
from kg_assistant.models.documents import Chunk
from kg_assistant.models.extraction import (
    ChunkExtractionError,
    ExtractionSummary,
    NormalizedExtraction,
)

MERGE_ENTITIES = """
MATCH (c:Chunk {id: $chunk_id})
UNWIND $entities AS item
MERGE (e:Entity {type: item.type, normalized_name: item.normalized_name})
ON CREATE SET e.id = item.id, e.name = item.name, e.description = item.description
MERGE (c)-[m:MENTIONS]->(e)
SET m.source_document_id = $document_id, m.evidence_quote = item.evidence_quote
RETURN count(e) AS count
"""
MERGE_RELATIONSHIPS = """
UNWIND $relationships AS item
MATCH (s:Entity {id: item.source_id}), (t:Entity {id: item.target_id})
MERGE (s)-[r:RELATIONSHIP_TYPE {id: item.id}]->(t)
SET r.source_chunk_id = $chunk_id, r.source_document_id = $document_id,
    r.evidence_quote = item.evidence_quote, r.description = item.description
RETURN count(r) AS count
"""


class KnowledgeGraphRepository:
    def __init__(
        self,
        connection: Neo4jConnectionManager,
        timeout: float,
        entity_types: list[str],
        relationship_types: list[str],
        lease_seconds: float,
    ) -> None:
        self.connection = connection
        self.timeout = timeout
        self.entity_types = set(validate_types(entity_types))
        self.relationship_types = set(validate_types(relationship_types))
        # Compile fixed query structures ONLY from validated server configuration, never LLM text.
        self.relationship_queries = {
            kind: MERGE_RELATIONSHIPS.replace("RELATIONSHIP_TYPE", kind)
            for kind in self.relationship_types
        }
        self.lease_seconds = lease_seconds

    async def begin(self, document_id: str) -> str:
        run_id = str(uuid4())
        async with asyncio.timeout(self.timeout):
            async with self.connection.driver.session(
                database=self.connection.settings.neo4j_database
            ) as session:
                for statement in CONSTRAINTS:
                    await (await session.run(statement)).consume()
                result = await session.run(
                    "MATCH (d:Document {id: $id}) "
                    "SET d.extraction_lock = coalesce(d.extraction_lock, 0) + 1 "
                    "WITH d WHERE coalesce(d.extraction_status, 'disabled') <> 'processing' "
                    "OR d.extraction_lease_until IS NULL OR d.extraction_lease_until < datetime() "
                    "SET d.extraction_status = 'processing', d.extraction_run_id = $run_id, "
                    "d.extraction_lease_until = datetime() + duration({seconds: $lease}) "
                    "RETURN d.id AS id",
                    id=document_id,
                    run_id=run_id,
                    lease=self.lease_seconds,
                )
                if await result.single() is None:
                    # Distinguish a missing document from a concurrent ingestion attempt.
                    await self._summary_session(session, document_id)
                    raise IngestionError(
                        "extraction_in_progress", "Extraction is already running.", 409
                    )
        return run_id

    async def pending_chunks(self, document_id: str) -> list[Chunk]:
        async with asyncio.timeout(self.timeout):
            async with self.connection.driver.session(
                database=self.connection.settings.neo4j_database
            ) as session:
                result = await session.run(
                    "MATCH (:Document {id: $id})-[:HAS_CHUNK]->(c:Chunk) "
                    "WHERE coalesce(c.extraction_status, 'disabled') <> 'completed' "
                    "RETURN c.id AS id, c.text AS text, c.chunk_index AS chunk_index, "
                    "c.page_number AS page_number ORDER BY c.chunk_index",
                    id=document_id,
                )
                return [Chunk(document_id=document_id, **dict(r)) async for r in result]

    async def save_chunk(
        self,
        chunk: Chunk,
        extraction: NormalizedExtraction,
        attempts: int,
        run_id: str,
        model: str,
    ) -> None:
        if any(e.type not in self.entity_types for e in extraction.entities):
            raise ValueError("Entity type is not configured")
        if any(r.type not in self.relationship_types for r in extraction.relationships):
            raise ValueError("Relationship type is not configured")
        ids = {e.id for e in extraction.entities}
        if any(r.source_id not in ids or r.target_id not in ids for r in extraction.relationships):
            raise ValueError("Relationship endpoints must be mentioned in this chunk")
        relationships = [
            {
                **r.model_dump(),
                "id": str(
                    uuid5(NAMESPACE_URL, f"fact:{chunk.id}:{r.source_id}:{r.type}:{r.target_id}")
                ),
            }
            for r in extraction.relationships
        ]
        async with asyncio.timeout(self.timeout):
            async with self.connection.driver.session(
                database=self.connection.settings.neo4j_database
            ) as session:
                await session.execute_write(
                    self._save_transaction,
                    chunk,
                    [e.model_dump() for e in extraction.entities],
                    relationships,
                    attempts,
                    run_id,
                    model,
                )

    async def _owned(self, tx: AsyncManagedTransaction, document_id: str, run_id: str) -> None:
        result = await tx.run(
            "MATCH (d:Document {id: $id}) "
            "SET d.extraction_lock = coalesce(d.extraction_lock, 0) + 1 "
            "WITH d WHERE d.extraction_run_id = $run_id "
            "SET d.extraction_lease_until = datetime() + duration({seconds: $lease}) "
            "RETURN d.id AS id",
            id=document_id,
            run_id=run_id,
            lease=self.lease_seconds,
        )
        if await result.single() is None:
            raise IngestionError(
                "extraction_superseded", "A newer extraction run owns this document.", 409
            )

    async def _save_transaction(
        self,
        tx: AsyncManagedTransaction,
        chunk: Chunk,
        entities: list[dict],
        relationships: list[dict],
        attempts: int,
        run_id: str,
        model: str,
    ) -> None:
        await self._owned(tx, chunk.document_id, run_id)
        result = await tx.run(
            MERGE_ENTITIES, chunk_id=chunk.id, document_id=chunk.document_id, entities=entities
        )
        record = await result.single(strict=True)
        if record is None or record["count"] != len(entities):
            raise RuntimeError("Graph write lost an entity")
        # Use server-allowlisted query templates for reliable MERGE on the pinned Neo4j version.
        groups: dict[str, list[dict]] = {}
        for relationship in relationships:
            groups.setdefault(relationship["type"], []).append(relationship)
        for relationship_type, items in groups.items():
            result = await tx.run(
                self.relationship_queries[relationship_type],
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                relationships=items,
            )
            record = await result.single(strict=True)
            if record is None or record["count"] != len(items):
                raise RuntimeError("Graph write lost a relationship")
        result = await tx.run(
            "MATCH (:Document {id: $document_id})-[:HAS_CHUNK]->(c:Chunk {id: $chunk_id}) "
            "SET c.extraction_status = 'completed', c.extraction_error = null, "
            "c.extraction_attempts = coalesce(c.extraction_attempts, 0) + $attempts, "
            "c.extraction_model = $model, c.extraction_prompt_version = 'v1' RETURN c.id AS id",
            document_id=chunk.document_id,
            chunk_id=chunk.id,
            attempts=attempts,
            model=model,
        )
        if await result.single() is None:
            raise RuntimeError("Chunk no longer belongs to the document")

    async def fail_chunk(self, chunk: Chunk, code: str, attempts: int, run_id: str) -> None:
        async def write(tx):
            await self._owned(tx, chunk.document_id, run_id)
            result = await tx.run(
                "MATCH (:Document {id: $document_id})-[:HAS_CHUNK]->(c:Chunk {id: $chunk_id}) "
                "SET c.extraction_status = 'failed', c.extraction_error = $code, "
                "c.extraction_attempts = coalesce(c.extraction_attempts, 0) + $attempts",
                document_id=chunk.document_id,
                chunk_id=chunk.id,
                code=code,
                attempts=attempts,
            )
            await result.consume()

        async with asyncio.timeout(self.timeout):
            async with self.connection.driver.session(
                database=self.connection.settings.neo4j_database
            ) as session:
                await session.execute_write(write)

    async def summary(self, document_id: str) -> ExtractionSummary:
        async with asyncio.timeout(self.timeout):
            async with self.connection.driver.session(
                database=self.connection.settings.neo4j_database
            ) as session:
                return await self._summary_session(session, document_id)

    @staticmethod
    async def _summary_session(session, document_id: str) -> ExtractionSummary:
        result = await session.run(
            "MATCH (d:Document {id: $id}) OPTIONAL MATCH (d)-[:HAS_CHUNK]->(c:Chunk) "
            "RETURN coalesce(d.extraction_status, 'disabled') AS status, "
            "collect(c { .id, .extraction_status, .extraction_error, "
            ".extraction_attempts }) AS chunks",
            id=document_id,
        )
        record = await result.single()
        if record is None:
            raise IngestionError("document_not_found", "Document not found.", 404)
        chunks = record["chunks"]
        return ExtractionSummary(
            status=record["status"],
            total=len(chunks),
            completed=sum(c.get("extraction_status") == "completed" for c in chunks),
            failed=sum(c.get("extraction_status") == "failed" for c in chunks),
            errors=[
                ChunkExtractionError(
                    chunk_id=c["id"],
                    code=c["extraction_error"],
                    attempts=c.get("extraction_attempts") or 0,
                )
                for c in chunks
                if c.get("extraction_status") == "failed"
            ],
        )

    async def finish(self, document_id: str, run_id: str) -> ExtractionSummary:
        async def write(tx):
            await self._owned(tx, document_id, run_id)
            result = await tx.run(
                "MATCH (d:Document {id: $id})-[:HAS_CHUNK]->(c:Chunk) "
                "WITH d, count(c) AS total, "
                "sum(CASE WHEN c.extraction_status = 'completed' THEN 1 ELSE 0 END) AS done "
                "SET d.extraction_status = CASE WHEN done = total THEN 'completed' "
                "WHEN done > 0 THEN 'partial' ELSE 'failed' END, "
                "d.extraction_run_id = null, d.extraction_lease_until = null",
                id=document_id,
            )
            await result.consume()

        async with asyncio.timeout(self.timeout):
            async with self.connection.driver.session(
                database=self.connection.settings.neo4j_database
            ) as session:
                await session.execute_write(write)
        return await self.summary(document_id)
