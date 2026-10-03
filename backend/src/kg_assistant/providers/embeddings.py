from typing import Protocol

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from kg_assistant.core.config import Settings


class EmbeddingError(Exception):
    def __init__(self, code: str, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


class EmbeddingProvider(Protocol):
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...
    async def close(self) -> None: ...


class OpenAIEmbeddingProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=settings.embedding_request_timeout,
            max_retries=0,
        )

    async def close(self) -> None:
        await self.client.close()

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        options = {}
        if self.settings.embedding_request_dimensions:
            options["dimensions"] = self.settings.embedding_dimensions
        try:
            result = await self.client.embeddings.create(
                model=self.settings.embedding_model,
                input=texts,
                encoding_format="float",
                **options,
            )
        except (APIConnectionError, APITimeoutError) as exc:
            raise EmbeddingError("embedding_provider_unavailable", True) from exc
        except APIStatusError as exc:
            raise EmbeddingError(
                "embedding_provider_error", exc.status_code == 429 or exc.status_code >= 500
            ) from exc
        if sorted(item.index for item in result.data) != list(range(len(texts))):
            raise EmbeddingError("invalid_embedding_response", True)
        return [item.embedding for item in sorted(result.data, key=lambda item: item.index)]
