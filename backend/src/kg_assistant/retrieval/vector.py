import logging

from kg_assistant.core.config import Settings
from kg_assistant.core.exceptions import IngestionError
from kg_assistant.db.repositories.vectors import VectorRepository
from kg_assistant.models.retrieval import VectorSearchRequest, VectorSearchResponse
from kg_assistant.providers.embeddings import EmbeddingError
from kg_assistant.services.embedding_ingestion import DATABASE_ERRORS
from kg_assistant.services.embeddings import EmbeddingService

logger = logging.getLogger(__name__)


class VectorRetrievalService:
    def __init__(
        self, settings: Settings, repository: VectorRepository, embedder: EmbeddingService | None
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.embedder = embedder

    async def search(self, request: VectorSearchRequest) -> VectorSearchResponse:
        if request.top_k > self.settings.vector_max_top_k:
            raise IngestionError("invalid_top_k", "top_k exceeds the configured maximum.", 422)
        if not self.settings.embedding_enabled or self.embedder is None:
            raise IngestionError(
                "embeddings_disabled", "Enable and configure embeddings first.", 503
            )
        try:
            await self.repository.ensure_index()
            vector = await self.embedder.embed_text(request.query)
            results = await self.repository.search(vector, request.top_k)
            return VectorSearchResponse(query=request.query, results=results)
        except EmbeddingError as exc:
            logger.warning("query_embedding_failed:%s", exc.code)
            status = (
                422 if exc.code in {"empty_embedding_input", "embedding_input_too_large"} else 502
            )
            raise IngestionError(
                exc.code, "Unable to embed the query with the configured provider.", status
            ) from exc
        except DATABASE_ERRORS as exc:
            logger.warning("vector_retrieval_failed:%s", type(exc).__name__)
            raise IngestionError(
                "database_unavailable", "Vector retrieval unavailable.", 503
            ) from exc
