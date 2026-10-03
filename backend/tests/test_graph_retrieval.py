from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from neo4j import READ_ACCESS
from pydantic import ValidationError

from kg_assistant.api.dependencies import get_graph_retrieval
from kg_assistant.core.config import Settings
from kg_assistant.core.exceptions import IngestionError
from kg_assistant.db.repositories.graph_retrieval import NEIGHBORS, GraphRetrievalRepository
from kg_assistant.main import create_app
from kg_assistant.models.graph_retrieval import (
    GraphEdge,
    GraphEntity,
    GraphPath,
    GraphSearchRequest,
    GraphSearchResponse,
    QueryEntity,
    QueryExtraction,
    RelationshipEvidence,
)
from kg_assistant.providers.base import ExtractionError
from kg_assistant.providers.query_entities import OpenAIQueryEntityProvider
from kg_assistant.retrieval.graph import GraphRetrievalService, GraphTraversal
from kg_assistant.retrieval.query_entities import QueryEntityExtractionService


def graph_settings(**overrides):
    return Settings(
        _env_file=None,
        neo4j_password="test-only",
        graph_retrieval_enabled=True,
        openai_api_key="mock-only",
        llm_model="mock-structured",
        llm_retry_backoff=0,
        **overrides,
    )


NODES = [
    GraphEntity(id=str(i), name=name, type=kind)
    for i, (name, kind) in enumerate(
        [
            ("Platform Team", "ORGANIZATION"),
            ("Payment Service", "SERVICE"),
            ("Redis", "TECHNOLOGY"),
            ("AWS ElastiCache", "CLOUD_SERVICE"),
            ("PostgreSQL", "DATABASE"),
        ]
    )
]
QUESTIONS = [
    ("What does Payment Service use?", 1, ["USES"], None),
    ("What service is managed by Platform Team?", 0, ["MANAGES"], "SERVICE"),
    (
        "What technology is used by the service managed by Platform Team?",
        0,
        ["MANAGES", "USES"],
        "TECHNOLOGY",
    ),
    (
        "Which cloud service hosts the technology used by the service managed by Platform Team?",
        0,
        ["MANAGES", "USES", "HOSTED_ON"],
        "CLOUD_SERVICE",
    ),
]


def intent_for(index):
    _, anchor, kinds, target = QUESTIONS[index]
    return QueryExtraction(
        entities=[QueryEntity(name=NODES[anchor].name, type=NODES[anchor].type)],
        relationship_types=kinds,
        target_type=target,
        direction="outgoing",
    )


def fake_repository():
    repo = AsyncMock()
    repo.resolve.side_effect = lambda entity: (
        [n for n in NODES if n.name.casefold() == entity.name.casefold()],
        False,
    )
    adjacency = {
        "0": [(NODES[1], GraphEdge(type="MANAGES", source_id="0", target_id="1"))],
        "1": [
            (NODES[2], GraphEdge(type="USES", source_id="1", target_id="2")),
            (NODES[4], GraphEdge(type="DEPENDS_ON", source_id="1", target_id="4")),
        ],
        "2": [
            (NODES[3], GraphEdge(type="HOSTED_ON", source_id="2", target_id="3")),
            (NODES[0], GraphEdge(type="RELATED_TO", source_id="2", target_id="0")),
        ],
    }
    repo.neighbors.side_effect = lambda id, direction: (adjacency.get(id, []), False)
    repo.evidence.side_effect = lambda edge: edge.model_copy(
        update={
            "evidence": [
                RelationshipEvidence(
                    chunk_id="c",
                    document_id="d",
                    filename="technical.pdf",
                    page_number=3,
                    chunk_index=7,
                )
            ]
        }
    )
    return repo


@pytest.mark.parametrize("index", range(4))
async def test_one_two_three_hops_rank_and_serialize(index):
    query, anchor, kinds, _ = QUESTIONS[index]
    result = await GraphTraversal(graph_settings(), fake_repository()).retrieve(
        query, intent_for(index), 3
    )
    assert result.status == "ok"
    assert result.paths[0].relationships == kinds
    assert result.paths[0].hop_count == len(kinds)
    assert result.paths[0].nodes[0] == NODES[anchor]
    assert result.paths[0].edges[0].evidence[0].filename == "technical.pdf"
    assert GraphSearchResponse.model_validate_json(result.model_dump_json()) == result
    assert all(len({n.id for n in path.nodes}) == len(path.nodes) for path in result.paths)


async def test_depth_candidate_budget_exclusions_and_deduplication():
    repo = fake_repository()
    edge = GraphEdge(type="MANAGES", source_id="0", target_id="1")
    repo.neighbors.side_effect = None
    repo.neighbors.return_value = (
        [
            (NODES[1], edge),
            (NODES[1], edge),
            (NODES[2], GraphEdge(type="MENTIONS", source_id="0", target_id="2")),
        ],
        False,
    )
    result = await GraphTraversal(graph_settings(), repo).retrieve("q", intent_for(1), 1)
    assert len(result.paths) == 1
    assert result.paths[0].relationships == ["MANAGES"]
    limited = await GraphTraversal(
        graph_settings(graph_max_candidates=1), fake_repository()
    ).retrieve("q", intent_for(3), 3)
    assert len(limited.paths) == 1 and limited.truncated
    result = await GraphTraversal(graph_settings(graph_max_results=1), fake_repository()).retrieve(
        "q", intent_for(3), 3
    )
    assert result.truncated and result.paths[0].hop_count == 3


async def test_unresolved_no_anchors_and_no_paths():
    repo = fake_repository()
    result = await GraphTraversal(graph_settings(), repo).retrieve(
        "q", QueryExtraction(entities=[]), 3
    )
    assert result.status == "no_anchors" and not result.paths
    result = await GraphTraversal(graph_settings(), repo).retrieve(
        "q", QueryExtraction(entities=[QueryEntity(name="missing")]), 3
    )
    assert result.status == "unresolved_anchors" and result.unresolved_entities[0].name == "missing"
    repo.neighbors.side_effect = None
    repo.neighbors.return_value = ([], False)
    result = await GraphTraversal(graph_settings(), repo).retrieve("q", intent_for(1), 3)
    assert result.status == "no_paths" and result.anchors


@pytest.mark.parametrize(
    "body",
    [
        {"query": ""},
        {"query": " \n "},
        {"query": "q", "max_hops": 0},
        {"query": "q", "max_hops": 6},
        {"query": "q", "max_hops": True},
        {"query": "q", "max_hops": "3"},
        {"query": "q", "cypher": "MATCH (n) RETURN n"},
    ],
)
def test_request_validation(body):
    with pytest.raises(ValidationError):
        GraphSearchRequest(**body)


async def test_query_extraction_validation_normalization_and_retry():
    provider = AsyncMock()
    provider.extract.side_effect = [
        ExtractionError("invalid"),
        QueryExtraction(
            entities=[
                QueryEntity(name="Platform Team", type="ORGANIZATION"),
                QueryEntity(name="PLATFORM TEAM", type="ORGANIZATION"),
            ]
        ),
    ]
    result = await QueryEntityExtractionService(graph_settings(), provider).extract(QUESTIONS[1][0])
    assert len(result.entities) == 1 and provider.extract.await_count == 2


@pytest.mark.parametrize(
    "result",
    [
        "free-form response",
        QueryExtraction(entities=[QueryEntity(name="Invented")]),
        QueryExtraction(entities=[QueryEntity(name="Platform Team", type="INVALID")]),
        QueryExtraction(entities=[], relationship_types=["MENTIONS"]),
        QueryExtraction(entities=[], target_type="INVALID"),
    ],
)
def test_invalid_query_extraction(result):
    with pytest.raises(ExtractionError):
        QueryEntityExtractionService(graph_settings(), AsyncMock()).validate(
            result, QUESTIONS[1][0]
        )


async def test_repository_resolution_and_provenance():
    repo = GraphRetrievalRepository(AsyncMock(), graph_settings())
    repo._read = AsyncMock(return_value=[NODES[0].model_dump()])
    resolved, truncated = await repo.resolve(
        QueryEntity(name="  PLATFORM  TEAM ", type="ORGANIZATION")
    )
    assert resolved == [NODES[0]] and not truncated
    assert repo._read.call_args.kwargs["name"] == "platform team"
    repo._read.return_value = [
        {
            "relationship_id": "r",
            "chunk_id": "c",
            "document_id": "d",
            "filename": "technical.pdf",
            "page_number": 3,
            "chunk_index": 7,
            "evidence_quote": "Payment Service uses Redis.",
        }
    ]
    edge = await repo.evidence(GraphEdge(type="USES", source_id="1", target_id="2"))
    assert edge.evidence[0].page_number == 3 and edge.evidence[0].chunk_index == 7
    repo._read.return_value = [{key: None for key in edge.evidence[0].model_dump()}]
    assert (await repo.evidence(edge)).evidence == []
    assert "HAS_CHUNK" in NEIGHBORS and "MENTIONS" in NEIGHBORS
    assert "[*]" not in NEIGHBORS


async def test_structured_provider_and_lifecycle():
    client = AsyncMock()
    client.responses.parse.return_value = SimpleNamespace(
        status="completed", output_parsed=intent_for(3)
    )
    with patch("kg_assistant.providers.query_entities.AsyncOpenAI", return_value=client):
        adapter = OpenAIQueryEntityProvider(graph_settings())
        assert await adapter.extract(QUESTIONS[3][0]) == intent_for(3)
        assert client.responses.parse.call_args.kwargs["text_format"] is QueryExtraction
        assert client.responses.parse.call_args.kwargs["store"] is False
        client.responses.parse.return_value = SimpleNamespace(
            status="incomplete", output_parsed=None
        )
        with pytest.raises(ExtractionError):
            await adapter.extract("q")
        await adapter.close()
        client.close.assert_awaited_once()


async def test_service_read_only_limits_errors_and_api(settings):
    connection = MagicMock()
    session = AsyncMock()
    connection.driver.session.return_value.__aenter__.return_value = session
    session.execute_read.return_value = GraphSearchResponse(
        query="q", anchors=[], paths=[], status="no_anchors"
    )
    extractor = AsyncMock()
    extractor.extract.return_value = QueryExtraction(entities=[])
    service = GraphRetrievalService(graph_settings(), connection, extractor)
    assert (await service.search(GraphSearchRequest(query="q"))).status == "no_anchors"
    assert connection.driver.session.call_args.kwargs["default_access_mode"] == READ_ACCESS
    with pytest.raises(IngestionError) as error:
        await service.search(GraphSearchRequest(query="q", max_hops=4))
    assert error.value.status_code == 422
    extractor.extract.side_effect = ExtractionError("query_extraction_invalid_response")
    with pytest.raises(IngestionError) as error:
        await service.search(GraphSearchRequest(query="q"))
    assert error.value.status_code == 502
    app = create_app(settings)
    app.dependency_overrides[get_graph_retrieval] = lambda: service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (
            await client.post("/api/retrieval/graph-search", json={"query": " "})
        ).status_code == 422
        assert (
            await client.post("/api/retrieval/graph-search", json={"query": "q"})
        ).status_code == 502


def test_structured_path_rejects_cycle():
    with pytest.raises(ValidationError):
        GraphPath(
            hop_count=2,
            nodes=[NODES[0], NODES[1], NODES[0]],
            relationships=["MANAGES", "MANAGES"],
            edges=[GraphEdge(type="MANAGES", source_id="0", target_id="1")] * 2,
        )


@pytest.mark.parametrize("limit", [0, 6])
def test_configuration_hop_limit(limit):
    with pytest.raises(ValidationError):
        graph_settings(graph_max_hops=limit)


async def test_anchor_ambiguity_fanout_and_evidence_limits():
    config = graph_settings(graph_max_anchors=1, graph_fan_out=1, graph_max_evidence=1)
    repo = GraphRetrievalRepository(AsyncMock(), config)
    repo._read = AsyncMock(return_value=[NODES[0].model_dump(), NODES[1].model_dump()])
    entities, limited = await repo.resolve(QueryEntity(name="Platform Team"))
    assert len(entities) == 1 and limited
    assert repo._read.call_args.kwargs["type"] is None
    assert repo._read.call_args.kwargs["limit"] == 2
    repo._read.return_value = [
        {
            **NODES[index].model_dump(),
            "relationship_type": "USES",
            "source_id": "0",
            "target_id": str(index),
        }
        for index in (1, 2)
    ]
    neighbors, limited = await repo.neighbors("0", "both")
    assert len(neighbors) == 1 and limited
    assert repo._read.call_args.kwargs["limit"] == 2
    repo._read.return_value = [{"chunk_id": "c1"}, {"chunk_id": "c2"}]
    edge = await repo.evidence(GraphEdge(type="USES", source_id="0", target_id="1"))
    assert edge.evidence_truncated and len(edge.evidence) == 1


async def test_disabled_graph_retrieval_and_timeout(settings):
    with pytest.raises(IngestionError) as failure:
        await GraphRetrievalService(settings, MagicMock(), None).search(
            GraphSearchRequest(query="q")
        )
    assert failure.value.code == "graph_retrieval_disabled"
    connection = MagicMock()
    session = AsyncMock()
    connection.driver.session.return_value.__aenter__.return_value = session
    session.execute_read.side_effect = TimeoutError("private database details")
    extractor = AsyncMock()
    extractor.extract.return_value = QueryExtraction(entities=[])
    with pytest.raises(IngestionError) as failure:
        await GraphRetrievalService(graph_settings(), connection, extractor).search(
            GraphSearchRequest(query="q")
        )
    assert failure.value.status_code == 503 and "private" not in failure.value.message
