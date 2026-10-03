# Implementation

The backend uses async FastAPI, Pydantic contracts/settings, one lifecycle-managed Neo4j driver, and asynchronous provider clients. Thin routes delegate to services, database logic is encapsulated in repositories, and AI adapters implement replaceable provider interfaces. FastAPI dependency injection supplies these components and enables mocks in tests. These are actual separation/reuse mechanisms, not invented pattern claims.

| Implemented module | Responsibility and important behavior |
|---|---|
| core/config, main, api/dependencies | Environment-backed configuration, lifespan, dependency injection, CORS, error/correlation middleware |
| core/body_limit | Bound transport bytes before parsing, including chunked requests; actual file limit enforced separately |
| ingestion/extraction | PDF pages, DOCX body/table text, UTF-8 TXT, corruption/empty/expansion/text limits; parsing moved to worker threads |
| ingestion/chunking | Character windows, overlap, stable per-document IDs, PDF page boundaries and continuous chunk indices |
| ingestion/entity_extraction, providers/openai | Structured entities/relationships, type/reference/verbatim evidence validation, bounded retries |
| ingestion/normalization | Unicode/name normalization, semantic type identity, duplicate handling, stable entity IDs |
| db/repositories/documents, knowledge_graph | Base atomic storage; per-chunk atomic graph writes; run/lease ownership; statuses and recovery |
| services/embeddings, providers/embeddings | Batch/query vectors, dimensions/finite values/cardinality validation, timeouts/retries |
| db/repositories/vectors | Idempotent cosine index/model fingerprint, guarded vector writes/backfill, source-aware vector results |
| retrieval/query_entities, graph | Grounded query anchors, existing-entity resolution, BFS, cycles/bounds/provenance, deterministic path ranking |
| retrieval/context | Verified chunk/path fusion, dedupe, count/serialized character limits, actual excerpt provenance |
| services/answers, prompts/answer | Evidence-only structured answer, validated inline/list citations, canonical insufficiency |
| services/graphrag | Concurrent retrievers, error propagation, source hydration/fusion/generation orchestration and count/timing logs |
| api/routes/graph and graph repository/service | Bounded read-only Entity snapshot, preserved direction, parallel-edge display collapse |
| evaluation | Text-only baseline reuses working services; hybrid uses production orchestrator; metrics/timings/optional usage, JSON/Markdown/JUnit reports |
| frontend/src/lib and components | Central API/types, real transfer/processing states, session history, chat/source expansion, responsive sidebar, Cytoscape lifecycle and entity inspection |

OpenAI Responses/Pydantic structured output is used for extraction, anchors, and answers. The embedding model/dimensions are configured (example: text-embedding-3-small, 1536); no hardcoded credential exists in source. Requests use store=false in Responses adapters. Provider lifecycle is explicit. Optional evaluation usage observers are inactive in production by default; unknown usage remains null.

Failures after base upload persistence retain source text for recovery. Completed chunks/vectors are skipped by retry/backfill. Queries do not create entities. Provenance is checked against actual Neo4j ownership and excerpts, while unsupported/unavailable source information stays absent. Citation validation does not prove that an answer is semantically entailed; live-provider manual evaluation is necessary.

The frontend fetches production endpoints and never hardcodes a demo graph. Sources and model text are rendered as text; no unsafe HTML injection is used. NEXT_PUBLIC variables contain only backend URL/upload limit. A browser timeout is cancellation of the client request, not durable job cancellation; large synchronous ingestion remains a limitation.
