from typing import Protocol

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from pydantic import ValidationError

from kg_assistant.core.config import Settings
from kg_assistant.models.graph_retrieval import QueryExtraction
from kg_assistant.prompts.query_entities import QUERY_INSTRUCTIONS
from kg_assistant.providers.base import ExtractionError
from kg_assistant.providers.usage import UsageObserver, observe_usage


class QueryEntityProvider(Protocol):
    async def extract(self, question: str) -> QueryExtraction: ...
    async def close(self) -> None: ...


class OpenAIQueryEntityProvider:
    def __init__(self, settings: Settings, usage_observer: UsageObserver | None = None) -> None:
        self.settings = settings
        self.usage_observer = usage_observer
        if settings.openai_api_key is None:
            raise ValueError("Configure the query extraction API key")
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=settings.llm_request_timeout,
            max_retries=0,
        )

    async def extract(self, question: str) -> QueryExtraction:
        try:
            response = await self.client.responses.parse(
                model=self.settings.llm_model,
                instructions=QUERY_INSTRUCTIONS.format(
                    entity_types=", ".join(self.settings.entity_types),
                    relationship_types=", ".join(self.settings.relationship_types),
                ),
                input=[{"role": "user", "content": question}],
                text_format=QueryExtraction,
                max_output_tokens=self.settings.llm_max_output_tokens,
                store=False,
            )
        except (APIConnectionError, APITimeoutError) as exc:
            raise ExtractionError("query_extraction_unavailable") from exc
        except APIStatusError as exc:
            raise ExtractionError(
                "query_extraction_provider_error", exc.status_code == 429 or exc.status_code >= 500
            ) from exc
        except ValidationError as exc:
            raise ExtractionError("query_extraction_invalid_response") from exc
        observe_usage(response, self.usage_observer)
        if response.status != "completed" or not isinstance(
            response.output_parsed, QueryExtraction
        ):
            raise ExtractionError("query_extraction_invalid_response")
        return response.output_parsed

    async def close(self) -> None:
        await self.client.close()
