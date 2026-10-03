import logging

from neo4j.exceptions import DriverError, Neo4jError

from kg_assistant.core.config import Settings
from kg_assistant.core.exceptions import IngestionError
from kg_assistant.db.repositories.knowledge_graph import KnowledgeGraphRepository
from kg_assistant.ingestion.entity_extraction import EntityExtractionService
from kg_assistant.models.extraction import ExtractionSummary
from kg_assistant.providers.base import ExtractionError

logger = logging.getLogger(__name__)
DATABASE_ERRORS = (Neo4jError, DriverError, TimeoutError, OSError)


class GraphIngestionService:
    def __init__(
        self,
        settings: Settings,
        repository: KnowledgeGraphRepository,
        extractor: EntityExtractionService | None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.extractor = extractor

    async def status(self, document_id: str) -> ExtractionSummary:
        try:
            return await self.repository.summary(document_id)
        except DATABASE_ERRORS as exc:
            raise IngestionError(
                "graph_storage_unavailable", "Unable to read extraction status. Please retry.", 503
            ) from exc

    async def ingest(self, document_id: str) -> ExtractionSummary:
        if self.extractor is None:
            raise IngestionError(
                "extraction_disabled", "Enable and configure LLM extraction first.", 503
            )
        try:
            run_id = await self.repository.begin(document_id)
            for chunk in await self.repository.pending_chunks(document_id):
                attempts = 0
                try:
                    extraction, attempts = await self.extractor.extract(chunk.text)
                    await self.repository.save_chunk(
                        chunk, extraction, attempts, run_id, self.settings.llm_model
                    )
                except IngestionError:
                    raise
                except ExtractionError as exc:
                    await self.repository.fail_chunk(
                        chunk, exc.code, getattr(exc, "attempts", 1), run_id
                    )
                    logger.warning("chunk_extraction_failed:%s:%s", chunk.id, exc.code)
                except Exception as exc:
                    # Graph writes roll back first; completed chunks remain intact.
                    code = (
                        "graph_write_failed"
                        if isinstance(exc, DATABASE_ERRORS)
                        else "extraction_failed"
                    )
                    await self.repository.fail_chunk(chunk, code, attempts, run_id)
                    logger.error("chunk_extraction_failed:%s:%s", chunk.id, type(exc).__name__)
            return await self.repository.finish(document_id, run_id)
        except DATABASE_ERRORS as exc:
            logger.error("graph_storage_failed:%s", type(exc).__name__)
            raise IngestionError(
                "graph_storage_unavailable",
                f"Document {document_id} is saved, but graph storage failed. "
                "Retry its extraction later.",
                503,
            ) from exc
