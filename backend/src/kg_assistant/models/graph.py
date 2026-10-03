from pydantic import BaseModel


class GraphNode(BaseModel):
    id: str
    label: str
    type: str
    description: str | None = None


class VisualizationEdge(BaseModel):
    id: str
    source: str
    target: str
    type: str


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[VisualizationEdge]
    truncated: bool = False
