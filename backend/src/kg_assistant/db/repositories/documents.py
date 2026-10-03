import asyncio

from neo4j import AsyncManagedTransaction

from kg_assistant.db.migrations.documents import CONSTRAINTS
from kg_assistant.db.neo4j import Neo4jConnectionManager
from kg_assistant.models.documents import Chunk, Document

STORE_DOCUMENT = """
MERGE (d:Document {id: $document.id})
ON CREATE SET d.filename = $document.filename,
              d.file_type = $document.file_type,
              d.created_at = datetime($document.created_at),
              d.extraction_status = $document.extraction_status
WITH d
UNWIND $chunks AS item
MERGE (c:Chunk {id: item.id})
ON CREATE SET c.text = item.text,
              c.document_id = item.document_id,
              c.chunk_index = item.chunk_index,
              c.page_number = item.page_number,
              c.extraction_status = $document.extraction_status
MERGE (d)-[:HAS_CHUNK]->(c)
RETURN count(c) AS chunk_count
"""


class DocumentRepository:
    def __init__(self, connection: Neo4jConnectionManager, timeout: float) -> None:
        self.connection = connection
        self.timeout = timeout

    async def save(self, document: Document, chunks: list[Chunk]) -> None:
        if not chunks or any(chunk.document_id != document.id for chunk in chunks):
            raise ValueError("Chunks must belong to the document")
        async with asyncio.timeout(self.timeout):
            async with self.connection.driver.session(
                database=self.connection.settings.neo4j_database
            ) as session:
                # DDL must execute separately from the atomic document/chunk data transaction.
                for statement in CONSTRAINTS:
                    result = await session.run(statement)
                    await result.consume()
                await session.execute_write(
                    self._save_transaction,
                    document.model_dump(mode="json"),
                    [chunk.model_dump(mode="json") for chunk in chunks],
                )

    @staticmethod
    async def _save_transaction(
        tx: AsyncManagedTransaction, document: dict, chunks: list[dict]
    ) -> None:
        result = await tx.run(STORE_DOCUMENT, document=document, chunks=chunks)
        record = await result.single(strict=True)
        if record is None or record["chunk_count"] != len(chunks):
            raise RuntimeError("Document write did not store every chunk")
