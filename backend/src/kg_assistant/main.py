import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.responses import Response

from kg_assistant.api.routes.documents import router as documents_router
from kg_assistant.api.routes.embeddings import router as embeddings_router
from kg_assistant.api.routes.graph import router as graph_router
from kg_assistant.api.routes.graphrag import router as graphrag_router
from kg_assistant.api.routes.health import router
from kg_assistant.api.routes.retrieval import router as retrieval_router
from kg_assistant.core.body_limit import RequestBodyLimitMiddleware
from kg_assistant.core.config import Settings, get_settings
from kg_assistant.core.exceptions import IngestionError
from kg_assistant.core.logging import configure_logging
from kg_assistant.db.neo4j import Neo4jConnectionManager
from kg_assistant.providers.answer import OpenAIAnswerProvider
from kg_assistant.providers.embeddings import OpenAIEmbeddingProvider
from kg_assistant.providers.openai import OpenAIExtractionProvider
from kg_assistant.providers.query_entities import OpenAIQueryEntityProvider

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings if settings is not None else get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(config.log_level)
        connection = Neo4jConnectionManager(config)
        app.state.neo4j = connection
        app.state.extraction_provider = None
        app.state.embedding_provider = None
        app.state.query_entity_provider = None
        app.state.answer_provider = None
        try:
            await connection.start()
            if config.llm_extraction_enabled:
                app.state.extraction_provider = OpenAIExtractionProvider(config)
            if config.embedding_enabled:
                app.state.embedding_provider = OpenAIEmbeddingProvider(config)
            if config.graph_retrieval_enabled:
                app.state.query_entity_provider = OpenAIQueryEntityProvider(config)
            if config.graphrag_enabled:
                app.state.answer_provider = OpenAIAnswerProvider(config)
            logger.info("application_started")
            yield
        finally:
            try:
                if app.state.extraction_provider is not None:
                    await app.state.extraction_provider.close()
            finally:
                try:
                    if app.state.embedding_provider is not None:
                        await app.state.embedding_provider.close()
                finally:
                    try:
                        if app.state.query_entity_provider is not None:
                            await app.state.query_entity_provider.close()
                    finally:
                        try:
                            if app.state.answer_provider is not None:
                                await app.state.answer_provider.close()
                        finally:
                            await connection.close()
            logger.info("application_stopped")

    app = FastAPI(title=config.app_name, version="0.1.0", lifespan=lifespan)
    app.state.settings = config
    app.add_middleware(RequestBodyLimitMiddleware, max_file_size=config.max_file_size)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = uuid4().hex
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error("request_failed:%s", type(exc).__name__, extra={"request_id": request_id})
            response = JSONResponse(
                status_code=500,
                content={"error": {"code": "internal_error", "message": "Internal server error"}},
            )
        response.headers["X-Request-ID"] = request_id
        logger.info("request_completed:%s", response.status_code, extra={"request_id": request_id})
        return response

    @app.exception_handler(IngestionError)
    async def ingestion_error(request: Request, exc: IngestionError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    app.include_router(documents_router)
    app.include_router(graph_router)
    app.include_router(graphrag_router)
    app.include_router(retrieval_router)
    app.include_router(embeddings_router)
    app.include_router(router)
    return app
