from kg_assistant.core.config import Settings
from kg_assistant.models.graph_retrieval import (
    GraphEdge,
    GraphEntity,
    GraphPath,
    GraphSearchResponse,
    RelationshipEvidence,
)
from kg_assistant.models.graphrag import SourceChunk
from kg_assistant.models.retrieval import VectorSearchResponse, VectorSearchResult

QUESTION = "Which cloud service hosts the technology used by the service managed by Platform Team?"
TEXTS = [
    "Platform Team manages Payment Service.",
    "Payment Service uses Redis for caching.",
    "Redis is hosted on AWS ElastiCache.",
]


def config(**overrides):
    return Settings(
        _env_file=None,
        neo4j_password="test-only",
        embedding_enabled=True,
        embedding_model="mock-embedding",
        embedding_dimensions=3,
        graph_retrieval_enabled=True,
        graphrag_enabled=True,
        openai_api_key="mock-only",
        llm_model="mock-structured",
        llm_retry_backoff=0,
        **overrides,
    )


def evidence():
    chunks = [
        SourceChunk(
            document_id="d",
            chunk_id=f"c{i}",
            filename="technical.pdf",
            page_number=i + 1,
            chunk_index=i,
            text=text,
        )
        for i, text in enumerate(TEXTS)
    ]
    nodes = [
        GraphEntity(id=f"e{i}", name=name, type=kind)
        for i, (name, kind) in enumerate(
            [
                ("Platform Team", "ORGANIZATION"),
                ("Payment Service", "SERVICE"),
                ("Redis", "TECHNOLOGY"),
                ("AWS ElastiCache", "CLOUD_SERVICE"),
            ]
        )
    ]
    edges = [
        GraphEdge(
            type=kind,
            source_id=nodes[i].id,
            target_id=nodes[i + 1].id,
            evidence=[
                RelationshipEvidence(
                    chunk_id=chunks[i].chunk_id, document_id="d", evidence_quote=chunks[i].text
                )
            ],
        )
        for i, kind in enumerate(["MANAGES", "USES", "HOSTED_ON"])
    ]
    path = GraphPath(
        hop_count=3, nodes=nodes, edges=edges, relationships=[e.type for e in edges], score=93
    )
    graph = GraphSearchResponse(query=QUESTION, anchors=nodes[:1], paths=[path], status="ok")
    vector = VectorSearchResponse(
        query=QUESTION,
        results=[
            VectorSearchResult(**chunk.model_dump(exclude={"text_truncated"}), score=score)
            for chunk, score in zip(chunks, [0.8, 0.95, 0.7], strict=True)
        ],
    )
    return vector, graph, chunks
