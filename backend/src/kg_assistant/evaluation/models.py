from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kg_assistant.models.graph_retrieval import GraphSearchResponse
from kg_assistant.models.graphrag import AskResponse, FusedContext
from kg_assistant.models.retrieval import VectorSearchResponse
from kg_assistant.providers.usage import TokenUsage

Category = Literal["factual", "semantic", "relationship", "multi_hop", "insufficient_evidence"]
Mode = Literal["vector_rag", "graphrag"]


class ExpectedSource(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    document_id: str | None = Field(default=None, min_length=1)
    chunk_id: str | None = Field(default=None, min_length=1)
    filename: str | None = Field(default=None, min_length=1)
    quote: str | None = Field(default=None, min_length=1)
    page_number: int | None = Field(default=None, ge=1)
    chunk_index: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def selector(self):
        if not ((self.document_id and self.chunk_id) or (self.filename and self.quote)):
            raise ValueError("Supply document_id/chunk_id or filename/quote as a source selector")
        return self


class ExpectedEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    type: str = Field(min_length=1)


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=4000)
    question_type: Category
    expected_answer: str | None = Field(default=None, min_length=1)
    expected_entities: list[str] = Field(default_factory=list, max_length=100)
    expected_anchors: list[str] = Field(default_factory=list, max_length=10)
    expected_sources: list[ExpectedSource] = Field(default_factory=list, max_length=50)
    sources_complete: bool = False
    expected_path: list[ExpectedEdge] = Field(default_factory=list, max_length=5)
    expected_insufficient_evidence: bool | None = None

    @model_validator(mode="after")
    def consistent(self):
        if (
            self.question_type == "insufficient_evidence"
            and self.expected_insufficient_evidence is not True
        ):
            raise ValueError("Insufficient-evidence cases must explicitly expect insufficiency")
        if self.expected_insufficient_evidence is True and self.expected_answer is not None:
            raise ValueError("Do not annotate a supported answer for an insufficient-evidence case")
        if any(not value.strip() for value in self.expected_entities + self.expected_anchors):
            raise ValueError("Expected entity names must be nonempty")
        for previous, current in zip(self.expected_path, self.expected_path[1:], strict=False):
            if previous.target.casefold() != current.source.casefold():
                raise ValueError("Expected path must be a connected directed chain")
        return self


class EvaluationDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    name: str = Field(min_length=1)
    description: str
    cases: list[EvaluationCase] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique_ids(self):
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("Question IDs must be unique")
        return self


class ResolvedGroundTruth(BaseModel):
    references: list[tuple[str, str]] = Field(default_factory=list)
    status: Literal["resolved", "unannotated", "missing", "ambiguous", "error"]


class ModeResult(BaseModel):
    status: Literal["ok", "error"]
    response: AskResponse | None = None
    vector: VectorSearchResponse | None = None
    graph: GraphSearchResponse | None = None
    context: FusedContext | None = None
    latency_ms: float = Field(ge=0)
    vector_retrieval_ms: float | None = None
    graph_retrieval_ms: float | None = None
    token_usage: dict[str, TokenUsage | None] = Field(default_factory=dict)
    error_code: str | None = None
    metrics: dict[str, float | bool | None] = Field(default_factory=dict)
