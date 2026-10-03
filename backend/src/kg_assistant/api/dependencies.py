from typing import Annotated

from fastapi import Depends, Request

from kg_assistant.core.config import Settings
from kg_assistant.db.neo4j import Neo4jConnectionManager
from kg_assistant.db.repositories.context import ContextRepository
from kg_assistant.db.repositories.documents import DocumentRepository
from kg_assistant.db.repositories.graph import GraphVisualizationRepository
from kg_assistant.db.repositories.knowledge_graph import KnowledgeGraphRepository
from kg_assistant.db.repositories.vectors import VectorRepository
from kg_assistant.ingestion.chunking import ChunkingService
from kg_assistant.ingestion.entity_extraction import EntityExtractionService
from kg_assistant.ingestion.extraction import TextExtractionService
from kg_assistant.providers.answer import AnswerProvider
from kg_assistant.providers.base import ExtractionProvider
from kg_assistant.providers.embeddings import EmbeddingProvider
from kg_assistant.providers.query_entities import QueryEntityProvider
from kg_assistant.retrieval.context import ContextBuilder
from kg_assistant.retrieval.graph import GraphRetrievalService
from kg_assistant.retrieval.query_entities import QueryEntityExtractionService
from kg_assistant.retrieval.vector import VectorRetrievalService
from kg_assistant.services.answers import AnswerGenerationService
from kg_assistant.services.documents import DocumentService
from kg_assistant.services.embedding_ingestion import EmbeddingIngestionService
from kg_assistant.services.embeddings import EmbeddingService
from kg_assistant.services.graph import GraphVisualizationService
from kg_assistant.services.graphrag import GraphRAGService
from kg_assistant.services.knowledge_graph import GraphIngestionService


def get_config(request: Request) -> Settings:
    return request.app.state.settings


def get_neo4j(request: Request) -> Neo4jConnectionManager:
    return request.app.state.neo4j


def get_graph_visualization(
    connection: Annotated[Neo4jConnectionManager, Depends(get_neo4j)],
    config: Annotated[Settings, Depends(get_config)],
) -> GraphVisualizationService:
    return GraphVisualizationService(GraphVisualizationRepository(connection, config))


def get_document_repository(
    connection: Annotated[Neo4jConnectionManager, Depends(get_neo4j)],
    config: Annotated[Settings, Depends(get_config)],
) -> DocumentRepository:
    return DocumentRepository(connection, config.neo4j_write_timeout)


def get_extraction_provider(request: Request) -> ExtractionProvider | None:
    return request.app.state.extraction_provider


def get_graph_repository(
    connection: Annotated[Neo4jConnectionManager, Depends(get_neo4j)],
    config: Annotated[Settings, Depends(get_config)],
) -> KnowledgeGraphRepository:
    lease = (
        config.llm_request_timeout * config.llm_max_attempts
        + config.llm_retry_backoff * config.llm_max_attempts**2
        + config.neo4j_write_timeout
        + 30
    )
    return KnowledgeGraphRepository(
        connection,
        config.neo4j_write_timeout,
        config.entity_types,
        config.relationship_types,
        lease,
    )


def get_graph_ingestion(
    config: Annotated[Settings, Depends(get_config)],
    repository: Annotated[KnowledgeGraphRepository, Depends(get_graph_repository)],
    provider: Annotated[ExtractionProvider | None, Depends(get_extraction_provider)],
) -> GraphIngestionService:
    extractor = EntityExtractionService(provider, config) if provider is not None else None
    return GraphIngestionService(config, repository, extractor)


def get_embedding_provider(request: Request) -> EmbeddingProvider | None:
    return request.app.state.embedding_provider


def get_vector_repository(
    connection: Annotated[Neo4jConnectionManager, Depends(get_neo4j)],
    config: Annotated[Settings, Depends(get_config)],
) -> VectorRepository:
    return VectorRepository(connection, config)


def get_embedding_service(
    config: Annotated[Settings, Depends(get_config)],
    provider: Annotated[EmbeddingProvider | None, Depends(get_embedding_provider)],
) -> EmbeddingService | None:
    return EmbeddingService(provider, config) if provider is not None else None


def get_embedding_ingestion(
    config: Annotated[Settings, Depends(get_config)],
    repository: Annotated[VectorRepository, Depends(get_vector_repository)],
    embedder: Annotated[EmbeddingService | None, Depends(get_embedding_service)],
) -> EmbeddingIngestionService:
    return EmbeddingIngestionService(config, repository, embedder)


def get_vector_retrieval(
    config: Annotated[Settings, Depends(get_config)],
    repository: Annotated[VectorRepository, Depends(get_vector_repository)],
    embedder: Annotated[EmbeddingService | None, Depends(get_embedding_service)],
) -> VectorRetrievalService:
    return VectorRetrievalService(config, repository, embedder)


def get_document_service(
    config: Annotated[Settings, Depends(get_config)],
    repository: Annotated[DocumentRepository, Depends(get_document_repository)],
    graph: Annotated[GraphIngestionService, Depends(get_graph_ingestion)],
    embeddings: Annotated[EmbeddingIngestionService, Depends(get_embedding_ingestion)],
) -> DocumentService:
    return DocumentService(
        config,
        TextExtractionService(config.max_extracted_characters, config.max_docx_uncompressed_bytes),
        ChunkingService(config.chunk_size, config.chunk_overlap, config.max_chunks),
        repository,
        graph,
        embeddings,
    )


def get_query_entity_provider(request: Request) -> QueryEntityProvider | None:
    return request.app.state.query_entity_provider


def get_graph_retrieval(
    config: Annotated[Settings, Depends(get_config)],
    connection: Annotated[Neo4jConnectionManager, Depends(get_neo4j)],
    provider: Annotated[QueryEntityProvider | None, Depends(get_query_entity_provider)],
) -> GraphRetrievalService:
    extractor = QueryEntityExtractionService(config, provider) if provider is not None else None
    return GraphRetrievalService(config, connection, extractor)


def get_answer_provider(request: Request) -> AnswerProvider | None:
    return request.app.state.answer_provider


def get_graphrag(
    config: Annotated[Settings, Depends(get_config)],
    connection: Annotated[Neo4jConnectionManager, Depends(get_neo4j)],
    vector: Annotated[VectorRetrievalService, Depends(get_vector_retrieval)],
    graph: Annotated[GraphRetrievalService, Depends(get_graph_retrieval)],
    provider: Annotated[AnswerProvider | None, Depends(get_answer_provider)],
) -> GraphRAGService:
    generator = AnswerGenerationService(config, provider) if provider is not None else None
    return GraphRAGService(
        config,
        vector,
        graph,
        ContextRepository(connection, config),
        ContextBuilder(config),
        generator,
    )
