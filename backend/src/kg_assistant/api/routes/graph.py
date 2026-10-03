from typing import Annotated

from fastapi import APIRouter, Depends, Query

from kg_assistant.api.dependencies import get_graph_visualization
from kg_assistant.models.graph import GraphResponse
from kg_assistant.services.graph import GraphVisualizationService

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.get("", response_model=GraphResponse)
async def graph_snapshot(
    service: Annotated[GraphVisualizationService, Depends(get_graph_visualization)],
    node_limit: Annotated[int, Query(ge=1, le=200)] = 100,
    edge_limit: Annotated[int, Query(ge=1, le=400)] = 200,
) -> GraphResponse:
    return await service.snapshot(node_limit, edge_limit)
