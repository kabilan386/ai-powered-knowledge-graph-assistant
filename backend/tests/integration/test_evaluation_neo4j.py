from pathlib import Path
from unittest.mock import AsyncMock

import httpx
from graphrag_fixtures import config
from test_neo4j_upload import integration_settings, pytestmark  # noqa: F401

from kg_assistant.api.dependencies import (
    get_embedding_provider,
    get_extraction_provider,
)
from kg_assistant.db.repositories.context import ContextRepository
from kg_assistant.db.repositories.vectors import VectorRepository
from kg_assistant.evaluation.fixtures import (
    FACTS,
    FixtureAnswerProvider,
    FixtureQueryProvider,
    FixtureStore,
)
from kg_assistant.evaluation.models import EvaluationDataset
from kg_assistant.evaluation.observations import ObservedQueryProvider
from kg_assistant.evaluation.repository import EvaluationRepository
from kg_assistant.evaluation.runner import EvaluationRuntime, evaluate_dataset
from kg_assistant.main import create_app
from kg_assistant.models.extraction import ExtractedEntity, ExtractedRelationship, ExtractionResult
from kg_assistant.retrieval.graph import GraphRetrievalService
from kg_assistant.retrieval.query_entities import QueryEntityExtractionService
from kg_assistant.retrieval.vector import VectorRetrievalService
from kg_assistant.services.embeddings import EmbeddingService


def extraction_for(text):
    _, quote, source, source_type, kind, target, target_type = next(
        fact for fact in FACTS if fact[1] in text
    )
    return ExtractionResult(
        entities=[
            ExtractedEntity(key="s", name=source, type=source_type, evidence_quote=source),
            ExtractedEntity(key="t", name=target, type=target_type, evidence_quote=target),
        ],
        relationships=[
            ExtractedRelationship(
                source="s",
                target="t",
                type=kind,
                evidence_quote=quote,
            )
        ],
    )


async def test_real_evaluation_upload_to_answer():
    settings = config()
    neo = integration_settings()
    settings.neo4j_uri = neo.neo4j_uri
    settings.neo4j_password = neo.neo4j_password
    settings.neo4j_database = neo.neo4j_database
    settings.llm_extraction_enabled = True
    app = create_app(settings)
    embeddings, extraction = AsyncMock(), AsyncMock()
    embeddings.embed_batch.side_effect = lambda texts: [[1.0, 0.1, 0.1] for _ in texts]
    extraction.extract.side_effect = extraction_for
    app.dependency_overrides[get_embedding_provider] = lambda: embeddings
    app.dependency_overrides[get_extraction_provider] = lambda: extraction
    documents = []
    async with app.router.lifespan_context(app):
        connection = app.state.neo4j
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            try:
                for filename, text, *_ in FACTS:
                    upload = await client.post(
                        "/api/documents/upload",
                        files={
                            "file": (filename, text.encode(), "text/plain"),
                        },
                    )
                    assert upload.status_code == 201, upload.text
                    body = upload.json()
                    documents.append(body["document"]["id"])
                    assert body["chunk_count"] == 1
                    assert body["embeddings"]["status"] == "completed"
                    assert body["extraction"]["status"] == "completed"
                vector = VectorRetrievalService(
                    settings,
                    VectorRepository(connection, settings),
                    EmbeddingService(embeddings, settings),
                )
                graph = GraphRetrievalService(
                    connection=connection,
                    settings=settings,
                    extractor=QueryEntityExtractionService(
                        settings,
                        ObservedQueryProvider(
                            FixtureQueryProvider(FixtureStore()),
                        ),
                    ),
                )
                runtime = EvaluationRuntime(
                    settings,
                    vector,
                    graph,
                    ContextRepository(connection, settings),
                    FixtureAnswerProvider(),
                    EvaluationRepository(connection, settings),
                )
                dataset_path = Path(__file__).parents[3] / "evaluation/dataset.json"
                dataset = EvaluationDataset.model_validate_json(dataset_path.read_bytes())
                records = await evaluate_dataset(runtime, dataset)
                assert all(
                    row[mode]["status"] == "ok"
                    for row in records
                    for mode in ["vector_rag", "graphrag"]
                )
                three_hop = next(row for row in records if row["id"] == "Q005")
                assert three_hop["ground_truth"]["status"] == "resolved"
                assert three_hop["graphrag"]["metrics"]["expected_path_found"] is True
                assert three_hop["graphrag"]["metrics"]["normalized_answer_match"] is True
                assert three_hop["graphrag"]["metrics"]["citation_validity"] is True
                assert three_hop["graphrag"]["graph_retrieval_ms"] >= 0
                assert three_hop["vector_rag"]["graph_paths"] == []
                assert three_hop["vector_rag"]["graph_retrieval_ms"] is None
                for source in three_hop["graphrag"]["response"]["sources"]:
                    if source["kind"] == "document":
                        assert source["document_id"] in documents
                insufficient = next(row for row in records if row["id"] == "Q006")
                assert insufficient["graphrag"]["metrics"]["insufficient_evidence_correct"] is True
            finally:
                async with connection.driver.session(database=settings.neo4j_database) as session:
                    await (
                        await session.run(
                            "MATCH ()-[r]->() WHERE r.source_document_id IN $ids DELETE r",
                            ids=documents,
                        )
                    ).consume()
                    await (
                        await session.run(
                            "MATCH (d:Document) WHERE d.id IN $ids "
                            "OPTIONAL MATCH (d)-[:HAS_CHUNK]->(c:Chunk) DETACH DELETE d,c",
                            ids=documents,
                        )
                    ).consume()
