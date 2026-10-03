import asyncio

from neo4j import READ_ACCESS, unit_of_work

from kg_assistant.core.config import Settings
from kg_assistant.db.neo4j import Neo4jConnectionManager
from kg_assistant.evaluation.models import ExpectedSource, ResolvedGroundTruth

RESOLVE_SOURCES = """
UNWIND $selectors AS ref
CALL {
  WITH ref
  MATCH (d:Document)-[:HAS_CHUNK]->(c:Chunk)
  WHERE (ref.document_id IS NULL OR d.id = ref.document_id)
    AND (ref.chunk_id IS NULL OR c.id = ref.chunk_id)
    AND (ref.filename IS NULL OR d.filename = ref.filename)
    AND (ref.quote IS NULL OR c.text CONTAINS ref.quote)
    AND (ref.page_number IS NULL OR c.page_number = ref.page_number)
    AND (ref.chunk_index IS NULL OR c.chunk_index = ref.chunk_index)
  RETURN d.id AS document_id, c.id AS chunk_id ORDER BY document_id, chunk_id LIMIT 2
}
RETURN ref.selector_index AS selector_index, document_id, chunk_id
"""
AUDIT_SOURCES = """
UNWIND $references AS ref
OPTIONAL MATCH (d:Document {id:ref.document_id})
OPTIONAL MATCH (c:Chunk {id:ref.chunk_id})
RETURN ref.document_id AS document_id, ref.chunk_id AS chunk_id,
       d IS NOT NULL AS document_exists, c IS NOT NULL AS chunk_exists,
       EXISTS { MATCH (d)-[:HAS_CHUNK]->(c) } AS linked
"""


class EvaluationRepository:
    """Read-only ground-truth resolution and source-existence audits; no data mutations."""

    def __init__(self, connection: Neo4jConnectionManager, settings: Settings) -> None:
        self.connection = connection
        self.settings = settings

    async def read(self, statement: str, **parameters) -> list[dict]:
        async with asyncio.timeout(self.settings.neo4j_write_timeout):
            async with self.connection.driver.session(
                database=self.settings.neo4j_database, default_access_mode=READ_ACCESS
            ) as session:

                @unit_of_work(timeout=self.settings.neo4j_write_timeout)
                async def load(tx):
                    result = await tx.run(statement, **parameters)
                    return [dict(row) async for row in result]

                return await session.execute_read(load)

    async def resolve_sources(self, selectors: list[ExpectedSource]) -> ResolvedGroundTruth:
        if not selectors:
            return ResolvedGroundTruth(status="unannotated")
        rows = await self.read(
            RESOLVE_SOURCES,
            selectors=[
                {**selector.model_dump(), "selector_index": index}
                for index, selector in enumerate(selectors)
            ],
        )
        return resolve_rows(len(selectors), rows)

    async def audit(self, references: list[tuple[str, str]]) -> list[dict]:
        if not references:
            return []
        return await self.read(
            AUDIT_SOURCES,
            references=[{"document_id": doc, "chunk_id": chunk} for doc, chunk in references],
        )


def resolve_rows(count: int, rows: list[dict]) -> ResolvedGroundTruth:
    grouped = {index: [] for index in range(count)}
    for row in rows:
        grouped[row["selector_index"]].append((row["document_id"], row["chunk_id"]))
    if any(len(references) > 1 for references in grouped.values()):
        return ResolvedGroundTruth(status="ambiguous")
    if any(not references for references in grouped.values()):
        return ResolvedGroundTruth(status="missing")
    return ResolvedGroundTruth(
        status="resolved",
        references=list(dict.fromkeys(references[0] for references in grouped.values())),
    )
