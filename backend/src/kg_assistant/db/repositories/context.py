import asyncio

from neo4j import READ_ACCESS

from kg_assistant.core.config import Settings
from kg_assistant.db.neo4j import Neo4jConnectionManager
from kg_assistant.models.graphrag import SourceChunk

LOAD_CHUNKS = """
UNWIND $references AS ref
MATCH (d:Document {id: ref.document_id})-[:HAS_CHUNK]->(c:Chunk {id: ref.chunk_id})
RETURN DISTINCT d.id AS document_id, c.id AS chunk_id, d.filename AS filename,
       c.page_number AS page_number, c.chunk_index AS chunk_index,
       substring(c.text, 0, $max_characters) AS text,
       size(c.text) > $max_characters AS text_truncated
ORDER BY document_id, chunk_id
"""


class ContextRepository:
    """Verify source identity and hydrate actual text, never manufacture provenance from quotes."""

    def __init__(self, connection: Neo4jConnectionManager, settings: Settings) -> None:
        self.connection = connection
        self.settings = settings

    async def load_chunks(self, references: list[tuple[str, str]]) -> list[SourceChunk]:
        if not references:
            return []
        async with asyncio.timeout(self.settings.neo4j_write_timeout):
            async with self.connection.driver.session(
                database=self.settings.neo4j_database, default_access_mode=READ_ACCESS
            ) as session:

                async def read(tx):
                    result = await tx.run(
                        LOAD_CHUNKS,
                        max_characters=self.settings.max_chunk_context_characters,
                        references=[
                            {"document_id": doc, "chunk_id": chunk} for doc, chunk in references
                        ],
                    )
                    return [SourceChunk.model_validate(dict(row)) async for row in result]

                return await session.execute_read(read)
