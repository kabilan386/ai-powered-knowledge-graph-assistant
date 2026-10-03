from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class QueryEntity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=255)
    type: str | None = Field(default=None, max_length=64)


class QueryExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    entities: list[QueryEntity] = Field(max_length=10)
    relationship_types: list[str] = Field(default_factory=list, max_length=5)
    target_type: str | None = None
    direction: Literal["outgoing", "incoming", "both"] = "both"


class GraphSearchRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    query: str = Field(min_length=1, max_length=4000)
    max_hops: int | None = Field(default=None, ge=1, le=5, strict=True)


class GraphEntity(BaseModel):
    id: str
    name: str
    type: str


class RelationshipEvidence(BaseModel):
    relationship_id: str | None = None
    chunk_id: str | None = None
    document_id: str | None = None
    filename: str | None = None
    page_number: int | None = None
    chunk_index: int | None = None
    evidence_quote: str | None = None


class GraphEdge(BaseModel):
    type: str
    source_id: str
    target_id: str
    evidence: list[RelationshipEvidence] = Field(default_factory=list)
    evidence_truncated: bool = False


class GraphPath(BaseModel):
    hop_count: int = Field(ge=1, le=5)
    nodes: list[GraphEntity]
    relationships: list[str]
    edges: list[GraphEdge]
    score: float = 0

    @model_validator(mode="after")
    def check_path(self) -> "GraphPath":
        if len(self.nodes) != self.hop_count + 1 or len(self.edges) != self.hop_count:
            raise ValueError("Path lengths are inconsistent")
        if self.relationships != [edge.type for edge in self.edges]:
            raise ValueError("Relationship types do not match edges")
        if len({node.id for node in self.nodes}) != len(self.nodes):
            raise ValueError("Paths must not repeat nodes")
        for index, edge in enumerate(self.edges):
            if {edge.source_id, edge.target_id} != {self.nodes[index].id, self.nodes[index + 1].id}:
                raise ValueError("Edge endpoints do not match path nodes")
        return self


class GraphSearchResponse(BaseModel):
    query: str
    anchors: list[GraphEntity]
    unresolved_entities: list[QueryEntity] = Field(default_factory=list)
    paths: list[GraphPath]
    status: Literal["ok", "no_anchors", "unresolved_anchors", "no_paths"]
    truncated: bool = False
