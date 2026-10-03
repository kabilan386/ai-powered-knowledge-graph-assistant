from typing import Annotated

from fastapi import APIRouter, Depends, Response

from kg_assistant.api.dependencies import get_neo4j
from kg_assistant.db.neo4j import Neo4jConnectionManager
from kg_assistant.models.health import HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=HealthResponse)
async def live() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/ready", response_model=HealthResponse, responses={503: {"model": HealthResponse}})
async def ready(
    response: Response,
    connection: Annotated[Neo4jConnectionManager, Depends(get_neo4j)],
) -> HealthResponse:
    if not await connection.healthy():
        response.status_code = 503
        return HealthResponse(status="unavailable", neo4j="down")
    return HealthResponse(status="ok", neo4j="up")
