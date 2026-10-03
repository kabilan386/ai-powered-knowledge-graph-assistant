from kg_assistant.db.repositories.graph import GraphVisualizationRepository
from kg_assistant.models.graph import GraphResponse


class GraphVisualizationService:
    def __init__(self, repository: GraphVisualizationRepository) -> None:
        self.repository = repository

    async def snapshot(self, node_limit: int, edge_limit: int) -> GraphResponse:
        return await self.repository.snapshot(node_limit, edge_limit)
