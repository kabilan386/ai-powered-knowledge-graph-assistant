# Actual environment configuration

Root .env is private and ignored. This inventory comes from Settings fields and safe .env.example values; it never includes local credentials. Compose forwards the documented application settings except host Neo4j URI/username/database, which are fixed internally to the local service. Frontend values are public and resolved at build time.

| Variable | Safe example / default |
|---|---|
| APP_NAME | `Knowledge Graph Assistant` |
| LOG_LEVEL | `INFO` |
| CORS_ORIGINS | `["http://localhost:3000"]` |
| NEO4J_URI | `bolt://localhost:7687` |
| NEO4J_USERNAME | `neo4j` |
| NEO4J_PASSWORD | `replace-with-a-local-password` |
| NEO4J_DATABASE | `neo4j` |
| NEO4J_CONNECTION_TIMEOUT | `5` |
| NEO4J_HEALTH_TIMEOUT | `5` |
| MAX_FILE_SIZE | `10485760` |
| CHUNK_SIZE | `1000` |
| CHUNK_OVERLAP | `200` |
| MAX_EXTRACTED_CHARACTERS | `2000000` |
| MAX_DOCX_UNCOMPRESSED_BYTES | `52428800` |
| MAX_CHUNKS | `10000` |
| NEO4J_WRITE_TIMEOUT | `30` |
| LLM_EXTRACTION_ENABLED | `false` |
| LLM_PROVIDER | `openai` |
| OPENAI_API_KEY | `(empty; configure when enabled)` |
| LLM_MODEL | `(empty; configure when enabled)` |
| LLM_REQUEST_TIMEOUT | `30` |
| LLM_MAX_ATTEMPTS | `2` |
| LLM_RETRY_BACKOFF | `0.5` |
| LLM_MAX_OUTPUT_TOKENS | `4096` |
| EMBEDDING_ENABLED | `false` |
| EMBEDDING_PROVIDER | `openai` |
| EMBEDDING_MODEL | `text-embedding-3-small` |
| EMBEDDING_DIMENSIONS | `1536` |
| EMBEDDING_REQUEST_DIMENSIONS | `true` |
| EMBEDDING_BATCH_SIZE | `32` |
| EMBEDDING_REQUEST_TIMEOUT | `30` |
| EMBEDDING_MAX_ATTEMPTS | `2` |
| EMBEDDING_RETRY_BACKOFF | `0.5` |
| EMBEDDING_MAX_INPUT_CHARACTERS | `24000` |
| VECTOR_MAX_TOP_K | `50` |
| VECTOR_INDEX_TIMEOUT | `30` |
| GRAPH_RETRIEVAL_ENABLED | `false` |
| GRAPH_MAX_HOPS | `3` |
| GRAPH_MAX_ANCHORS | `5` |
| GRAPH_FAN_OUT | `25` |
| GRAPH_MAX_CANDIDATES | `200` |
| GRAPH_MAX_RESULTS | `25` |
| GRAPH_MAX_EVIDENCE | `3` |
| GRAPH_RETRIEVAL_TIMEOUT | `10` |
| GRAPHRAG_ENABLED | `false` |
| VECTOR_TOP_K | `5` |
| MAX_GRAPH_PATHS | `5` |
| MAX_CONTEXT_CHUNKS | `10` |
| MAX_CONTEXT_CHARACTERS | `20000` |
| MAX_CHUNK_CONTEXT_CHARACTERS | `4000` |
| GRAPHRAG_REQUEST_TIMEOUT | `120` |
| ENTITY_TYPES | `["PERSON","ORGANIZATION","PROJECT","SERVICE","TECHNOLOGY","DATABASE","CLOUD_SERVICE","LOCATION","CONCEPT","OTHER"]` |
| RELATIONSHIP_TYPES | `["WORKS_ON","USES","MANAGES","DEPENDS_ON","HOSTED_ON","PART_OF","BELONGS_TO","CREATED_BY","LOCATED_IN","RELATED_TO"]` |
| NEXT_PUBLIC_API_BASE_URL | `http://localhost:8000` |
| NEXT_PUBLIC_MAX_FILE_SIZE | frontend `.env.local`: `10485760`; Docker derives from MAX_FILE_SIZE |

OPENAI_API_KEY is the implemented server credential; LLM_API_KEY is not an alias. EMBEDDING_DIMENSIONS is plural. Structured outputs require a compatible Responses model. Embedding provider/model/dimension identity must match persisted data. Never silently reset a mismatched index. CORS_ORIGINS, ENTITY_TYPES, RELATIONSHIP_TYPES are JSON arrays; domain type identifiers are validated uppercase server allowlists.

See core/config.py for all bounds and feature-flag validation. Test-only variables KG_RUN_NEO4J_TESTS and TEST_NEO4J_URI/USERNAME/PASSWORD/DATABASE select an isolated database; they are not production configuration.
