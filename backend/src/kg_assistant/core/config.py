from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from kg_assistant.core.graph_types import ENTITY_TYPES, RELATIONSHIP_TYPES, validate_types

PROJECT_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Knowledge Graph Assistant"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    cors_origins: list[str] = ["http://localhost:3000"]
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_username: str = Field(default="neo4j", min_length=1)
    neo4j_password: SecretStr
    neo4j_database: str = Field(default="neo4j", min_length=1)
    neo4j_connection_timeout: float = Field(default=5, gt=0, le=60)
    neo4j_health_timeout: float = Field(default=5, gt=0, le=60)

    max_file_size: int = Field(default=10 * 1024 * 1024, gt=0)
    chunk_size: int = Field(default=1000, gt=0)
    chunk_overlap: int = Field(default=200, ge=0)
    max_extracted_characters: int = Field(default=2_000_000, gt=0)
    max_docx_uncompressed_bytes: int = Field(default=50 * 1024 * 1024, gt=0)
    max_chunks: int = Field(default=10_000, gt=0)
    neo4j_write_timeout: float = Field(default=30, gt=0, le=300)

    llm_extraction_enabled: bool = False
    llm_provider: Literal["openai"] = "openai"
    openai_api_key: SecretStr | None = None
    llm_model: str = ""
    llm_request_timeout: float = Field(default=30, gt=0, le=300)
    llm_max_attempts: int = Field(default=2, ge=1, le=5)
    llm_retry_backoff: float = Field(default=0.5, ge=0, le=10)
    llm_max_output_tokens: int = Field(default=4096, ge=256, le=32768)
    embedding_enabled: bool = False
    embedding_provider: Literal["openai"] = "openai"
    embedding_model: str = ""
    embedding_dimensions: int = Field(default=1536, ge=1, le=4096)
    embedding_request_dimensions: bool = True
    embedding_batch_size: int = Field(default=32, ge=1, le=128)
    embedding_request_timeout: float = Field(default=30, gt=0, le=300)
    embedding_max_attempts: int = Field(default=2, ge=1, le=5)
    embedding_retry_backoff: float = Field(default=0.5, ge=0, le=10)
    embedding_max_input_characters: int = Field(default=24000, ge=1, le=100000)
    vector_max_top_k: int = Field(default=50, ge=1, le=100)
    vector_index_timeout: float = Field(default=30, gt=0, le=300)
    graph_retrieval_enabled: bool = False
    graph_max_hops: int = Field(default=3, ge=1, le=5)
    graph_max_anchors: int = Field(default=5, ge=1, le=10)
    graph_fan_out: int = Field(default=25, ge=1, le=100)
    graph_max_candidates: int = Field(default=200, ge=1, le=1000)
    graph_max_results: int = Field(default=25, ge=1, le=100)
    graph_max_evidence: int = Field(default=3, ge=1, le=10)
    graph_retrieval_timeout: float = Field(default=10, gt=0, le=60)
    graphrag_enabled: bool = False
    vector_top_k: int = Field(default=5, ge=1, le=100)
    max_graph_paths: int = Field(default=5, ge=1, le=25)
    max_context_chunks: int = Field(default=10, ge=1, le=50)
    max_context_characters: int = Field(default=20000, ge=1000, le=100000)
    max_chunk_context_characters: int = Field(default=4000, ge=100, le=32000)
    graphrag_request_timeout: float = Field(default=120, gt=0, le=600)
    entity_types: list[str] = Field(default_factory=lambda: ENTITY_TYPES.copy())
    relationship_types: list[str] = Field(default_factory=lambda: RELATIONSHIP_TYPES.copy())

    @field_validator("entity_types", "relationship_types")
    @classmethod
    def validate_graph_types(cls, values: list[str]) -> list[str]:
        return validate_types(values)

    @model_validator(mode="after")
    def validate_llm(self) -> "Settings":
        if self.llm_extraction_enabled or self.graph_retrieval_enabled:
            if not self.openai_api_key or not self.openai_api_key.get_secret_value().strip():
                raise ValueError("Set OPENAI_API_KEY when LLM extraction is enabled")
            if not self.llm_model.strip() or self.llm_model == "your-structured-output-model":
                raise ValueError("Set LLM_MODEL to a model supporting structured outputs")
        if self.embedding_enabled:
            if not self.openai_api_key or not self.openai_api_key.get_secret_value().strip():
                raise ValueError("Set OPENAI_API_KEY when embeddings are enabled")
            if not self.embedding_model.strip():
                raise ValueError("Set EMBEDDING_MODEL when embeddings are enabled")
        if self.graphrag_enabled:
            if not self.embedding_enabled or not self.graph_retrieval_enabled:
                raise ValueError("GraphRAG requires both embedding and graph retrieval enablement")
            if self.vector_top_k > self.vector_max_top_k:
                raise ValueError("VECTOR_TOP_K must not exceed VECTOR_MAX_TOP_K")
        return self

    @model_validator(mode="after")
    def validate_chunking(self) -> "Settings":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self

    @field_validator("neo4j_uri")
    @classmethod
    def validate_uri(cls, value: str) -> str:
        uri = urlsplit(value)
        if uri.scheme not in {"bolt", "bolt+s", "bolt+ssc", "neo4j", "neo4j+s", "neo4j+ssc"}:
            raise ValueError("Unsupported Neo4j URI scheme")
        if not uri.hostname or uri.username or uri.password:
            raise ValueError("Use a host URI and separate credential settings")
        return value

    @field_validator("neo4j_password")
    @classmethod
    def validate_password(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("Neo4j password must not be blank")
        if value.get_secret_value() == "replace-with-a-local-password":
            raise ValueError("Replace the example Neo4j password")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
