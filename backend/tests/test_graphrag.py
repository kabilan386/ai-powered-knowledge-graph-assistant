import asyncio
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from graphrag_fixtures import QUESTION, config, evidence
from openai import APIConnectionError, APIStatusError
from pydantic import ValidationError

from kg_assistant.api.dependencies import get_graphrag
from kg_assistant.core.config import Settings
from kg_assistant.core.exceptions import IngestionError
from kg_assistant.core.logging import JsonFormatter
from kg_assistant.main import create_app
from kg_assistant.models.graphrag import AskRequest, FusedContext, GroundedAnswer
from kg_assistant.providers.answer import OpenAIAnswerProvider
from kg_assistant.providers.base import ExtractionError
from kg_assistant.retrieval.context import ContextBuilder
from kg_assistant.services.answers import (
    INSUFFICIENT_ANSWER,
    AnswerGenerationService,
    map_sources,
    validate_answer,
)
from kg_assistant.services.graphrag import GraphRAGService


def service_for(settings=None):
    settings = settings or config()
    vector, graph, chunks = evidence()
    v, g, repository, provider = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    v.search.return_value = vector
    g.search.return_value = graph
    repository.load_chunks.return_value = chunks
    generator = AnswerGenerationService(settings, provider)
    service = GraphRAGService(settings, v, g, repository, ContextBuilder(settings), generator)
    provider.generate.return_value = GroundedAnswer(
        answer="Redis is hosted on AWS ElastiCache [S3].",
        citations=["S3"],
        insufficient_evidence=False,
    )
    return service, v, g, repository, provider


def test_context_deduplication_ids_support_and_determinism():
    vector, graph, chunks = evidence()
    vector.results.append(vector.results[0])
    graph.paths.append(graph.paths[0])
    builder = ContextBuilder(config())
    result = builder.build(vector, graph, chunks)
    assert len(result.text_evidence) == 3 and len(result.graph_evidence) == 1
    assert [item.citation for item in result.text_evidence] == ["S1", "S2", "S3"]
    assert result.text_evidence[0].chunk_id == "c1"
    assert all(edge.document_backed for edge in result.graph_evidence[0].edges)
    assert result.graph_evidence[0].edges[0].source_citations == ["S2"]
    assert builder.references(vector, graph) == [("d", "c0"), ("d", "c1"), ("d", "c2")]
    assert result == builder.build(vector, graph, list(reversed(chunks)))
    vector.results.reverse()
    assert result == builder.build(vector, graph, chunks)


def test_context_limits_graph_only_no_provenance_and_missing_sources():
    vector, graph, chunks = evidence()
    limited = ContextBuilder(config(max_context_chunks=1)).build(vector, graph, chunks)
    assert len(limited.text_evidence) == 1 and limited.truncated
    assert limited.graph_evidence[0].edges[0].document_backed is False
    budget = ContextBuilder(config(max_context_characters=1000)).build(vector, graph, chunks)
    assert len(budget.payload()) <= 1000 and budget.truncated
    vector.results = []
    for edge in graph.paths[0].edges:
        edge.evidence = []
    result = ContextBuilder(config()).build(vector, graph, [])
    assert not result.text_evidence and result.graph_evidence[0].citation == "G1"
    assert all(not edge.document_backed for edge in result.graph_evidence[0].edges)
    # Broken provenance does not inherit claimed filenames from the graph retriever.
    vector, graph, _ = evidence()
    result = ContextBuilder(config()).build(vector, graph, [])
    assert not result.text_evidence
    assert all(not edge.source_citations for edge in result.graph_evidence[0].edges)


def test_graph_path_cap_and_redundant_prefix():
    vector, graph, chunks = evidence()
    path = graph.paths[0]
    prefix = path.model_copy(
        update={
            "hop_count": 1,
            "nodes": path.nodes[:2],
            "edges": path.edges[:1],
            "relationships": path.relationships[:1],
            "score": 35,
        }
    )
    graph.paths.append(prefix)
    result = ContextBuilder(config(max_graph_paths=1)).build(vector, graph, chunks)
    assert len(result.graph_evidence) == 1 and result.graph_evidence[0].hop_count == 3
    assert result.truncated


@pytest.mark.parametrize(
    "answer,citations",
    [
        ("Invented [S99].", ["S99"]),
        ("Invented [S99].", ["S1"]),
        ("Fact [S1].", ["S2"]),
        ("Fact without inline citations.", ["S1"]),
        ("Fact [S1].", []),
        ("Fact [S1].", ["S1", "S1"]),
        ("Fact [G99].", ["G99"]),
        ("Fact [S99 ].", ["S1"]),
    ],
)
def test_invalid_citations(answer, citations):
    vector, graph, chunks = evidence()
    context = ContextBuilder(config()).build(vector, graph, chunks)
    with pytest.raises(ExtractionError, match="answer_invalid_citation"):
        validate_answer(
            GroundedAnswer(answer=answer, citations=citations, insufficient_evidence=False), context
        )


def test_sources_graph_support_and_insufficient_normalization():
    vector, graph, chunks = evidence()
    context = ContextBuilder(config()).build(vector, graph, chunks)
    result = validate_answer(
        GroundedAnswer(
            answer="The chain ends at ElastiCache [G1].",
            citations=["G1"],
            insufficient_evidence=False,
        ),
        context,
    )
    sources = map_sources(result.citations, context)
    assert sources[0].kind == "graph" and sources[0].filename is None
    assert set(sources[0].supporting_citations) == {"S1", "S2", "S3"}
    assert len(sources) == 4 and sources[1].document_id == "d"
    result = validate_answer(
        GroundedAnswer(answer="The CEO is invented.", citations=[], insufficient_evidence=True),
        context,
    )
    assert result.answer == INSUFFICIENT_ANSWER and result.citations == []


async def test_orchestration_both_retrievers_concurrently_and_metadata():
    service, v, g, repo, provider = service_for()
    started = asyncio.Event()
    vector_response = v.search.return_value
    graph_response = g.search.return_value

    async def vector(request):
        await asyncio.wait_for(started.wait(), 1)
        return vector_response

    async def graph(request):
        started.set()
        return graph_response

    v.search.side_effect = vector
    g.search.side_effect = graph
    response = await service.ask(AskRequest(question=QUESTION), "request-id")
    assert response.citations == ["S3"] and response.sources[0].chunk_id == "c2"
    assert response.retrieval.vector_results == 3 and response.retrieval.graph_paths == 1
    assert response.retrieval.context_chunks == 3 and response.retrieval.context_graph_paths == 1
    assert response.retrieval.duration_ms > 0
    assert v.search.call_args.args[0].top_k == 5
    assert g.search.call_args.args[0].max_hops == 3
    provider.generate.assert_awaited_once()


@pytest.mark.parametrize("mode", ["graph_only", "vector_only", "combined"])
async def test_retrieval_modes(mode):
    service, v, g, repo, provider = service_for()
    if mode == "vector_only":
        g.search.return_value.paths = []
        g.search.return_value.status = "no_paths"
    if mode == "graph_only":
        v.search.return_value.results = []
        for edge in g.search.return_value.paths[0].edges:
            edge.evidence = []
        provider.generate.return_value = GroundedAnswer(
            answer="The graph shows Redis [G1].", citations=["G1"], insufficient_evidence=False
        )
    response = await service.ask(AskRequest(question=QUESTION))
    assert not response.insufficient_evidence
    v.search.assert_awaited_once()
    g.search.assert_awaited_once()
    if mode == "graph_only":
        assert (
            response.sources[0].kind == "graph" and response.sources[0].supporting_citations == []
        )


async def test_no_evidence_bypasses_generation_and_irrelevant_evidence():
    service, v, g, repo, provider = service_for()
    v.search.return_value.results = []
    g.search.return_value.paths = []
    response = await service.ask(AskRequest(question="Who is the CEO of Payment Service?"))
    assert response.insufficient_evidence and response.answer == INSUFFICIENT_ANSWER
    assert response.sources == [] and response.citations == []
    provider.generate.assert_not_awaited()
    service, v, g, repo, provider = service_for()
    provider.generate.return_value = GroundedAnswer(
        answer="I cannot find the CEO.", citations=[], insufficient_evidence=True
    )
    response = await service.ask(AskRequest(question="Who is the CEO of Payment Service?"))
    assert response.insufficient_evidence and not response.sources
    assert response.answer == INSUFFICIENT_ANSWER


async def test_bad_citation_retry_then_error_and_provider_failure():
    service, v, g, repo, provider = service_for()
    invalid = GroundedAnswer(
        answer="Invented [S99].", citations=["S99"], insufficient_evidence=False
    )
    provider.generate.return_value = invalid
    with pytest.raises(IngestionError) as error:
        await service.ask(AskRequest(question=QUESTION))
    assert error.value.status_code == 502 and error.value.code == "answer_invalid_citation"
    assert provider.generate.await_count == 2
    provider.generate.reset_mock()
    provider.generate.side_effect = ExtractionError("answer_provider_error", False)
    with pytest.raises(IngestionError) as error:
        await service.ask(AskRequest(question=QUESTION))
    assert error.value.code == "answer_provider_error" and provider.generate.await_count == 1


@pytest.mark.parametrize("branch", ["vector", "graph"])
async def test_retrieval_failure_is_not_empty_evidence(branch):
    service, v, g, repo, provider = service_for()
    (v if branch == "vector" else g).search.side_effect = IngestionError(
        "retrieval_failure", "Unavailable", 503
    )
    with pytest.raises(IngestionError) as error:
        await service.ask(AskRequest(question=QUESTION))
    assert error.value.status_code == 503
    v.search.assert_awaited_once()
    g.search.assert_awaited_once()
    provider.generate.assert_not_awaited()


async def test_database_failure_timeout_and_disabled(settings):
    service, v, g, repo, provider = service_for()
    repo.load_chunks.side_effect = OSError("private details")
    with pytest.raises(IngestionError) as error:
        await service.ask(AskRequest(question=QUESTION))
    assert error.value.status_code == 503 and "private" not in error.value.message
    service, v, g, repo, provider = service_for(config(graphrag_request_timeout=0.01))

    async def slow(*args):
        await asyncio.sleep(1)

    v.search.side_effect = slow
    with pytest.raises(IngestionError) as error:
        await service.ask(AskRequest(question=QUESTION))
    assert error.value.status_code == 503
    service.settings = settings
    with pytest.raises(IngestionError) as error:
        await service.ask(AskRequest(question=QUESTION))
    assert error.value.code == "graphrag_disabled"


async def test_answer_adapter_structured_output_and_refusal():
    client = AsyncMock()
    result = GroundedAnswer(
        answer="Insufficient evidence.", citations=[], insufficient_evidence=True
    )
    client.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed=result)
    with patch("kg_assistant.providers.answer.AsyncOpenAI", return_value=client) as factory:
        adapter = OpenAIAnswerProvider(config())
        assert await adapter.generate("q", FusedContext()) == result
        assert client.responses.parse.call_args.kwargs["text_format"] is GroundedAnswer
        assert client.responses.parse.call_args.kwargs["store"] is False
        assert factory.call_args.kwargs["max_retries"] == 0
        client.responses.parse.return_value = SimpleNamespace(
            status="completed", output_parsed=None
        )
        with pytest.raises(ExtractionError):
            await adapter.generate("q", FusedContext())
        await adapter.close()
        client.close.assert_awaited_once()


@pytest.mark.parametrize("status,retryable", [(400, False), (429, True), (503, True)])
async def test_answer_provider_api_errors(status, retryable):
    client = AsyncMock()
    response = httpx.Response(status, request=httpx.Request("POST", "https://api.openai.com"))
    client.responses.parse.side_effect = APIStatusError("private", response=response, body=None)
    with patch("kg_assistant.providers.answer.AsyncOpenAI", return_value=client):
        with pytest.raises(ExtractionError) as error:
            await OpenAIAnswerProvider(config()).generate("q", FusedContext())
        assert error.value.retryable is retryable
        assert "private" not in str(error.value)
    client.responses.parse.side_effect = APIConnectionError(
        request=httpx.Request("POST", "https://api.openai.com")
    )
    with patch("kg_assistant.providers.answer.AsyncOpenAI", return_value=client):
        with pytest.raises(ExtractionError, match="answer_provider_unavailable"):
            await OpenAIAnswerProvider(config()).generate("q", FusedContext())


async def test_api_validation_and_success():
    service, v, g, repo, provider = service_for()
    app = create_app(config())
    app.dependency_overrides[get_graphrag] = lambda: service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for body in (
            {"question": ""},
            {"question": " \n "},
            {"question": "q", "cypher": "MATCH (n)"},
            {"question": "q" * 4001},
        ):
            assert (await client.post("/api/graphrag/ask", json=body)).status_code == 422
        response = await client.post("/api/graphrag/ask", json={"question": QUESTION})
        assert response.status_code == 200, response.text
        assert response.json()["sources"][0]["chunk_id"] == "c2"
        assert "X-Request-ID" in response.headers


def test_configuration_and_structured_logging():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, neo4j_password="test", graphrag_enabled=True)
    with pytest.raises(ValidationError):
        config(vector_top_k=51)
    record = logging.LogRecord("test", logging.INFO, "", 0, "graphrag_retrieved", (), None)
    record.vector_results = 3
    record.graph_paths = 1
    record.question = "private text"
    output = json.loads(JsonFormatter().format(record))
    assert output["vector_results"] == 3 and output["graph_paths"] == 1
    assert "private" not in json.dumps(output)


def test_duplicate_paths_preserve_complementary_document_support():
    vector, graph, chunks = evidence()
    from kg_assistant.models.graph_retrieval import RelationshipEvidence

    duplicate = graph.paths[0].model_copy(deep=True)
    other = chunks[0].model_copy(update={"document_id": "another-doc", "chunk_id": "another-chunk"})
    duplicate.edges[0].evidence = [
        RelationshipEvidence(
            document_id=other.document_id, chunk_id=other.chunk_id, evidence_quote=other.text
        )
    ]
    graph.paths.append(duplicate)
    context = ContextBuilder(config()).build(vector, graph, chunks + [other])
    assert len(context.graph_evidence) == 1
    assert len(context.text_evidence) == 4
    assert len(context.graph_evidence[0].edges[0].source_citations) == 2


@pytest.mark.parametrize("unknown", ["S99", "G99"])
def test_insufficient_response_discards_all_untrusted_content_and_citations(unknown):
    context = FusedContext()
    result = validate_answer(
        GroundedAnswer(
            answer=f"An invented founder [{unknown}].",
            citations=[unknown],
            insufficient_evidence=True,
        ),
        context,
    )
    assert result.answer == INSUFFICIENT_ANSWER
    assert result.citations == [] and result.insufficient_evidence
    with pytest.raises(ExtractionError):
        validate_answer(
            GroundedAnswer(
                answer=f"An invented founder [{unknown}].",
                citations=[unknown],
                insufficient_evidence=False,
            ),
            context,
        )


async def test_citation_retry_receives_feedback_without_relaxing_validation():
    vector, graph, chunks = evidence()
    context = ContextBuilder(config()).build(vector, graph, chunks)

    class Provider:
        def __init__(self):
            self.feedback = []

        async def generate(self, question, context):
            return GroundedAnswer(
                answer="Unsupported citation [S99].", citations=["S99"], insufficient_evidence=False
            )

        async def generate_with_feedback(self, question, context, error_code):
            self.feedback.append(error_code)
            return GroundedAnswer(
                answer="Missing founder.", citations=[], insufficient_evidence=True
            )

    provider = Provider()
    result = await AnswerGenerationService(config(), provider).generate("Who founded it?", context)
    assert provider.feedback == ["answer_invalid_citation"]
    assert result.answer == INSUFFICIENT_ANSWER and result.citations == []
