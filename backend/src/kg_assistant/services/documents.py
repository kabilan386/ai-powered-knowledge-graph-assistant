import logging
from datetime import UTC, datetime
from pathlib import PurePosixPath
from uuid import uuid4

from fastapi import UploadFile
from neo4j.exceptions import DriverError, Neo4jError
from starlette.concurrency import run_in_threadpool

from kg_assistant.core.config import Settings
from kg_assistant.core.exceptions import IngestionError
from kg_assistant.db.repositories.documents import DocumentRepository
from kg_assistant.ingestion.chunking import ChunkingService
from kg_assistant.ingestion.extraction import TextExtractionService
from kg_assistant.models.documents import Document, FileType, UploadResponse
from kg_assistant.models.embeddings import EmbeddingSummary
from kg_assistant.models.extraction import ExtractionSummary
from kg_assistant.services.embedding_ingestion import EmbeddingIngestionService
from kg_assistant.services.knowledge_graph import GraphIngestionService

logger = logging.getLogger(__name__)
SUPPORTED_TYPES: dict[str, FileType] = {".pdf": "pdf", ".docx": "docx", ".txt": "txt"}


class DocumentService:
    def __init__(
        self,
        settings: Settings,
        extractor: TextExtractionService,
        chunker: ChunkingService,
        repository: DocumentRepository,
        graph_ingestion: GraphIngestionService | None = None,
        embedding_ingestion: EmbeddingIngestionService | None = None,
    ) -> None:
        self.settings = settings
        self.extractor = extractor
        self.chunker = chunker
        self.repository = repository
        self.graph_ingestion = graph_ingestion
        self.embedding_ingestion = embedding_ingestion

    async def upload(self, file: UploadFile) -> UploadResponse:
        try:
            filename = PurePosixPath((file.filename or "").replace("\\", "/")).name
            if (
                not filename
                or len(filename) > 255
                or any(ord(character) < 32 or ord(character) == 127 for character in filename)
            ):
                raise IngestionError(
                    "invalid_filename",
                    "Provide a filename up to 255 characters without control characters.",
                    400,
                )
            file_type = SUPPORTED_TYPES.get(PurePosixPath(filename).suffix.lower())
            if file_type is None:
                raise IngestionError("unsupported_file", "Supported types: PDF, DOCX, TXT.", 415)
            if file.size is not None and file.size > self.settings.max_file_size:
                raise IngestionError("file_too_large", "File exceeds the maximum upload size.", 413)
            content = bytearray()
            while block := await file.read(64 * 1024):
                content.extend(block)
                if len(content) > self.settings.max_file_size:
                    raise IngestionError(
                        "file_too_large", "File exceeds the maximum upload size.", 413
                    )
            pages = await run_in_threadpool(self.extractor.extract, bytes(content), file_type)
            document = Document(
                id=str(uuid4()),
                filename=filename,
                file_type=file_type,
                created_at=datetime.now(UTC),
                extraction_status="pending" if self.settings.llm_extraction_enabled else "disabled",
            )
            chunks = await run_in_threadpool(self.chunker.chunk, pages, document.id)
            try:
                await self.repository.save(document, chunks)
            except (Neo4jError, DriverError, TimeoutError, OSError) as exc:
                logger.warning("document_persistence_failed:%s", type(exc).__name__)
                raise IngestionError(
                    "database_unavailable", "Unable to store the document. Please retry later.", 503
                ) from exc
            logger.info("document_stored:%s:chunks=%s", document.id, len(chunks))
            embeddings = EmbeddingSummary(status="disabled", total=len(chunks))
            if self.settings.embedding_enabled:
                if self.embedding_ingestion is None:
                    raise IngestionError(
                        "embeddings_unavailable", "Embeddings are not configured.", 503
                    )
                try:
                    embeddings = await self.embedding_ingestion.ingest(document.id)
                except IngestionError as exc:
                    if document.id not in exc.message:
                        exc.message += f" Saved document ID: {document.id}."
                    raise
            summary = ExtractionSummary(status="disabled", total=len(chunks))
            if self.settings.llm_extraction_enabled:
                if self.graph_ingestion is None:
                    raise IngestionError(
                        "extraction_unavailable", "Graph extraction is not configured.", 503
                    )
                summary = await self.graph_ingestion.ingest(document.id)
                document.extraction_status = summary.status
            return UploadResponse(
                document=document,
                chunk_count=len(chunks),
                extraction=summary,
                embeddings=embeddings,
            )
        finally:
            await file.close()
