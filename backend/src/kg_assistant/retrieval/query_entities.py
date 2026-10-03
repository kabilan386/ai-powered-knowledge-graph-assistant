import asyncio
import logging

from kg_assistant.core.config import Settings
from kg_assistant.ingestion.normalization import name_in_text, normalize_name
from kg_assistant.models.graph_retrieval import QueryExtraction
from kg_assistant.providers.base import ExtractionError
from kg_assistant.providers.query_entities import QueryEntityProvider

logger = logging.getLogger(__name__)


class QueryEntityExtractionService:
    def __init__(self, settings: Settings, provider: QueryEntityProvider) -> None:
        self.settings = settings
        self.provider = provider

    def validate(self, result: QueryExtraction, question: str) -> QueryExtraction:
        if not isinstance(result, QueryExtraction):
            raise ExtractionError("query_extraction_invalid_response")
        if any(
            not name_in_text(entity.name, question)
            or (entity.type is not None and entity.type not in self.settings.entity_types)
            for entity in result.entities
        ):
            raise ExtractionError("query_extraction_unsupported_anchor")
        if any(kind not in self.settings.relationship_types for kind in result.relationship_types):
            raise ExtractionError("query_extraction_invalid_intent")
        if result.target_type is not None and result.target_type not in self.settings.entity_types:
            raise ExtractionError("query_extraction_invalid_intent")
        unique = {(normalize_name(entity.name), entity.type): entity for entity in result.entities}
        return result.model_copy(update={"entities": list(unique.values())})

    async def extract(self, question: str) -> QueryExtraction:
        for attempt in range(1, self.settings.llm_max_attempts + 1):
            try:
                async with asyncio.timeout(self.settings.llm_request_timeout):
                    result = await self.provider.extract(question)
                return self.validate(result, question)
            except (TimeoutError, OSError):
                error = ExtractionError("query_extraction_unavailable")
            except ExtractionError as exc:
                error = exc
            logger.warning("query_entity_extraction_failed:%s:attempt=%s", error.code, attempt)
            if not error.retryable or attempt == self.settings.llm_max_attempts:
                raise error
            await asyncio.sleep(self.settings.llm_retry_backoff * attempt)
        raise RuntimeError("Unreachable retry state")
