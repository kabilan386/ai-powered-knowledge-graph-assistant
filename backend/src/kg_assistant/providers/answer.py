import json
from typing import Protocol

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from pydantic import ValidationError

from kg_assistant.core.config import Settings
from kg_assistant.models.graphrag import FusedContext, GroundedAnswer
from kg_assistant.prompts.answer import ANSWER_INSTRUCTIONS
from kg_assistant.providers.base import ExtractionError
from kg_assistant.providers.usage import UsageObserver, observe_usage


class AnswerProvider(Protocol):
    async def generate(self, question: str, context: FusedContext) -> GroundedAnswer: ...
    async def close(self) -> None: ...


class OpenAIAnswerProvider:
    def __init__(self, settings: Settings, usage_observer: UsageObserver | None = None) -> None:
        self.settings = settings
        self.usage_observer = usage_observer
        if settings.openai_api_key is None:
            raise ValueError("Configure the answer API key")
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=settings.llm_request_timeout,
            max_retries=0,
        )

    async def generate(self, question: str, context: FusedContext) -> GroundedAnswer:
        return await self._generate(question, context)

    async def generate_with_feedback(
        self, question: str, context: FusedContext, error_code: str
    ) -> GroundedAnswer:
        return await self._generate(question, context, error_code)

    async def _generate(
        self, question: str, context: FusedContext, error_code: str | None = None
    ) -> GroundedAnswer:
        instructions = ANSWER_INSTRUCTIONS
        if error_code == "answer_invalid_citation":
            instructions += (
                "\nYour previous response failed citation validation. If the requested fact "
                "is absent or explicitly not documented, set insufficient_evidence=true with "
                "an empty citations list. Otherwise include literal separate [S1] or [G1] "
                "markers using only supplied IDs, and the same bare IDs in citations, unique "
                "and in first-appearance order. Do not invent or add evidence."
            )
        try:
            response = await self.client.responses.parse(
                model=self.settings.llm_model,
                instructions=instructions,
                input=[
                    {
                        "role": "user",
                        "content": json.dumps(
                            {"question": question, "context": context.model_dump()},
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    }
                ],
                text_format=GroundedAnswer,
                max_output_tokens=self.settings.llm_max_output_tokens,
                store=False,
            )
        except (APIConnectionError, APITimeoutError) as exc:
            raise ExtractionError("answer_provider_unavailable") from exc
        except APIStatusError as exc:
            raise ExtractionError(
                "answer_provider_error", exc.status_code == 429 or exc.status_code >= 500
            ) from exc
        except ValidationError as exc:
            raise ExtractionError("answer_invalid_response") from exc
        observe_usage(response, self.usage_observer)
        if response.status != "completed" or not isinstance(response.output_parsed, GroundedAnswer):
            raise ExtractionError("answer_invalid_response")
        return response.output_parsed

    async def close(self) -> None:
        await self.client.close()
