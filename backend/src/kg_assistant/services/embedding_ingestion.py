import logging

from neo4j.exceptions import DriverError, Neo4jError

from kg_assistant.core.config import Settings
from kg_assistant.core.exceptions import IngestionError
from kg_assistant.db.repositories.vectors import VectorRepository
from kg_assistant.models.embeddings import BackfillResponse, EmbeddingFailure, EmbeddingSummary
from kg_assistant.providers.embeddings import EmbeddingError
from kg_assistant.services.embeddings import EmbeddingService

logger = logging.getLogger(__name__)
DATABASE_ERRORS = (Neo4jError, DriverError, TimeoutError, OSError)


class EmbeddingIngestionService:
    def __init__(
        self, settings: Settings, repository: VectorRepository, embedder: EmbeddingService | None
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.embedder = embedder

    async def backfill(self, document_id: str | None, limit: int) -> BackfillResponse:
        if not self.settings.embedding_enabled or self.embedder is None:
            raise IngestionError(
                "embeddings_disabled", "Enable and configure embeddings first.", 503
            )
        report = BackfillResponse()
        attempted: list[str] = []
        try:
            if document_id and not await self.repository.document_exists(document_id):
                raise IngestionError("document_not_found", "Document not found.", 404)
            await self.repository.ensure_index()
            while len(attempted) < limit:
                run_id, chunks = await self.repository.claim(
                    document_id,
                    min(self.settings.embedding_batch_size, limit - len(attempted)),
                    attempted,
                )
                if not chunks:
                    break
                attempted.extend(chunk.id for chunk in chunks)
                try:
                    vectors = await self.embedder.embed_batch([chunk.text for chunk in chunks])
                except EmbeddingError as exc:
                    logger.warning("chunk_embeddings_failed:%s:count=%s", exc.code, len(chunks))
                    await self.repository.fail(run_id, chunks, exc.code)
                    report.errors.extend(
                        EmbeddingFailure(chunk_id=chunk.id, code=exc.code) for chunk in chunks
                    )
                    continue
                updated = await self.repository.store(run_id, chunks, vectors)
                report.updated += updated
                report.skipped += len(chunks) - updated
            report.processed = len(attempted)
            summary = await self.repository.summary(document_id)
            report.remaining = summary.total - summary.completed
            return report
        except DATABASE_ERRORS as exc:
            logger.warning("embedding_database_failed:%s", type(exc).__name__)
            message = "Embedding storage unavailable; saved chunks can be backfilled later."
            if document_id:
                message += f" Document ID: {document_id}."
            raise IngestionError("database_unavailable", message, 503) from exc

    async def ingest(self, document_id: str) -> EmbeddingSummary:
        await self.backfill(document_id, self.settings.max_chunks)
        try:
            return await self.repository.summary(document_id)
        except DATABASE_ERRORS as exc:
            raise IngestionError(
                "database_unavailable", "Embedding status unavailable.", 503
            ) from exc
