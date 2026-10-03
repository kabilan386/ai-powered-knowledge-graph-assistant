from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from kg_assistant.models.graph_retrieval import GraphEntity


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=4000)


class GroundedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    answer: str = Field(
        min_length=1,
        max_length=16000,
        description="For supported answers, cite claims inline with exact markers such as [S1] "
        "or [G1]. A separate citations list alone is not sufficient.",
    )
    citations: list[str] = Field(
        max_length=100,
        description="Bare supplied IDs used inside square brackets in answer, deduplicated "
        "in first-appearance order. Every listed ID must appear inline in answer.",
    )
    insufficient_evidence: bool


class SourceChunk(BaseModel):
    document_id: str
    chunk_id: str
    filename: str
    page_number: int | None = None
    chunk_index: int
    text: str
    text_truncated: bool = False


class TextEvidence(BaseModel):
    citation: str
    document_id: str
    chunk_id: str
    filename: str
    page_number: int | None = None
    chunk_index: int
    excerpt: str
    excerpt_truncated: bool = False
    vector_score: float | None = None


class FusedEdge(BaseModel):
    type: str
    source_id: str
    target_id: str
    source_citations: list[str] = Field(default_factory=list)
    document_backed: bool = False


class GraphEvidence(BaseModel):
    citation: str
    hop_count: int
    nodes: list[GraphEntity]
    edges: list[FusedEdge]


class FusedContext(BaseModel):
    text_evidence: list[TextEvidence] = Field(default_factory=list)
    graph_evidence: list[GraphEvidence] = Field(default_factory=list)
    truncated: bool = False

    def payload(self) -> str:
        return self.model_dump_json()


class CitationSource(BaseModel):
    citation: str
    kind: Literal["document", "graph"]
    document_id: str | None = None
    chunk_id: str | None = None
    filename: str | None = None
    page_number: int | None = None
    chunk_index: int | None = None
    excerpt: str | None = None
    excerpt_truncated: bool = False
    nodes: list[GraphEntity] = Field(default_factory=list)
    edges: list[FusedEdge] = Field(default_factory=list)
    supporting_citations: list[str] = Field(default_factory=list)


class RetrievalMetadata(BaseModel):
    vector_results: int
    graph_paths: int
    context_chunks: int
    context_graph_paths: int
    context_characters: int
    vector_top_k: int
    graph_max_hops: int
    graph_status: str
    graph_truncated: bool
    context_truncated: bool
    duration_ms: float = 0


class AskResponse(BaseModel):
    question: str
    answer: str
    citations: list[str]
    sources: list[CitationSource]
    retrieval: RetrievalMetadata
    insufficient_evidence: bool
