from typing import Literal

from pydantic import BaseModel, Field


class EmbeddingFailure(BaseModel):
    chunk_id: str
    code: str


class EmbeddingSummary(BaseModel):
    status: Literal["disabled", "pending", "completed", "partial", "failed"] = "disabled"
    total: int = Field(default=0, ge=0)
    completed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    errors: list[EmbeddingFailure] = Field(default_factory=list)


class BackfillRequest(BaseModel):
    document_id: str | None = Field(default=None, min_length=1, max_length=128)
    limit: int = Field(default=100, ge=1, le=1000, strict=True)


class BackfillResponse(BaseModel):
    processed: int = 0
    updated: int = 0
    skipped: int = 0
    remaining: int = 0
    errors: list[EmbeddingFailure] = Field(default_factory=list)
