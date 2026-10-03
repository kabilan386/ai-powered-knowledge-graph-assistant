import asyncio
import logging
import math

from kg_assistant.core.config import Settings
from kg_assistant.providers.embeddings import EmbeddingError, EmbeddingProvider

logger = logging.getLogger(__name__)


class EmbeddingService:
    def __init__(self, provider: EmbeddingProvider, settings: Settings) -> None:
        self.provider = provider
        self.settings = settings

    def validate_vector(self, vector: list[float]) -> list[float]:
        if not isinstance(vector, list) or len(vector) != self.settings.embedding_dimensions:
            raise EmbeddingError("embedding_dimension_mismatch")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (float, int))
            or not math.isfinite(value)
            for value in vector
        ):
            raise EmbeddingError("invalid_embedding_response", True)
        if not any(vector) or not math.isfinite(math.hypot(*vector)):
            raise EmbeddingError("invalid_embedding_response", True)
        return [float(value) for value in vector]

    async def embed_text(self, text: str) -> list[float]:
        return (await self.embed_batch([text]))[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if any(not text.strip() for text in texts):
            raise EmbeddingError("empty_embedding_input")
        if any(len(text) > self.settings.embedding_max_input_characters for text in texts):
            raise EmbeddingError("embedding_input_too_large")
        vectors = []
        for offset in range(0, len(texts), self.settings.embedding_batch_size):
            batch = texts[offset : offset + self.settings.embedding_batch_size]
            for attempt in range(1, self.settings.embedding_max_attempts + 1):
                try:
                    async with asyncio.timeout(self.settings.embedding_request_timeout):
                        result = await self.provider.embed_batch(batch)
                    if not isinstance(result, list) or len(result) != len(batch):
                        raise EmbeddingError("invalid_embedding_response", True)
                    validated = [self.validate_vector(vector) for vector in result]
                    vectors.extend(validated)
                    break
                except (TimeoutError, OSError) as exc:
                    error = EmbeddingError("embedding_provider_unavailable", True)
                    error.__cause__ = exc
                except EmbeddingError as exc:
                    error = exc
                logger.warning("embedding_failed:%s:attempt=%s", error.code, attempt)
                if not error.retryable or attempt == self.settings.embedding_max_attempts:
                    raise error
                await asyncio.sleep(self.settings.embedding_retry_backoff * attempt)
        return vectors
