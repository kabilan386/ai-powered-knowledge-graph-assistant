from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from kg_assistant.models.embeddings import EmbeddingSummary
from kg_assistant.models.extraction import ExtractionSummary

FileType = Literal["pdf", "docx", "txt"]


class ExtractedPage(BaseModel):
    text: str
    page_number: int | None = Field(default=None, ge=1)


class Document(BaseModel):
    id: str
    filename: str
    file_type: FileType
    created_at: datetime
    extraction_status: Literal[
        "disabled", "pending", "processing", "completed", "partial", "failed"
    ] = "disabled"


class Chunk(BaseModel):
    id: str
    document_id: str
    text: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)
    page_number: int | None = Field(default=None, ge=1)


class UploadResponse(BaseModel):
    embeddings: EmbeddingSummary = Field(default_factory=EmbeddingSummary)
    document: Document
    chunk_count: int = Field(ge=1)
    extraction: ExtractionSummary = Field(
        default_factory=lambda: ExtractionSummary(status="disabled")
    )
