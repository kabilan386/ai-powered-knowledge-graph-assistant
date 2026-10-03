import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from graph_fixtures import SAMPLE, sample_extraction
from pydantic import ValidationError

from kg_assistant.core.config import Settings
from kg_assistant.ingestion.entity_extraction import EntityExtractionService
from kg_assistant.ingestion.normalization import normalize_extraction, normalize_name
from kg_assistant.models.extraction import ExtractedEntity, ExtractionResult
from kg_assistant.providers.base import ExtractionError
from kg_assistant.providers.openai import OpenAIExtractionProvider


def test_structured_schema_and_json():
    result = sample_extraction()
    assert ExtractionResult.model_validate_json(result.model_dump_json()) == result
    assert len(result.entities) == 4
    assert [r.type for r in result.relationships] == ["MANAGES", "USES", "HOSTED_ON"]


@pytest.mark.parametrize(
    "payload",
    [
        "arbitrary free-form response",
        {"entities": []},
        {"entities": [], "relationships": [], "unexpected": True},
        {
            "entities": [{"key": "a", "name": 123, "type": "PERSON", "evidence_quote": "123"}],
            "relationships": [],
        },
    ],
)
def test_invalid_schema(payload):
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate(payload)


def test_unknown_endpoint_and_duplicate_keys():
    payload = sample_extraction().model_dump()
    payload["relationships"][0]["target"] = "not-an-entity"
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate(payload)
    payload = sample_extraction().model_dump()
    payload["entities"][1]["key"] = "team"
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate(payload)


def test_normalization_type_aware_and_canonical_display():
    assert normalize_name("  Neo4J  ") == "neo4j"
    assert normalize_name("Ｎｅｏ４ｊ") == "neo4j"
    assert normalize_name("Payment\t  Service") == "payment service"
    result = ExtractionResult(
        entities=[
            ExtractedEntity(key=str(i), name=name, type=kind, evidence_quote=name)
            for i, (name, kind) in enumerate(
                [
                    ("Neo4j", "TECHNOLOGY"),
                    ("neo4j", "TECHNOLOGY"),
                    ("Neo4J", "TECHNOLOGY"),
                    ("Neo4j", "DATABASE"),
                ]
            )
        ],
        relationships=[],
    )
    normalized = normalize_extraction(result)
    assert len(normalized.entities) == 2
    assert normalized.entities[0].name == "Neo4j"
    assert normalized.entities[0].normalized_name == "neo4j"
    assert normalized.entities[0].id != normalized.entities[1].id
    assert normalized == normalize_extraction(result)


def test_relationship_mapping_and_deduplication():
    result = sample_extraction()
    result.entities.append(
        ExtractedEntity(key="redis-alias", name="redis", type="TECHNOLOGY", evidence_quote="Redis")
    )
    relation = result.relationships[1].model_copy(update={"target": "redis-alias"})
    result.relationships.append(relation)
    normalized = normalize_extraction(result)
    ids = {e.name: e.id for e in normalized.entities}
    assert len(normalized.entities) == 4
    assert len(normalized.relationships) == 3
    assert normalized.relationships[1].source_id == ids["Payment Service"]
    assert normalized.relationships[1].target_id == ids["Redis"]


async def test_valid_extraction_and_empty_result(settings):
    provider = AsyncMock()
    provider.extract.return_value = sample_extraction()
    normalized, attempts = await EntityExtractionService(provider, settings).extract(SAMPLE)
    assert len(normalized.entities) == 4 and attempts == 1
    provider.extract.return_value = ExtractionResult(entities=[], relationships=[])
    empty, attempts = await EntityExtractionService(provider, settings).extract("No facts here")
    assert empty.entities == [] and empty.relationships == []


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("entity_type", "llm_invalid_entity"),
        ("relationship_type", "llm_invalid_relationship"),
        ("quote", "llm_unsupported_evidence"),
        ("endpoint_quote", "llm_unsupported_evidence"),
    ],
)
async def test_grounding_and_types(settings, mutation, code):
    settings.llm_max_attempts = 1
    result = sample_extraction()
    if mutation == "entity_type":
        result.entities[0].type = "NOT_ALLOWED"
    elif mutation == "relationship_type":
        result.relationships[0].type = "HAS_CHUNK"
    elif mutation == "quote":
        result.relationships[0].evidence_quote = "Platform Team created Redis."
    else:
        result.relationships[0].evidence_quote = "Redis"
    provider = AsyncMock()
    provider.extract.return_value = result
    with pytest.raises(ExtractionError) as caught:
        await EntityExtractionService(provider, settings).extract(SAMPLE)
    assert caught.value.code == code


async def test_invalid_response_retry_and_transient_retry(settings):
    settings.llm_retry_backoff = 0
    provider = AsyncMock()
    provider.extract.side_effect = ["free-form prose", sample_extraction()]
    _, attempts = await EntityExtractionService(provider, settings).extract(SAMPLE)
    assert attempts == 2
    provider.extract.side_effect = [ExtractionError("llm_unavailable"), sample_extraction()]
    _, attempts = await EntityExtractionService(provider, settings).extract(SAMPLE)
    assert attempts == 2


async def test_exhausted_and_nonretryable_errors(settings):
    settings.llm_retry_backoff = 0
    provider = AsyncMock()
    provider.extract.side_effect = ExtractionError("llm_invalid_response")
    with pytest.raises(ExtractionError) as caught:
        await EntityExtractionService(provider, settings).extract(SAMPLE)
    assert caught.value.attempts == 2
    provider.extract.reset_mock()
    provider.extract.side_effect = ExtractionError("llm_provider_error", retryable=False)
    with pytest.raises(ExtractionError) as caught:
        await EntityExtractionService(provider, settings).extract(SAMPLE)
    assert caught.value.attempts == 1
    provider.extract.assert_awaited_once()


async def test_openai_uses_structured_outputs_without_network(settings):
    settings.openai_api_key = Settings(
        _env_file=None, neo4j_password="test", openai_api_key="test-key"
    ).openai_api_key
    settings.llm_model = "configured-test-model"
    client = AsyncMock()
    response = MagicMock(status="completed", output_parsed=sample_extraction())
    client.responses.parse.return_value = response
    with patch("kg_assistant.providers.openai.AsyncOpenAI", return_value=client) as factory:
        provider = OpenAIExtractionProvider(settings)
        assert await provider.extract(SAMPLE) == sample_extraction()
        kwargs = client.responses.parse.call_args.kwargs
        assert kwargs["text_format"] is ExtractionResult
        assert kwargs["store"] is False
        assert kwargs["model"] == "configured-test-model"
        assert factory.call_args.kwargs["max_retries"] == 0
        client.responses.parse.return_value = MagicMock(status="completed", output_parsed=None)
        with pytest.raises(ExtractionError):
            await provider.extract(SAMPLE)
        await provider.close()
        client.close.assert_awaited_once()


@pytest.mark.parametrize("types", [["USES); DELETE n"], ["MENTIONS"], ["USES", "USES"], []])
def test_invalid_configured_types(types):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, neo4j_password="test", relationship_types=types)


def test_enabled_requires_credentials_and_model():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, neo4j_password="test", llm_extraction_enabled=True)
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            neo4j_password="test",
            llm_extraction_enabled=True,
            openai_api_key="test",
        )


async def test_provider_timeout_is_bounded(settings):
    settings.llm_request_timeout = 0.01
    settings.llm_max_attempts = 1
    provider = AsyncMock()

    async def slow(text):
        await asyncio.sleep(1)
        return sample_extraction()

    provider.extract.side_effect = slow
    with pytest.raises(ExtractionError) as caught:
        await EntityExtractionService(provider, settings).extract(SAMPLE)
    assert caught.value.code == "llm_timeout"
    assert caught.value.attempts == 1
