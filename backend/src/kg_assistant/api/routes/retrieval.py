from typing import Annotated

from fastapi import APIRouter, Depends

from kg_assistant.api.dependencies import get_graph_retrieval, get_vector_retrieval
from kg_assistant.models.graph_retrieval import GraphSearchRequest, GraphSearchResponse
from kg_assistant.models.retrieval import VectorSearchRequest, VectorSearchResponse
from kg_assistant.retrieval.graph import GraphRetrievalService
from kg_assistant.retrieval.vector import VectorRetrievalService

router = APIRouter(prefix="/api/retrieval", tags=["retrieval"])


@router.post("/vector-search", response_model=VectorSearchResponse)
async def vector_search(
    body: VectorSearchRequest,
    service: Annotated[VectorRetrievalService, Depends(get_vector_retrieval)],
) -> VectorSearchResponse:
    return await service.search(body)


@router.post("/graph-search", response_model=GraphSearchResponse)
async def graph_search(
    body: GraphSearchRequest,
    service: Annotated[GraphRetrievalService, Depends(get_graph_retrieval)],
) -> GraphSearchResponse:
    return await service.search(body)
