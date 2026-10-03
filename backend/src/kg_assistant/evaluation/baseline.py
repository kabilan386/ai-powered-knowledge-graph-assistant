import asyncio
from time import perf_counter

from kg_assistant.core.config import Settings
from kg_assistant.models.graph_retrieval import GraphSearchResponse
from kg_assistant.models.graphrag import AskRequest, AskResponse, GroundedAnswer, RetrievalMetadata
from kg_assistant.models.retrieval import VectorSearchRequest
from kg_assistant.services.answers import INSUFFICIENT_ANSWER, map_sources


class VectorRAGBaseline:
    """Evaluation only: shared answer policy, exclusively vector text evidence."""

    def __init__(self, settings: Settings, vector, repository, builder, generator) -> None:
        self.settings = settings
        self.vector = vector
        self.repository = repository
        self.builder = builder
        self.generator = generator

    async def ask(self, request: AskRequest) -> AskResponse:
        started = perf_counter()
        async with asyncio.timeout(self.settings.graphrag_request_timeout):
            vector = await self.vector.search(
                VectorSearchRequest(query=request.question, top_k=self.settings.vector_top_k)
            )
            # This is an empty input contract, never a graph search/provider/database read.
            empty_graph = GraphSearchResponse(
                query=request.question, anchors=[], paths=[], status="no_paths"
            )
            references = [(row.document_id, row.chunk_id) for row in vector.results]
            chunks = await self.repository.load_chunks(references)
            context = self.builder.build(vector, empty_graph, chunks)
            if context.graph_evidence:
                raise RuntimeError("Vector baseline must not contain graph evidence")
            if context.text_evidence:
                result = await self.generator.generate(request.question, context)
            else:
                result = GroundedAnswer(
                    answer=INSUFFICIENT_ANSWER, citations=[], insufficient_evidence=True
                )
            return AskResponse(
                question=request.question,
                answer=result.answer,
                citations=result.citations,
                sources=map_sources(result.citations, context),
                insufficient_evidence=result.insufficient_evidence,
                retrieval=RetrievalMetadata(
                    vector_results=len(vector.results),
                    graph_paths=0,
                    context_chunks=len(context.text_evidence),
                    context_graph_paths=0,
                    context_characters=len(context.payload()),
                    vector_top_k=self.settings.vector_top_k,
                    graph_max_hops=0,
                    graph_status="not_used",
                    graph_truncated=False,
                    context_truncated=context.truncated,
                    duration_ms=(perf_counter() - started) * 1000,
                ),
            )
