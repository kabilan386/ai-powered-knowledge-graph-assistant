from typing import Annotated

from fastapi import APIRouter, Depends, Request

from kg_assistant.api.dependencies import get_graphrag
from kg_assistant.models.graphrag import AskRequest, AskResponse
from kg_assistant.services.graphrag import GraphRAGService

router = APIRouter(prefix="/api/graphrag", tags=["graphrag"])


@router.post("/ask", response_model=AskResponse)
async def ask(
    body: AskRequest,
    request: Request,
    service: Annotated[GraphRAGService, Depends(get_graphrag)],
) -> AskResponse:
    return await service.ask(body, request.state.request_id)
