from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExtractedEntity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    key: str = Field(min_length=1, max_length=64, description="Unique local entity reference")
    name: str = Field(min_length=1, max_length=255)
    type: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=1000)
    evidence_quote: str = Field(
        min_length=1, description="Verbatim text containing the entity name"
    )


class ExtractedRelationship(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source: str = Field(min_length=1, description="Source entity key")
    target: str = Field(min_length=1, description="Target entity key")
    type: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=1000)
    evidence_quote: str = Field(
        min_length=1, description="Verbatim text explicitly supporting the directed relationship"
    )


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    entities: list[ExtractedEntity] = Field(max_length=100)
    relationships: list[ExtractedRelationship] = Field(max_length=200)

    @model_validator(mode="after")
    def check_references(self) -> "ExtractionResult":
        keys = [entity.key for entity in self.entities]
        if len(keys) != len(set(keys)):
            raise ValueError("Entity keys must be unique")
        if any(r.source not in keys or r.target not in keys for r in self.relationships):
            raise ValueError("Relationships must reference extracted entity keys")
        return self


class ChunkExtractionError(BaseModel):
    chunk_id: str
    code: str
    attempts: int


class ExtractionSummary(BaseModel):
    status: Literal["disabled", "pending", "processing", "completed", "partial", "failed"]
    total: int = 0
    completed: int = 0
    failed: int = 0
    errors: list[ChunkExtractionError] = Field(default_factory=list)


class NormalizedEntity(BaseModel):
    id: str
    name: str
    normalized_name: str
    type: str
    description: str | None
    evidence_quote: str


class NormalizedRelationship(BaseModel):
    source_id: str
    target_id: str
    type: str
    description: str | None
    evidence_quote: str


class NormalizedExtraction(BaseModel):
    entities: list[NormalizedEntity]
    relationships: list[NormalizedRelationship]
