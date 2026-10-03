from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from pydantic import ValidationError

from kg_assistant.core.config import Settings
from kg_assistant.models.extraction import ExtractionResult
from kg_assistant.prompts.extraction import EXTRACTION_INSTRUCTIONS
from kg_assistant.providers.base import ExtractionError


class OpenAIExtractionProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        if settings.openai_api_key is None:
            raise ValueError("An API key is required when LLM extraction is enabled")
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=settings.llm_request_timeout,
            max_retries=0,
        )

    async def extract(self, text: str) -> ExtractionResult:
        try:
            response = await self.client.responses.parse(
                model=self.settings.llm_model,
                instructions=EXTRACTION_INSTRUCTIONS.format(
                    entity_types=", ".join(self.settings.entity_types),
                    relationship_types=", ".join(self.settings.relationship_types),
                ),
                input=[{"role": "user", "content": text}],
                text_format=ExtractionResult,
                max_output_tokens=self.settings.llm_max_output_tokens,
                store=False,
            )
        except (APIConnectionError, APITimeoutError) as exc:
            raise ExtractionError("llm_unavailable") from exc
        except APIStatusError as exc:
            raise ExtractionError(
                "llm_provider_error", retryable=exc.status_code == 429 or exc.status_code >= 500
            ) from exc
        except ValidationError as exc:
            raise ExtractionError("llm_invalid_response") from exc
        if response.status != "completed" or not isinstance(
            response.output_parsed, ExtractionResult
        ):
            raise ExtractionError("llm_invalid_response")
        return response.output_parsed

    async def close(self) -> None:
        await self.client.close()
