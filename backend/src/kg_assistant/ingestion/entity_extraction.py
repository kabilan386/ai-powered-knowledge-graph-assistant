import asyncio
import logging

from kg_assistant.core.config import Settings
from kg_assistant.ingestion.normalization import name_in_text, normalize_extraction, normalize_name
from kg_assistant.models.extraction import ExtractionResult, NormalizedExtraction
from kg_assistant.providers.base import ExtractionError, ExtractionProvider

logger = logging.getLogger(__name__)


class EntityExtractionService:
    def __init__(self, provider: ExtractionProvider, settings: Settings) -> None:
        self.provider = provider
        self.settings = settings

    async def extract(self, text: str) -> tuple[NormalizedExtraction, int]:
        for attempt in range(1, self.settings.llm_max_attempts + 1):
            try:
                async with asyncio.timeout(self.settings.llm_request_timeout):
                    result = await self.provider.extract(text)
                self.validate(result, text)
                return normalize_extraction(result), attempt
            except TimeoutError:
                error = ExtractionError("llm_timeout")
            except ExtractionError as exc:
                error = exc
            logger.warning("chunk_extraction_attempt_failed:%s:attempt=%s", error.code, attempt)
            if not error.retryable or attempt == self.settings.llm_max_attempts:
                error.attempts = attempt
                raise error
            await asyncio.sleep(self.settings.llm_retry_backoff * attempt)
        raise RuntimeError("Unreachable retry state")

    def validate(self, result: ExtractionResult, text: str) -> None:
        if not isinstance(result, ExtractionResult):
            raise ExtractionError("llm_invalid_response")
        entities = {entity.key: entity for entity in result.entities}
        for entity in result.entities:
            if entity.type not in self.settings.entity_types or not normalize_name(entity.name):
                raise ExtractionError("llm_invalid_entity")
            if entity.evidence_quote not in text or not name_in_text(
                entity.name, entity.evidence_quote
            ):
                raise ExtractionError("llm_unsupported_evidence")
        for relationship in result.relationships:
            if relationship.type not in self.settings.relationship_types:
                raise ExtractionError("llm_invalid_relationship")
            if relationship.evidence_quote not in text:
                raise ExtractionError("llm_unsupported_evidence")
            for key in (relationship.source, relationship.target):
                if not name_in_text(entities[key].name, relationship.evidence_quote):
                    raise ExtractionError("llm_unsupported_evidence")
