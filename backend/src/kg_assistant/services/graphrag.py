import asyncio
import logging
from time import perf_counter

from kg_assistant.core.config import Settings
from kg_assistant.core.exceptions import IngestionError
from kg_assistant.db.repositories.context import ContextRepository
from kg_assistant.models.graph_retrieval import GraphSearchRequest
from kg_assistant.models.graphrag import AskRequest, AskResponse, GroundedAnswer, RetrievalMetadata
from kg_assistant.models.retrieval import VectorSearchRequest
from kg_assistant.providers.base import ExtractionError
from kg_assistant.retrieval.context import ContextBuilder
from kg_assistant.retrieval.graph import GraphRetrievalService
from kg_assistant.retrieval.vector import VectorRetrievalService
from kg_assistant.services.answers import INSUFFICIENT_ANSWER, AnswerGenerationService, map_sources
from kg_assistant.services.embedding_ingestion import DATABASE_ERRORS

logger = logging.getLogger(__name__)


class GraphRAGService:
    def __init__(
        self,
        settings: Settings,
        vector: VectorRetrievalService,
        graph: GraphRetrievalService,
        repository: ContextRepository,
        builder: ContextBuilder,
        generator: AnswerGenerationService | None,
    ) -> None:
        self.settings = settings
        self.vector = vector
        self.graph = graph
        self.repository = repository
        self.builder = builder
        self.generator = generator

    async def ask(self, request: AskRequest, request_id: str | None = None) -> AskResponse:
        started = perf_counter()
        details = {"request_id": request_id}
        logger.info("graphrag_request_started", extra=details)
        try:
            if not self.settings.graphrag_enabled or self.generator is None:
                raise IngestionError(
                    "graphrag_disabled", "Enable and configure GraphRAG first.", 503
                )
            async with asyncio.timeout(self.settings.graphrag_request_timeout):
                # Await both outcomes so neither branch is abandoned/orphaned on peer failure.
                outcomes = await asyncio.gather(
                    self.vector.search(
                        VectorSearchRequest(
                            query=request.question, top_k=self.settings.vector_top_k
                        )
                    ),
                    self.graph.search(
                        GraphSearchRequest(
                            query=request.question, max_hops=self.settings.graph_max_hops
                        )
                    ),
                    return_exceptions=True,
                )
                for branch, outcome in zip(("vector", "graph"), outcomes, strict=True):
                    if isinstance(outcome, BaseException):
                        logger.warning(
                            "graphrag_retrieval_failed", extra={**details, "stage": branch}
                        )
                        if isinstance(outcome, IngestionError):
                            raise outcome
                        raise IngestionError(
                            "retrieval_unavailable", "A required retriever failed.", 503
                        ) from outcome
                vector, graph = outcomes
                logger.info(
                    "graphrag_retrieved",
                    extra={
                        **details,
                        "vector_results": len(vector.results),
                        "graph_paths": len(graph.paths),
                    },
                )
                chunks = await self.repository.load_chunks(self.builder.references(vector, graph))
                context = self.builder.build(vector, graph, chunks)
                logger.info(
                    "graphrag_context_built",
                    extra={
                        **details,
                        "context_chunks": len(context.text_evidence),
                        "context_graph_paths": len(context.graph_evidence),
                        "context_characters": len(context.payload()),
                    },
                )
                if not context.text_evidence and not context.graph_evidence:
                    result = GroundedAnswer(
                        answer=INSUFFICIENT_ANSWER, citations=[], insufficient_evidence=True
                    )
                else:
                    try:
                        result = await self.generator.generate(request.question, context)
                        logger.info("graphrag_generation_succeeded", extra=details)
                    except ExtractionError as exc:
                        logger.warning(
                            "graphrag_generation_failed", extra={**details, "error_code": exc.code}
                        )
                        raise IngestionError(
                            exc.code, "Unable to produce a validated grounded answer.", 502
                        ) from exc
                return AskResponse(
                    question=request.question,
                    answer=result.answer,
                    citations=result.citations,
                    sources=map_sources(result.citations, context),
                    insufficient_evidence=result.insufficient_evidence,
                    retrieval=RetrievalMetadata(
                        vector_results=len(vector.results),
                        graph_paths=len(graph.paths),
                        context_chunks=len(context.text_evidence),
                        context_graph_paths=len(context.graph_evidence),
                        context_characters=len(context.payload()),
                        vector_top_k=self.settings.vector_top_k,
                        graph_max_hops=self.settings.graph_max_hops,
                        graph_status=graph.status,
                        graph_truncated=graph.truncated,
                        context_truncated=context.truncated,
                        duration_ms=round((perf_counter() - started) * 1000, 3),
                    ),
                )
        except DATABASE_ERRORS as exc:
            raise IngestionError(
                "graphrag_unavailable", "GraphRAG timed out or source storage is unavailable.", 503
            ) from exc
        finally:
            logger.info(
                "graphrag_request_finished",
                extra={**details, "duration_ms": round((perf_counter() - started) * 1000, 3)},
            )
