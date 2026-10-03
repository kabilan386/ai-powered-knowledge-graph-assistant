from typing import Annotated

from fastapi import APIRouter, Depends

from kg_assistant.api.dependencies import get_embedding_ingestion
from kg_assistant.models.embeddings import BackfillRequest, BackfillResponse
from kg_assistant.services.embedding_ingestion import EmbeddingIngestionService

router = APIRouter(prefix="/api/embeddings", tags=["embeddings"])


@router.post("/backfill", response_model=BackfillResponse)
async def backfill(
    body: BackfillRequest,
    service: Annotated[EmbeddingIngestionService, Depends(get_embedding_ingestion)],
) -> BackfillResponse:
    return await service.backfill(body.document_id, body.limit)
