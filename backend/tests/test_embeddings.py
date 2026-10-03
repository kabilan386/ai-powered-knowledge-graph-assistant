from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from openai import APIConnectionError, APIStatusError
from pydantic import ValidationError

from kg_assistant.core.config import Settings
from kg_assistant.providers.embeddings import EmbeddingError, OpenAIEmbeddingProvider
from kg_assistant.services.embeddings import EmbeddingService


def embedding_settings(**overrides):
    return Settings(
        _env_file=None,
        neo4j_password="test-only-password",
        embedding_enabled=True,
        openai_api_key="mock-only-key",
        embedding_model="mock-embedding",
        embedding_dimensions=3,
        embedding_retry_backoff=0,
        **overrides,
    )


async def test_batch_splitting_and_float_output():
    settings = embedding_settings(embedding_batch_size=2)
    provider = AsyncMock()
    provider.embed_batch.side_effect = [[[1, 2, 3], [2, 1, 3]], [[3, 2, 1]]]
    service = EmbeddingService(provider, settings)
    result = await service.embed_batch(["one", "two", "three"])
    assert result == [[1.0, 2.0, 3.0], [2.0, 1.0, 3.0], [3.0, 2.0, 1.0]]
    assert provider.embed_batch.await_args_list[0].args == (["one", "two"],)
    assert provider.embed_batch.await_args_list[1].args == (["three"],)
    assert all(isinstance(value, float) for vector in result for value in vector)


@pytest.mark.parametrize(
    "vector,code",
    [
        ([1, 2], "embedding_dimension_mismatch"),
        ([1, float("nan"), 2], "invalid_embedding_response"),
        ([1, float("inf"), 2], "invalid_embedding_response"),
        ([True, 2, 3], "invalid_embedding_response"),
        (["1", 2, 3], "invalid_embedding_response"),
        ([0, 0, 0], "invalid_embedding_response"),
    ],
)
def test_vector_validation(vector, code):
    with pytest.raises(EmbeddingError, match=code):
        EmbeddingService(AsyncMock(), embedding_settings()).validate_vector(vector)


async def test_retry_does_not_keep_partial_invalid_batch():
    provider = AsyncMock()
    provider.embed_batch.side_effect = [
        [[1, 2, 3], [0, 0, 0]],
        [[1, 2, 3], [2, 3, 1]],
    ]
    result = await EmbeddingService(provider, embedding_settings()).embed_batch(["one", "two"])
    assert len(result) == 2
    assert provider.embed_batch.await_count == 2


async def test_failure_retry_and_exhaustion():
    provider = AsyncMock()
    provider.embed_batch.side_effect = EmbeddingError("embedding_provider_unavailable", True)
    with pytest.raises(EmbeddingError, match="embedding_provider_unavailable"):
        await EmbeddingService(provider, embedding_settings()).embed_text("one")
    assert provider.embed_batch.await_count == 2


async def test_dimension_mismatch_does_not_retry():
    provider = AsyncMock()
    provider.embed_batch.return_value = [[1, 2]]
    with pytest.raises(EmbeddingError, match="embedding_dimension_mismatch"):
        await EmbeddingService(provider, embedding_settings()).embed_text("one")
    assert provider.embed_batch.await_count == 1


@pytest.mark.parametrize(
    "text,code",
    [
        ("   ", "empty_embedding_input"),
        ("abcdef", "embedding_input_too_large"),
    ],
)
async def test_input_validation(text, code):
    provider = AsyncMock()
    with pytest.raises(EmbeddingError, match=code):
        await EmbeddingService(
            provider, embedding_settings(embedding_max_input_characters=5)
        ).embed_text(text)
    provider.embed_batch.assert_not_awaited()


async def test_cardinality_and_timeout():
    provider = AsyncMock()
    provider.embed_batch.return_value = None
    with pytest.raises(EmbeddingError, match="invalid_embedding_response"):
        await EmbeddingService(provider, embedding_settings()).embed_text("one")
    provider.embed_batch.side_effect = TimeoutError()
    with pytest.raises(EmbeddingError, match="embedding_provider_unavailable"):
        await EmbeddingService(provider, embedding_settings()).embed_text("one")


async def test_openai_batch_order_dimensions_and_close():
    client = AsyncMock()
    client.embeddings.create.return_value = SimpleNamespace(
        data=[
            SimpleNamespace(index=1, embedding=[2.0, 3.0, 1.0]),
            SimpleNamespace(index=0, embedding=[1.0, 2.0, 3.0]),
        ]
    )
    with patch("kg_assistant.providers.embeddings.AsyncOpenAI", return_value=client) as factory:
        adapter = OpenAIEmbeddingProvider(embedding_settings())
        assert await adapter.embed_batch(["one", "two"]) == [[1.0, 2.0, 3.0], [2.0, 3.0, 1.0]]
        client.embeddings.create.assert_awaited_once_with(
            model="mock-embedding",
            input=["one", "two"],
            encoding_format="float",
            dimensions=3,
        )
        assert factory.call_args.kwargs["max_retries"] == 0
        await adapter.close()
        client.close.assert_awaited_once()


async def test_openai_native_dimensions_and_bad_indexes():
    client = AsyncMock()
    client.embeddings.create.return_value = SimpleNamespace(
        data=[
            SimpleNamespace(index=0, embedding=[1.0, 2.0, 3.0]),
            SimpleNamespace(index=0, embedding=[1.0, 2.0, 3.0]),
        ]
    )
    with patch("kg_assistant.providers.embeddings.AsyncOpenAI", return_value=client):
        adapter = OpenAIEmbeddingProvider(embedding_settings(embedding_request_dimensions=False))
        with pytest.raises(EmbeddingError, match="invalid_embedding_response"):
            await adapter.embed_batch(["one", "two"])
        assert "dimensions" not in client.embeddings.create.call_args.kwargs


@pytest.mark.parametrize("status,retryable", [(400, False), (401, False), (429, True), (503, True)])
async def test_openai_status_error_is_sanitized(status, retryable):
    client = AsyncMock()
    response = httpx.Response(status, request=httpx.Request("POST", "https://api.openai.com"))
    client.embeddings.create.side_effect = APIStatusError(
        "private secret", response=response, body=None
    )
    with patch("kg_assistant.providers.embeddings.AsyncOpenAI", return_value=client):
        with pytest.raises(EmbeddingError) as failure:
            await OpenAIEmbeddingProvider(embedding_settings()).embed_batch(["one"])
    assert failure.value.retryable is retryable
    assert "private" not in str(failure.value)


async def test_openai_connection_failure():
    client = AsyncMock()
    client.embeddings.create.side_effect = APIConnectionError(
        request=httpx.Request("POST", "https://api.openai.com")
    )
    with patch("kg_assistant.providers.embeddings.AsyncOpenAI", return_value=client):
        with pytest.raises(EmbeddingError) as failure:
            await OpenAIEmbeddingProvider(embedding_settings()).embed_batch(["one"])
    assert failure.value.retryable


@pytest.mark.parametrize(
    "options",
    [
        {"embedding_enabled": True},
        {"embedding_enabled": True, "openai_api_key": "mock"},
        {"embedding_dimensions": 0},
        {"embedding_dimensions": 4097},
    ],
)
def test_settings_validation(options):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, neo4j_password="test-only", **options)
