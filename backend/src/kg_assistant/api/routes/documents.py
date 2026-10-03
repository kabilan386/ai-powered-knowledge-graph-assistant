from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from kg_assistant.api.dependencies import (
    get_document_service,
    get_graph_ingestion,
)
from kg_assistant.models.documents import UploadResponse
from kg_assistant.models.extraction import ExtractionSummary
from kg_assistant.services.documents import DocumentService
from kg_assistant.services.knowledge_graph import GraphIngestionService

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("/upload", status_code=201, response_model=UploadResponse)
async def upload_document(
    file: Annotated[UploadFile, File(description="PDF, DOCX, or UTF-8 TXT document")],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> UploadResponse:
    return await service.upload(file)


@router.get("/{document_id}/extraction", response_model=ExtractionSummary)
async def extraction_status(
    document_id: str,
    service: Annotated[GraphIngestionService, Depends(get_graph_ingestion)],
) -> ExtractionSummary:
    return await service.status(document_id)


@router.post("/{document_id}/extract", response_model=ExtractionSummary)
async def retry_extraction(
    document_id: str,
    service: Annotated[GraphIngestionService, Depends(get_graph_ingestion)],
) -> ExtractionSummary:
    return await service.ingest(document_id)
