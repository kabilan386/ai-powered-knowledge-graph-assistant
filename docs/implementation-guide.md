# AI-Powered Knowledge Graph Assistant

MCA final project using GraphRAG and large language models. Neo4j holds both the labeled property graph and Chunk vector index; no separate vector database is used.

Milestones 1–8 implement the FastAPI foundation, PDF/DOCX/TXT ingestion, structured LLM knowledge graph extraction with provenance, Chunk embeddings, Neo4j vector indexing/search, missing-vector backfill, separate bounded multi-hop graph retrieval, hybrid context fusion, and grounded LLM answers with validated citations, and a Next.js dashboard for upload, chat, and Cytoscape.js graph visualization. Milestone 8 adds paired Vector RAG/GraphRAG evaluation, deterministic metrics, and reports generated from executed tests. Authentication, unrestricted Text-to-Cypher, and external reranking remain outside the current scope.

## Prerequisites

- Python 3.12 or 3.13 and [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Docker with Docker Compose v2
- Node.js **24.15+** and npm for local frontend development (the pinned test tools require it; Docker supplies Node 24.19.0)

## Configuration

From the repository root:

```bash
cp .env.example .env
```

Edit `.env` and replace `NEO4J_PASSWORD` with a local password of at least eight characters. The API rejects the example placeholder. Credentials stay in the ignored `.env`; do not commit them.

Settings load from the root `.env`, with environment variables taking precedence. `CORS_ORIGINS` is a JSON array. Connection and health timeouts are in seconds. Compose uses the initial Neo4j username/database `neo4j` and overrides the API URI to `bolt://neo4j:7687`; the host-run API uses `bolt://localhost:7687`.

## Run with Docker

```bash
docker compose up --build -d --wait
docker compose ps
```

- Frontend: http://localhost:3000
- API docs: http://localhost:8000/docs
- Liveness: http://localhost:8000/health/live
- Readiness including Neo4j: http://localhost:8000/health/ready
- Neo4j Browser: http://localhost:7474 (username `neo4j`, password from `.env`)

All published ports bind to localhost. Neo4j uses a persistent named volume. `docker compose down` stops the services and preserves data. Changing the initial password in `.env` does not update an existing database's credentials; change them through Neo4j and then update configuration.

## Run the backend locally

Start only Neo4j, then install and run the API:

```bash
docker compose up -d --wait neo4j
uv sync --project backend --locked
cd backend
uv run uvicorn kg_assistant.main:create_app --factory --reload --host 127.0.0.1 --port 8000
```

The app uses FastAPI lifespan to create/close one async Neo4j driver per process. Startup does not require an available database: liveness remains 200 during database outages, while readiness executes `RETURN 1` against the configured database and returns 503 if connectivity, authentication, database access, or the bounded timeout fails. Health responses do not expose driver errors or credentials. Requests receive a server-generated `X-Request-ID`; application logs are JSON.

## Tests and checks

From the repository root:

```bash
uv run --project backend --locked pytest
uv run --project backend --locked ruff check backend
uv run --project backend --locked ruff format --check backend
```

Routine tests use mocked Neo4j drivers, need no credentials or running server, and cover configuration validation, driver cleanup, readiness success/failure, timeouts, dependency overrides, and sanitized errors. Compose's health check exercises a real database; verify `/health/ready` after starting the stack to check API-to-database connectivity.

`backend/uv.lock` locks development/runtime dependencies. `backend/requirements.lock` is its generated runtime-only export used by Docker. After changing dependencies, regenerate it:

```bash
uv lock --project backend
uv export --project backend --locked --no-dev --no-emit-project --format requirements-txt --output-file backend/requirements.lock
```

See [the implementation plan](implementation-plan.md) and [coding rules](../AGENTS.md).

Implementation references: [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/), [Neo4j async driver API](https://neo4j.com/docs/api/python-driver/current/async_api.html), and [Neo4j Docker setup](https://neo4j.com/docs/operations-manual/current/docker/introduction/).

## Upload a document

`POST /api/documents/upload` accepts a multipart form with a required `file` field. PDF, DOCX, and UTF-8 TXT are supported; suffix checks are case-insensitive, and contents must parse as the selected format. Files are parsed in memory after validation; original binaries are not retained. Upload processing is synchronous, and a `201 Created` response means the document and all chunks have committed to Neo4j.

```bash
curl --fail-with-body -X POST http://localhost:8000/api/documents/upload \
  -F 'file=@/absolute/path/notes.pdf'
```

Example response:

```json
{
  "document": {
    "id": "generated-document-uuid",
    "filename": "notes.pdf",
    "file_type": "pdf",
    "created_at": "2026-10-03T00:00:00Z"
  },
  "chunk_count": 4
}
```

You can also upload from `/docs`. Only the filename basename is stored. Each HTTP upload creates a new document, including repeated uploads of identical content. Internal transaction retries reuse the same IDs without duplicating nodes or edges.

Configuration in `.env` (also passed through by Compose):

| Setting | Default | Meaning |
|---|---:|---|
| `MAX_FILE_SIZE` | 10485760 | Maximum uploaded file bytes (10 MiB) |
| `CHUNK_SIZE` | 1000 | Maximum characters per chunk |
| `CHUNK_OVERLAP` | 200 | Characters repeated between adjacent windows; must be less than chunk size |
| `MAX_EXTRACTED_CHARACTERS` | 2000000 | Maximum extracted text length |
| `MAX_DOCX_UNCOMPRESSED_BYTES` | 52428800 | Maximum expanded DOCX archive size |
| `MAX_CHUNKS` | 10000 | Maximum chunks per document |
| `NEO4J_WRITE_TIMEOUT` | 30 | Deadline for schema setup and the document write, in seconds |

Chunks use fixed character windows, retaining the original extracted whitespace. Whitespace-only chunks are omitted. Chunks never cross PDF page boundaries; overlap resets at each page, while indices continue across the whole document. PDF page numbers start at 1; chunk indices start at 0. DOCX extraction preserves main-body paragraph/table order; it does not infer rendered page numbers or extract headers, footers, or text boxes. TXT must be UTF-8 (an optional BOM is accepted). Image-only PDFs need OCR, which is not implemented. Encrypted PDFs are rejected.

Errors use `{"error": {"code": "...", "message": "..."}}`: unsupported types return 415; empty files/invalid filenames return 400; upload/extraction/chunk limits return 413; unreadable or text-free documents return 422; database failures return 503. FastAPI returns its standard 422 validation response when the required `file` field is missing. Failed base document writes roll back all document and chunk data. File validation/text extraction failures store nothing. LLM extraction runs after this base commit: a failed chunk leaves its document/text intact and returns explicit extraction errors (see milestone 3 below).

## Neo4j document model and manual verification

```text
(:Document {id, filename, file_type, created_at})
    -[:HAS_CHUNK]->
(:Chunk {id, document_id, text, chunk_index, page_number})
```

`created_at` is a Neo4j datetime. `document_id` is also retained on each Chunk. `page_number` is present for PDFs; for TXT/DOCX it is unavailable (Neo4j omits null-valued properties). Chunk IDs are deterministic within a document. The first successful upload ensures Document/Chunk ID uniqueness constraints exist; the configured database user needs schema permissions. Schema setup is idempotent and runs separately from the atomic data transaction. Cypher structure is fixed and all document/chunk values are parameters.

After uploading, copy the response's document ID, open Neo4j Browser at http://localhost:7474, and run:

```cypher
:param document_id => 'paste-document-id-here';
MATCH (d:Document {id: $document_id})-[r:HAS_CHUNK]->(c:Chunk)
RETURN d, r, c;
```

Choose the graph visualization to see the document connected to chunks. To inspect their order and provenance:

```cypher
MATCH (d:Document {id: $document_id})-[:HAS_CHUNK]->(c:Chunk)
RETURN d.filename AS filename, c.document_id AS document_id,
       c.chunk_index AS chunk_index, c.page_number AS page_number, c.text AS text
ORDER BY c.chunk_index;
```

## Real Neo4j integration tests

Routine tests exercise the actual extraction/chunking services and multipart API with an injected repository. Opt-in tests additionally verify PDF/DOCX/TXT uploads against Neo4j, knowledge graph construction/provenance, normalization, failed-chunk recovery, concurrent run protection, idempotent writes, and transaction rollback. Their LLM and embedding providers are mocked. Vector tests verify actual cosine ranking, index/model compatibility, source metadata, missing-vector recovery, and lease ownership. Use an isolated test instance and provide its connection settings:

```bash
export KG_RUN_NEO4J_TESTS=1
export TEST_NEO4J_URI=bolt://localhost:7687
export TEST_NEO4J_USERNAME=neo4j
export TEST_NEO4J_DATABASE=neo4j
read -s -p 'Test Neo4j password: ' TEST_NEO4J_PASSWORD
export TEST_NEO4J_PASSWORD
uv run --project backend --locked pytest
```

Integration tests remove their generated documents/chunks and supporting facts; shared normalized entities and idempotent constraints remain. Vector tests also leave a three-dimensional chunk_embedding_index and mock-embedding EmbeddingSpace fingerprint, so use a fresh isolated test database, never your application database. Without `KG_RUN_NEO4J_TESTS=1`, these tests are skipped. They do not require any AI credentials.

Extraction/API references: [FastAPI file uploads](https://fastapi.tiangolo.com/tutorial/request-files/), [pypdf extraction](https://pypdf.readthedocs.io/en/stable/user/extract-text.html), and [python-docx document API](https://python-docx.readthedocs.io/en/latest/api/document.html).

## Milestone 3: Enable structured LLM extraction

The first provider adapter is OpenAI. It uses the async Responses API's Pydantic structured-output parser, not free-form text parsing. Provider selection is behind an interface; currently `LLM_PROVIDER=openai` is the supported setting. No API key or model name is hardcoded. Configure these values in your ignored root `.env`:

```dotenv
LLM_EXTRACTION_ENABLED=true
LLM_PROVIDER=openai
OPENAI_API_KEY=your-api-key
LLM_MODEL=your-structured-output-model
```

Replace both placeholders with your own key and an available model that supports Responses structured outputs. The model placeholder is rejected. Restart the backend after configuration changes (`docker compose up --build -d --wait`, or restart local uvicorn). With extraction disabled (the default), uploads still work and explicitly return `extraction.status="disabled"`. A key/model is required at startup only when enabled.

`ENTITY_TYPES` and `RELATIONSHIP_TYPES` are configurable JSON arrays. Defaults include all entity and relationship types requested for this milestone; custom uppercase identifiers are supported. Values must match `[A-Z][A-Z0-9_]{0,63}`. Administrative relationship types `HAS_CHUNK` and `MENTIONS` are reserved. Neo4j statements use fixed templates built only from this validated server allowlist, with all document/LLM data values passed as parameters. No LLM-generated Cypher is executed. Templates are grouped by relationship type to avoid dynamic-MERGE type evaluation issues found during integration tests on Neo4j 5.26.0.

The Pydantic extraction contract contains:

- Entities: `key`, `name`, `type`, nullable `description`, and `evidence_quote`.
- Relationships: `source` and `target` **local entity keys**, `type`, nullable `description`, and `evidence_quote`.
- Result: `entities[]` and `relationships[]`; empty arrays are a successful extraction.

Local keys disambiguate names inside an extraction response. Unknown keys, malformed structures, extra fields, and unconfigured types are rejected. Every quote must occur verbatim in the chunk. Entity quotes must contain the entity name; relationship quotes must contain both endpoint names. The prompt restricts relations to explicitly stated facts, excluding inferred, negated, hypothetical, or uncertain relations. These mechanical checks verify source presence, but do not prove a model's semantic interpretation; inspect the stored quotes and evaluate extraction quality for your domain.

Additional settings:

| Setting | Default | Meaning |
|---|---:|---|
| `LLM_REQUEST_TIMEOUT` | 30 | Seconds per extraction attempt |
| `LLM_MAX_ATTEMPTS` | 2 | Total attempts per chunk (bounded to 1–5) |
| `LLM_RETRY_BACKOFF` | 0.5 | Seconds multiplied by attempt number between retries |
| `LLM_MAX_OUTPUT_TOKENS` | 4096 | Provider output budget |

Transient provider failures, timeouts, and invalid structured/evidence responses use bounded retries. Non-transient HTTP errors do not retry. The SDK's separate automatic retries are disabled so the configured attempt limit remains authoritative. Refusals/incomplete responses are failures, not empty successes. Inputs, raw LLM responses, and keys are not logged by the application. The provider request uses `store=false`.

## Graph model, normalization, and provenance

```text
Document -[:HAS_CHUNK]-> Chunk -[:MENTIONS]-> Entity
Entity -[:USES | MANAGES | HOSTED_ON | ...]-> Entity
```

Entity properties: `id`, `name`, `normalized_name`, `type`, and optional `description`. Names are normalized with Unicode NFKC, case folding, and whitespace collapse. Entities merge on **(type, normalized_name)**, with stable derived IDs. `Neo4j`, `neo4j`, and `Neo4J` with the same type share one node. The first display name and description are retained; distinct semantic types remain separate nodes. This is basic global name/type matching; distinguishing same-name homonyms within one type is future entity-resolution work.

MENTIONS edges preserve the supporting chunk by their source node and store `source_document_id` and `evidence_quote`. Domain edges store `id`, `source_chunk_id`, `source_document_id`, `evidence_quote`, and optional `description`. The chosen provenance model is **one edge per supporting chunk**. If two chunks support the same fact, two edges retain independent evidence; rewriting the same chunk/fact IDs does not duplicate edges. No support is overwritten by another document.

Base Document/Chunk persistence commits first. Each chunk's entities, mentions, domain edges, and `extraction_status="completed"` then commit together in one transaction. A failed transaction leaves none of that chunk's graph changes. Failure bookkeeping retains a sanitized code and cumulative attempt count on the Chunk. Successful chunks survive failures elsewhere. Chunk metadata also records the extraction model and prompt version.

Document states are `disabled`, `pending`, `processing`, `completed`, `partial`, or `failed`. A successful document upload returns 201 because its source text is stored; **inspect `extraction.status` and `extraction.errors` to determine graph completion**. Example additional response field:

```json
{
  "extraction": {
    "status": "partial",
    "total": 3,
    "completed": 2,
    "failed": 1,
    "errors": [
      {"chunk_id": "failed-chunk-id", "code": "llm_invalid_response", "attempts": 2}
    ]
  }
}
```

The returned document also includes `extraction_status`. If database connectivity prevents graph bookkeeping, the API returns 503 with the saved document ID in its message; avoid re-uploading and use that document's retry endpoint after recovery.

```bash
curl --fail-with-body http://localhost:8000/api/documents/DOCUMENT_ID/extraction
curl --fail-with-body -X POST http://localhost:8000/api/documents/DOCUMENT_ID/extract
```

The first endpoint reads status; the second processes only chunks not marked completed (including documents uploaded before LLM extraction was enabled). Missing documents return 404; disabled extraction returns 503 for retry requests. An active document run blocks concurrent extraction with 409. Runs have a database lease refreshed at each chunk commit/failure; an interrupted run can be retried once the lease expires. Its duration covers the configured per-chunk attempts, backoff, write deadline, and a margin. Run IDs reject stale writes after a newer run acquires the lease. This is synchronous recovery, not a background job queue.

## Manual milestone 3 example

After enabling/configuring the LLM, upload the provided sample (use default chunk settings so it remains in one chunk):

```bash
curl --fail-with-body http://localhost:8000/api/documents/upload \
  -F 'file=@docs/examples/platform-services.txt'
```

Expected supported facts:

```text
Platform Team -[:MANAGES]-> Payment Service
Payment Service -[:USES]-> Redis
Redis -[:HOSTED_ON]-> AWS ElastiCache
```

Copy the returned document ID into Neo4j Browser. Inspect mentions:

```cypher
:param document_id => 'paste-document-id-here';
MATCH (d:Document {id: $document_id})-[:HAS_CHUNK]->(c:Chunk)-[m:MENTIONS]->(e:Entity)
RETURN d, c, m, e;
```

Inspect that document's domain graph:

```cypher
MATCH (source:Entity)-[r]->(target:Entity)
WHERE r.source_document_id = $document_id
RETURN source, r, target;
```

Inspect exact support and relationship direction:

```cypher
MATCH (source:Entity)-[r]->(target:Entity)
WHERE r.source_document_id = $document_id
MATCH (chunk:Chunk {id: r.source_chunk_id})
RETURN source.name AS source, type(r) AS relationship, target.name AS target,
       r.source_document_id AS document_id, chunk.chunk_index AS chunk_index,
       r.evidence_quote AS evidence, chunk.text AS source_text;
```

Inspect extraction errors:

```cypher
MATCH (d:Document {id: $document_id})-[:HAS_CHUNK]->(c:Chunk)
RETURN d.extraction_status AS document_status, c.chunk_index AS chunk_index,
       c.extraction_status AS chunk_status, c.extraction_error AS error,
       c.extraction_attempts AS attempts
ORDER BY c.chunk_index;
```

All automated tests use mock LLM providers, including tests of the deployed architecture against real Neo4j. They cover schema validation, normalization/deduplication, relationship mapping, empty results, invalid output, grounding, retries, per-chunk rollback, provenance, and run protection. No live-provider accuracy claim is made by the tests; manually inspect the sample's evidence after configuring your provider.

Provider reference: [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

## Milestone 4: Chunk embeddings and semantic vector retrieval

Neo4j is the only database. The dedicated embedding service validates vector counts, dimensions, finite numeric values, and nonzero cosine norms. It batches requests and retries transient provider failures with bounded attempts. Its provider interface is independent of retrieval; the initial adapter uses OpenAI's async embeddings API. No Document node is embedded.

Enable embeddings in the root `.env`, using your own API key:

```dotenv
EMBEDDING_ENABLED=true
EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=your-api-key
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536
EMBEDDING_REQUEST_DIMENSIONS=true
```

Restart the backend after changes. `EMBEDDING_ENABLED=false` is the default, so earlier uploads and graph extraction work without embedding credentials. Entity extraction and embeddings have independent enablement flags; enable both to populate the whole current graph. The example third-generation model supports the requested dimension parameter. For models without that parameter, set `EMBEDDING_REQUEST_DIMENSIONS=false` and configure their exact native dimensions. The provider's returned dimensions are always validated, rather than padding or truncating vectors. See [OpenAI embeddings](https://developers.openai.com/api/docs/guides/embeddings).

| Setting | Default | Meaning |
|---|---:|---|
| `EMBEDDING_MODEL` | example: text-embedding-3-small | Explicit model name; required when enabled |
| `EMBEDDING_DIMENSIONS` | 1536 | Exact vector length, 1–4096 |
| `EMBEDDING_REQUEST_DIMENSIONS` | true | Send the API dimension parameter |
| `EMBEDDING_BATCH_SIZE` | 32 | Maximum texts per provider request, 1–128 |
| `EMBEDDING_REQUEST_TIMEOUT` | 30 | Seconds per provider attempt |
| `EMBEDDING_MAX_ATTEMPTS` | 2 | Total attempts per batch, 1–5 |
| `EMBEDDING_RETRY_BACKOFF` | 0.5 | Seconds multiplied by attempt between retries |
| `EMBEDDING_MAX_INPUT_CHARACTERS` | 24000 | Per-text character limit; provider token limits still apply |
| `VECTOR_MAX_TOP_K` | 50 | Configured maximum results, 1–100 |
| `VECTOR_INDEX_TIMEOUT` | 30 | Seconds to wait for index readiness |

Chunking uses characters, not tokens. For highly token-dense inputs or another model, reduce chunk size/input limit to fit that provider's token budget. Non-transient API failures and dimension mismatches do not retry. SDK automatic retries are disabled. Keys, document text, and vectors are not included in application logs.

The pinned Neo4j **5.26.0 Community** image was verified against the actual database using CREATE VECTOR INDEX with parameterized dimensions, db.awaitIndex, and db.index.vector.queryNodes. The index is created lazily on the first enabled upload, backfill, or search, so database availability is still checked through readiness rather than mandatory startup. It indexes `(:Chunk).embedding` as `chunk_embedding_index` with cosine similarity. Creation is idempotent; the existing index's label, property, dimensions, and similarity are checked before use. See [Neo4j 5 vector indexes](https://neo4j.com/docs/cypher-manual/5/indexes/semantic-indexes/vector-indexes/).

```text
Document -[:HAS_CHUNK]-> Chunk {embedding, embedding_provider,
                               embedding_model, embedding_dimensions,
                               embedding_status, embedding_error?}
Chunk -[:MENTIONS]-> Entity
Entity -[:extracted_relationship]-> Entity
EmbeddingSpace {id: "chunk_embedding_index", provider, model, dimensions}
```

EmbeddingSpace is a singleton configuration guard inside Neo4j. One index has one provider/model/dimension identity. Even changing to a different model with the same dimensions returns 409 `embedding_space_mismatch`. Unidentified or incompatible existing vectors also return 409. This protects semantic compatibility, not just vector length. Backfill never changes existing embeddings. Changing models requires a separately planned migration/re-embedding operation; it is not performed automatically by this milestone.

Uploads first commit Document/Chunk source data, then generate embeddings in bounded batches, then run the existing entity extraction stage. These stages have separate completion results; no LLM call is needed for vector search. Embedding provider failures record chunk status/error and still allow entity extraction. A successful upload includes:

```json
{
  "embeddings": {
    "status": "completed",
    "total": 4,
    "completed": 4,
    "failed": 0,
    "errors": []
  }
}
```

A 201 response confirms source persistence; inspect `embeddings` and `extraction` for stage completion. Failed embedding chunks include their IDs and sanitized codes in `embeddings.errors`. Successful embedding batches survive later batch failures. Database errors return 503 and include the saved document ID where available; backfill that ID rather than uploading the source again. Synchronous ingestion, batch timeouts, and maximum chunks bound work; a durable task queue is deferred.

### Semantic retrieval API

```bash
curl --fail-with-body http://localhost:8000/api/retrieval/vector-search \
  -H 'Content-Type: application/json' \
  -d '{"query":"What caching technology does the payment application use?","top_k":5}'
```

`POST /api/retrieval/vector-search` accepts a trimmed nonempty query (maximum 24000 characters and the configured embedding input limit) and an integer `top_k` (default 5, minimum 1, maximum `VECTOR_MAX_TOP_K`). Invalid requests return 422, disabled embeddings/database failures return 503, incompatible index/model configuration returns 409, and query provider failures/dimension mismatches return 502. Missing vectors are excluded; when no eligible chunks exist the response has an empty results array. No answer generation is performed.

```json
{
  "query": "What caching technology does the payment application use?",
  "results": [{
    "chunk_id": "chunk-uuid",
    "text": "Payment Service uses Redis for caching.",
    "score": 0.91,
    "document_id": "document-uuid",
    "filename": "02.txt",
    "page_number": null,
    "chunk_index": 0
  }]
}
```

Scores come directly from Neo4j cosine vector retrieval, not a generated confidence score. Results include their Document ID/filename through HAS_CHUNK and page/chunk metadata for later citations. Only documents with embeddings on every chunk are eligible. Graph extraction status is independent here, because semantic search returns source chunks and makes no graph-derived claims. Neo4j ANN search uses at most min(1000, top_k × 10) candidates before eligibility filtering, so it may return fewer than top_k results even when other eligible chunks exist; it is not exhaustive nearest-neighbor ranking.

### Safe backfill and recovery

```bash
# One saved document, maximum 100 missing chunks per request:
curl --fail-with-body http://localhost:8000/api/embeddings/backfill \
  -H 'Content-Type: application/json' \
  -d '{"document_id":"DOCUMENT_ID","limit":100}'

# Across existing documents (document_id omitted):
curl --fail-with-body http://localhost:8000/api/embeddings/backfill \
  -H 'Content-Type: application/json' -d '{"limit":100}'
```

`limit` is 1–1000, default 100. Response fields are `processed`, `updated`, `skipped`, `remaining`, and `errors[{chunk_id,code}]`. `remaining` includes all missing vectors in the requested scope, including failed chunks and active leases. Repeat requests until remaining is zero; resolve reported provider/configuration errors first. A document ID that does not exist returns 404. Already embedded chunks are neither claimed nor sent to the provider. Failed batches are explicitly reported and can be retried on a later request; one request attempts each claimed chunk only once (with bounded provider retries).

Database claims use expiring per-chunk leases and unique run IDs. Conditional batch transactions write only missing vectors still owned by that run; completed or reclaimed chunks are skipped, never overwritten. Concurrent backfills can claim different batches. A process interruption leaves claims reclaimable after their lease expires; duration covers configured provider attempts/backoff, write timeout, and a margin. Successful vectors and existing knowledge graph nodes/edges remain intact.

### Manual sample and Neo4j inspection

With default chunk settings and embeddings enabled, upload all four public demonstration files:

```bash
for sample in docs/examples/vector-search/*.txt; do
  curl --fail-with-body http://localhost:8000/api/documents/upload -F "file=@$sample"
done
```

Run the semantic query above. The Payment Service/Redis caching chunk should rank highly despite different query wording. Automated tests use fixed mock embeddings to verify actual Neo4j ranking and provenance; this manual check evaluates your real embedding model's semantic quality.

In Neo4j Browser:

```cypher
MATCH (d:Document)-[:HAS_CHUNK]->(c:Chunk)
RETURN d.id AS document_id, d.filename AS filename,
       c.id AS chunk_id, c.text AS text, size(c.embedding) AS dimensions,
       c.embedding_model AS model, c.embedding_status AS status,
       c.embedding_error AS error
LIMIT 10;
```

Inspect the vector index and wait for ONLINE if needed:

```cypher
SHOW VECTOR INDEXES
YIELD name, state, populationPercent, labelsOrTypes, properties, options
WHERE name = 'chunk_embedding_index'
RETURN *;

CALL db.awaitIndex('chunk_embedding_index', 30);
```

Inspect the embedding identity guard:

```cypher
MATCH (s:EmbeddingSpace {id: 'chunk_embedding_index'})
RETURN s.provider, s.model, s.dimensions;
```

For a direct procedure smoke test using an existing vector (its source should score near 1):

```cypher
MATCH (seed:Chunk) WHERE seed.embedding IS NOT NULL
WITH seed LIMIT 1
CALL db.index.vector.queryNodes('chunk_embedding_index', 5, seed.embedding)
YIELD node, score
MATCH (d:Document)-[:HAS_CHUNK]->(node)
RETURN node.id, node.text, score, d.id, d.filename, node.page_number, node.chunk_index;
```

This inspection procedure demonstrates the index directly; the API additionally applies model and document-completeness checks. Embeddings, backfill, and semantic retrieval finish Milestone 4. Later sections describe multi-hop graph retrieval, context fusion, grounded answers, and the frontend added in Milestones 5–7.

## Milestone 5: Read-only multi-hop graph retrieval

`POST /api/retrieval/graph-search` is independent of vector search. It extracts named anchors and retrieval intent with structured Pydantic LLM output, resolves existing Entity nodes, follows bounded domain relationships, and returns ranked paths with source evidence. It does not fuse vector results, generate an answer, create entities, execute user/LLM Cypher, or use a reranking model.

Configure the root `.env` and restart the backend:

```dotenv
GRAPH_RETRIEVAL_ENABLED=true
OPENAI_API_KEY=your-api-key
LLM_MODEL=your-structured-output-model
GRAPH_MAX_HOPS=3
```

Set a real model supporting OpenAI Responses structured output; the adapter uses `responses.parse(text_format=QueryExtraction)` and `store=false`, with lifecycle-managed async clients. See [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs). Graph retrieval uses the existing LLM timeout, retry/backoff, and output-budget settings. Its enablement is independent of `LLM_EXTRACTION_ENABLED` and `EMBEDDING_ENABLED`: querying an already populated graph needs neither ingestion nor embedding API calls. The default is disabled, preserving previous behavior without new credentials. Enable LLM ingestion separately to construct a graph from new uploads.

### Query extraction and resolution

The LLM only produces anchors and hints:

```json
{
  "entities": [{"name":"Platform Team","type":"ORGANIZATION"}],
  "relationship_types": ["MANAGES","USES","HOSTED_ON"],
  "target_type": "CLOUD_SERVICE",
  "direction": "outgoing"
}
```

Anchor names must appear in the question (using existing Unicode/case/whitespace normalization and word-boundary checks). Invented anchors, unconfigured types, malformed output, incomplete responses, and refusals fail explicitly with bounded retries. A generic requested category such as "cloud service" is a target hint, not a newly created entity. Hints guide ranking; relationship hints do not limit traversal to just those types. Direction is outgoing, incoming, or both when uncertain. The LLM can misunderstand intent; these checks validate structure and source presence rather than semantic accuracy.

Resolution reuses Milestone 3 NFKC, case folding, and whitespace collapse. Matching is exact on normalized name with an optional semantic type. An untyped ambiguous name can return multiple bounded anchors; typed anchors are never silently matched to another type. Names that do not resolve are returned in `unresolved_entities`. There is no fuzzy alias resolution or entity creation during retrieval.

### Limits and controlled traversal

| Setting | Default | Limit / meaning |
|---|---:|---|
| `GRAPH_MAX_HOPS` | 3 | Maximum depth; configurable 1–5 |
| `GRAPH_MAX_ANCHORS` | 5 | Resolved anchor cap, 1–10 |
| `GRAPH_FAN_OUT` | 25 | Unique directed domain neighbors per node, 1–100 |
| `GRAPH_MAX_CANDIDATES` | 200 | Unique candidate paths per search, 1–1000 |
| `GRAPH_MAX_RESULTS` | 25 | Ranked paths returned, 1–100 |
| `GRAPH_MAX_EVIDENCE` | 3 | Supporting records per semantic edge, 1–10 |
| `GRAPH_RETRIEVAL_TIMEOUT` | 10 | Seconds for resolution, traversal, evidence reads, and read transaction, up to 60 |

The request's `max_hops` defaults to the configured value and must be between 1 and that maximum, never above 5. Traversal is breadth-first in application code, with cached, fixed single-hop parameterized Cypher queries. It uses a Neo4j read session and a managed read transaction; retrieval runs no DDL, writes, or ingestion bookkeeping. Only Entity-to-Entity edges from the server's configured domain relationship allowlist are followed. HAS_CHUNK and MENTIONS are explicitly excluded even if an incorrectly constructed edge connects two entities.

Facts whose known source Document is not marked extraction_status="completed" are excluded from traversal and evidence. This preserves the publication rule while ingestion is pending, processing, partial, or failed. Edges whose origin is unavailable remain eligible with only the provenance actually stored.

Paths never repeat a node, preventing cycles/self-loops. Distinct semantic paths are deduplicated by ordered node IDs and directed edge identities; parallel facts with different supporting chunks are represented as evidence on the same semantic edge. Stored source/target direction remains explicit in `edges` even when traversal follows an edge in reverse. This avoids presenting `Payment Service ← MANAGES ← Platform Team` as a reversed fact.

A result's `truncated` flag reports anchor/fan-out/candidate/result caps. Each edge separately reports `evidence_truncated`. Truncation means other paths/evidence may exist; increasing hop depth alone does not make the search exhaustive. Database elapsed time is bounded; a timeout returns 503 instead of silently presenting partial traversal as complete. High-degree adjacency reads may still scan many database records before DISTINCT/order/limit, so retain the timeout and tune budgets for your graph. No unbounded variable-length traversal is executed by the API.

### Explainable path ranking

All resolved anchors are exact matches, so they have equal anchor relevance. Score is:

```text
60 × (ordered matching relationship prefix / requested relationship count)
+ 25 if the endpoint matches target_type
+ 10 / hop_count
+ 5 × (edges with available provenance / hop_count)
```

The first term is zero without relationship hints. Node IDs and directed edge identities break ties deterministically. A relevant three-hop chain outranks an incomplete prefix when three relationships and a cloud endpoint were requested; equally relevant shorter paths rank higher. Scores are heuristic retrieval scores, not confidence probabilities or generated answers. Ranking considers only candidates admitted by the bounded traversal.

### API and empty outcomes

```bash
curl --fail-with-body http://localhost:8000/api/retrieval/graph-search \
  -H 'Content-Type: application/json' \
  -d '{"query":"Which cloud service hosts the technology used by the service managed by Platform Team?","max_hops":3}'
```

Response fields are `query`, `anchors`, `unresolved_entities`, `paths`, `status`, and `truncated`. Each path has `hop_count`, `nodes[{id,name,type}]`, `relationships[]`, directed `edges[]`, and `score`. Edges include type/source/target IDs and evidence records with relationship ID, chunk ID, document ID, filename, page number, chunk index, and stored evidence quote where available.

Evidence uses the Milestone 3 relationship's `source_chunk_id` / `source_document_id`, joined to the existing Document-HAS_CHUNK-Chunk relationship. Missing values stay null; an evidence-free edge returns an empty evidence array. No filename, page number, quote, or source association is inferred. These source records are evidence metadata for future citations, not generated citation claims.

Queries must be nonempty after trimming and at most 4000 characters. Invalid query/hops and extra request fields (including Cypher) return 422. Disabled retrieval returns 503; exhausted query provider/validation failures return sanitized 502; database failures/timeouts return 503. Successful empty searches return 200 with explicit status:

- `no_anchors`: extraction found no named anchor.
- `unresolved_anchors`: no extracted anchor matched an existing Entity.
- `no_paths`: anchors resolved but no eligible path was found at the requested depth.
- `ok`: one or more paths found; unresolved names may still be listed alongside resolved anchors.

### Sample graph and three-hop demonstration

Enable LLM ingestion if constructing the sample from scratch, then upload the supplied file:

```bash
curl --fail-with-body http://localhost:8000/api/documents/upload \
  -F 'file=@docs/examples/graph-retrieval.txt'
```

Inspect `extraction.status` for completion. The sample has these facts:

```text
Platform Team -MANAGES-> Payment Service -USES-> Redis -HOSTED_ON-> AWS ElastiCache
Payment Service -DEPENDS_ON-> PostgreSQL
Analytics Team -MANAGES-> Analytics Service -USES-> Neo4j
```

Try these queries against `/api/retrieval/graph-search` with max_hops 3:

| Question | Expected highest-ranked relationship chain |
|---|---|
| What does Payment Service use? | USES |
| What service is managed by Platform Team? | MANAGES |
| What technology is used by the service managed by Platform Team? | MANAGES → USES |
| Which cloud service hosts the technology used by the service managed by Platform Team? | MANAGES → USES → HOSTED_ON |

The automated real Neo4j test demonstrates the last query with a mocked structured query extractor: nodes are Platform Team, Payment Service, Redis, AWS ElastiCache; hop_count is 3; relationships are MANAGES, USES, HOSTED_ON. It also checks the first three questions, cycle prevention, excluded infrastructure edges, reverse direction, unrelated Analytics nodes, document/page/chunk evidence, unresolved anchors, and unchanged node/relationship counts after retrieval. Existing vector integration tests continue to run. No paid API calls are made in tests; use the manual queries to assess your configured LLM's anchor/intent quality.

### Inspect paths in Neo4j Browser

At http://localhost:7474, execute this bounded query and select the **Graph** result view:

```cypher
MATCH p=(a:Entity {normalized_name:'platform team', type:'ORGANIZATION'})
        -[:MANAGES|USES|HOSTED_ON|DEPENDS_ON*1..3]->(b:Entity)
WHERE all(n IN nodes(p) WHERE n:Entity)
  AND all(n IN nodes(p) WHERE single(other IN nodes(p) WHERE other = n))
RETURN p
LIMIT 25;
```

Click nodes/edges to inspect their properties. This manual query enumerates bounded sample paths; the API instead uses single-hop expansion and its additional budgets. For the exact three-hop chain:

```cypher
MATCH p=(team:Entity {normalized_name:'platform team', type:'ORGANIZATION'})
        -[:MANAGES]->(:Entity)-[:USES]->(:Entity)-[:HOSTED_ON]->(cloud:Entity)
RETURN p
LIMIT 25;
```

Inspect relationship direction and provenance separately in **Table** view:

```cypher
MATCH (source:Entity)-[r]->(target:Entity)
WHERE type(r) IN ['MANAGES','USES','HOSTED_ON','DEPENDS_ON']
OPTIONAL MATCH (d:Document {id:r.source_document_id})
               -[:HAS_CHUNK]->(c:Chunk {id:r.source_chunk_id})
RETURN source.name AS source, type(r) AS relationship, target.name AS target,
       r.source_document_id AS document_id, r.source_chunk_id AS chunk_id,
       d.filename AS filename, c.page_number AS page_number,
       c.chunk_index AS chunk_index, r.evidence_quote AS evidence
LIMIT 25;
```

Milestone 5 provides standalone structured graph paths. Milestone 6 adds fusion/answers and Milestone 7 adds the frontend; unrestricted Text-to-Cypher and external reranking remain deferred.

## Milestone 6: Hybrid GraphRAG with grounded answers and citations

`POST /api/graphrag/ask` runs both existing retrievers concurrently, verifies their source chunks in Neo4j, builds deterministic bounded context, and asks a separate structured answer provider to answer from that evidence. The existing `/api/retrieval/vector-search` and `/api/retrieval/graph-search` contracts and implementations are unchanged. Neo4j remains the only database.

Configure the root `.env`, replacing the model/key placeholders, then restart the backend:

```dotenv
EMBEDDING_ENABLED=true
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536
GRAPH_RETRIEVAL_ENABLED=true
GRAPH_MAX_HOPS=3
GRAPHRAG_ENABLED=true
OPENAI_API_KEY=your-api-key
LLM_MODEL=your-structured-output-model

VECTOR_TOP_K=5
MAX_GRAPH_PATHS=5
MAX_CONTEXT_CHUNKS=10
MAX_CONTEXT_CHARACTERS=20000
MAX_CHUNK_CONTEXT_CHARACTERS=4000
GRAPHRAG_REQUEST_TIMEOUT=120
```

`GRAPHRAG_ENABLED=false` is the default. Enabling it requires both embedding and graph retrieval flags; configuration rejects `VECTOR_TOP_K` above `VECTOR_MAX_TOP_K`. It uses the existing `LLM_MODEL`, API key, timeout, retry/backoff, and output budget for answer generation. The new provider is replaceable behind AnswerProvider; its async OpenAI Responses adapter uses Pydantic structured output and `store=false`, with SDK retries disabled. See [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

| Setting | Default | Bound / meaning |
|---|---:|---|
| `VECTOR_TOP_K` | 5 | Initial semantic retrieval results; 1–100, no greater than configured vector maximum |
| `GRAPH_MAX_HOPS` | 3 | Existing graph depth; 1–5 |
| `MAX_GRAPH_PATHS` | 5 | Fused complementary paths; 1–25 |
| `MAX_CONTEXT_CHUNKS` | 10 | Unique document/chunk sources supplied; 1–50 |
| `MAX_CONTEXT_CHARACTERS` | 20000 | Exact serialized context JSON character limit; 1000–100000 |
| `MAX_CHUNK_CONTEXT_CHARACTERS` | 4000 | Prefix excerpt limit per chunk; 100–32000 |
| `GRAPHRAG_REQUEST_TIMEOUT` | 120 | Total request deadline in seconds; up to 600 |

The character budget covers context JSON including IDs/metadata, independently of the bounded question and fixed prompt. It is not a tokenizer budget: reduce limits for token-dense text or models with smaller input windows. Individual provider attempts retain the existing timeout; the overall deadline covers both retrievers, source hydration, fusion, retries, and generation.

### Fusion, source verification, and limits

Source hydration uses a new fixed parameterized read query matching the actual `(Document)-[:HAS_CHUNK]->(Chunk)` by both IDs. It obtains real filename, page, index, and a bounded prefix of source text, instead of trusting claimed graph metadata or manufacturing a document from a relationship quote. Graph provenance can supply additional chunks absent from vector results, even when those chunks have no embeddings. Missing/deleted or mismatched source references cannot become S citations.

Text is included once per `(document_id, chunk_id)`. Distinct chunks or documents with overlapping text keep their independent provenance. Graph paths deduplicate by ordered node and directed edge identity; duplicate and redundant prefix paths contribute complementary support before a prefix already covered by a longer path is removed. Evidence per edge keeps the existing graph evidence cap and marks truncation. Branches and different directed paths remain separate.

Paths use existing deterministic scores and ID tie-breaks. Source priority is shared vector/graph chunks first (descending vector score), then other vector chunks, then complementary graph sources in ranked path/edge order. Retained chunks get `S1`, `S2`, ...; retained graph paths get `G1`, `G2`, ... . IDs are deterministic for the same fused inputs but are **local to that response**, not globally stable database identifiers.

When graph paths exist, text uses at most 70% of the serialized context budget, reserving room for graph structure. Remaining candidates that do not fit are omitted rather than sent without limit; paths must fit the total budget. Prefix text truncation and context/count limits are exposed in retrieval metadata and source excerpts. Thus tight budgets can omit relevant evidence and produce an insufficient answer; counts alone do not guarantee coverage.

Graph edges retain their actual source and target direction, including paths traversed backwards. An edge links to retained S IDs only when its provenance pair resolves in Neo4j and its stored quote occurs in the supplied source excerpt. Otherwise it remains an explicit graph fact with `document_backed=false`; no document source is invented. This flag describes document support verified **inside the supplied context**, including whether a quote/source was omitted by the budget, rather than changing the stored graph's provenance.

The answer prompt treats questions, node names, retrieved text, and graph evidence as untrusted data. It permits only supplied facts, preserves graph direction, requires support citations, and requests insufficient evidence for unanswered questions. Document evidence and graph facts without verified document support are kept distinct.

### Structured output and citation safety

The answer provider returns Pydantic GroundedAnswer:

```json
{
  "answer": "Payment Service uses Redis [S1].",
  "citations": ["S1"],
  "insufficient_evidence": false
}
```

For supported answers, citations must be supplied S/G IDs. The structured list must equal the unique bracketed inline citations in order of first appearance, with at least one citation. Unknown IDs such as `[S99]`, mismatched lists, duplicate list entries, or an uncited supported answer are rejected. The safe strategy is bounded retry, then 502 `answer_invalid_citation`; the application never deletes a citation while leaving a potentially unsupported statement intact. Incomplete/refused or invalid provider responses similarly fail explicitly.

A model-reported insufficient answer is replaced with the fixed sentence below, with no citations/sources. Empty fused context bypasses the answer model entirely. If relevant-looking evidence still lacks the requested information, the structured answer model must report insufficiency. Prompting and citation validation reduce hallucination, but **valid source IDs do not prove semantic entailment**. Automated tests mock model behavior; evaluate your configured model on supported, unsupported, misleading, and prompt-injection examples, and manually compare claims with the returned excerpts.

The API returns only cited sources, plus the document sources supporting a cited graph path. `kind="document"` sources include citation ID, document ID, chunk ID, filename, page, chunk index, excerpt, and excerpt truncation. `kind="graph"` sources include nodes, directed edges, and `supporting_citations`; document fields remain null. A G citation may have no supporting documents, and must never be described as coming from a PDF/TXT/DOCX.

### Ask API and failures

```bash
curl --fail-with-body http://localhost:8000/api/graphrag/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"Which cloud service hosts the technology used by the service managed by Platform Team?"}'
```

Response fields: `question`, `answer`, `citations`, `sources`, `retrieval`, and `insufficient_evidence`. Retrieval includes raw vector/path counts, fused chunk/path counts, context characters, configured depth/top-k, graph status/truncation, context truncation, and request duration. The HTTP response retains the server-generated `X-Request-ID`.

Requests require a trimmed nonempty question of at most 4000 characters; unsupported extra fields return 422. Disabled GraphRAG returns 503. **Both retrievers must complete successfully**: zero results is supported, but provider/database/retrieval failures propagate errors rather than becoming empty evidence or a misleading insufficient response. Generic retriever errors, source storage failures, and overall timeouts return sanitized 503; exhausted answer failures return 502; existing retriever validation/configuration errors retain their status. Both concurrent outcomes are awaited, and the overall deadline cancels outstanding work. No durable background processing is introduced.

Structured JSON logs record request ID, stage/error codes, retrieval/context counts, generation success/failure, and duration. They do not include question text, document text, keys, raw model responses, or embedding vectors.

### Manual end-to-end demonstration

1. Enable the configuration above and set `LLM_EXTRACTION_ENABLED=true` to construct the sample graph. Start the existing local/Docker backend as described earlier. Upload the public sample (default chunk settings put this short TXT in one chunk; this is intentional):

   ```bash
   curl --fail-with-body http://localhost:8000/api/documents/upload \
     -F 'file=@docs/examples/graphrag-sample.txt'
   ```

   Require both `embeddings.status` and `extraction.status` to be completed. Copy the returned Document ID.

2. Inspect source chunks and metadata in Neo4j Browser:

   ```cypher
   :param document_id => 'paste-upload-document-id';
   MATCH (d:Document {id:$document_id})-[:HAS_CHUNK]->(c:Chunk)
   RETURN d.id, d.filename, c.id, c.text, c.chunk_index, c.page_number;
   ```

3. Inspect the supported knowledge graph in Graph view:

   ```cypher
   MATCH (source:Entity)-[r]->(target:Entity)
   WHERE r.source_document_id = $document_id
   RETURN source, r, target;
   ```

   Expected: Platform Team -MANAGES-> Payment Service -USES-> Redis -HOSTED_ON-> AWS ElastiCache.

4. Verify embeddings and index state:

   ```cypher
   MATCH (:Document {id:$document_id})-[:HAS_CHUNK]->(c:Chunk)
   RETURN c.id, size(c.embedding) AS dimensions, c.embedding_model, c.embedding_status;
   SHOW VECTOR INDEXES;
   ```

5. Run standalone vector retrieval:

   ```bash
   curl --fail-with-body http://localhost:8000/api/retrieval/vector-search \
     -H 'Content-Type: application/json' \
     -d '{"query":"Which cloud service hosts the technology used by the service managed by Platform Team?","top_k":5}'
   ```

6. Run standalone graph retrieval:

   ```bash
   curl --fail-with-body http://localhost:8000/api/retrieval/graph-search \
     -H 'Content-Type: application/json' \
     -d '{"query":"Which cloud service hosts the technology used by the service managed by Platform Team?","max_hops":3}'
   ```

   Confirm a three-hop path with MANAGES, USES, HOSTED_ON and the uploaded source ID.

7. Call `/api/graphrag/ask` using the request above. The expected supported answer identifies Payment Service, Redis, and AWS ElastiCache, with valid S and/or G citations. For the one-chunk TXT, all three facts may share one S citation. The integration test uses a three-page PDF to verify three distinct source chunks and page numbers.

8. Inspect each claim against the returned source excerpts and directed graph edges. Try the unsupported query:

   ```bash
   curl --fail-with-body http://localhost:8000/api/graphrag/ask \
     -H 'Content-Type: application/json' \
     -d '{"question":"Who is the CEO of Payment Service?"}'
   ```

   Expected: `insufficient_evidence=true`, no citations/sources, and "The available knowledge does not contain enough information to answer this question." A related service/cache/hosting fact does not establish a CEO.

9. For every returned document source, copy its document and chunk IDs into this parameterized verification query:

   ```cypher
   :param source_document_id => 'document_id-from-a-returned-source';
   :param source_chunk_id => 'chunk_id-from-that-source';
   MATCH (d:Document {id:$source_document_id})-[:HAS_CHUNK]->(c:Chunk {id:$source_chunk_id})
   RETURN d.filename, c.id, c.text, c.page_number, c.chunk_index;
   ```

   The filename/page/index must match the response, and its excerpt must be a prefix of the actual chunk text. Citation S IDs are response-local labels, not Neo4j properties. For a cited G path, inspect `sources[].supporting_citations`, then resolve each corresponding S source; if the list is empty, it is graph-only evidence.

The complete test suite covers concurrent orchestration, deterministic fusion, complementary evidence deduplication, graph-only/vector-only/combined results, citation IDs and rejection, no/insufficient evidence, budgets, provider/retriever failures, and real Neo4j source mapping. All external AI calls are mocked; no paid API call is required. Integration tests still require a fresh isolated database as described above, including the existing mock embedding index configuration.

Milestone 7 adds the frontend described below. Authentication, external reranking/vector databases, unrestricted Text-to-Cypher, and complex deployment infrastructure remain excluded.


## Milestone 7: Knowledge Assistant frontend

`frontend/` uses Next.js App Router, TypeScript, Tailwind CSS, and Cytoscape.js. A responsive sidebar links to **Chat**, **Documents**, and **Knowledge Graph**. Components use semantic HTML and small inline SVG icons; there is no additional UI component library. Next.js is pinned to 16.3.8, and the lockfile pins dependencies. See the official [Next.js installation guide](https://nextjs.org/docs/app/getting-started/installation), [Tailwind Next.js setup](https://tailwindcss.com/docs/installation/framework-guides/nextjs), and [Cytoscape API](https://js.cytoscape.org/).

### Local frontend setup

With Node.js 24.15+ installed, from the repository root:

```bash
cp frontend/.env.example frontend/.env.local
cd frontend
npm ci
npm run dev
```

Open http://localhost:3000. Start the backend and Neo4j using the instructions above; alternatively `docker compose up --build -d --wait neo4j backend` starts them while the frontend runs locally. The scripts use Next.js's supported Webpack option for compatibility with restricted local worker environments. For a local production run use `npm run build`, then `npm run start`.

Environment settings in **frontend/.env.local**:

| Setting | Example | Purpose |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | Absolute browser-reachable backend URL, without query/fragment/credentials. Required by the API client. |
| `NEXT_PUBLIC_MAX_FILE_SIZE` | `10485760` | Client file-size limit in bytes; match backend `MAX_FILE_SIZE`. Server validation is authoritative. |

These variables are public browser settings, inlined at build time. **Never put OPENAI_API_KEY or Neo4j credentials in the frontend.** Changes require restarting the development server or rebuilding production. The root `.env` configures Compose; Compose uses its `NEXT_PUBLIC_API_BASE_URL` as a frontend build argument and passes backend `MAX_FILE_SIZE` as the frontend size limit. Use a browser-reachable address, not `http://backend:8000`, which resolves only within Docker. Backend `CORS_ORIGINS` must include the exact frontend origin; the default is `["http://localhost:3000"]`. Compose now passes this setting through. For a frontend on `http://127.0.0.1:3000`, include that separate origin.

### Run the complete application with Docker

Set the root `.env` as described above. For the full AI demo configure a valid server-side key and compatible structured-output model, embedding model/dimensions, and enable:

```dotenv
LLM_EXTRACTION_ENABLED=true
EMBEDDING_ENABLED=true
GRAPH_RETRIEVAL_ENABLED=true
GRAPHRAG_ENABLED=true
```

Then run:

```bash
docker compose up --build -d --wait
```

Open http://localhost:3000. The frontend runs a non-root standalone Next.js server with a page health check; the backend and Neo4j retain their existing health checks. All published ports bind to localhost. `docker compose down` preserves Neo4j data. Disabled AI stages still allow text upload, but the UI displays disabled stages and ask returns the backend's explicit error. Real ingestion/answering calls your configured AI provider; routine tests do not.

### Document upload flow

Open **Documents**, drag in one PDF/DOCX/TXT or select it with **Browse files**, then choose **Upload document**. The browser checks extension, empty files, and size before the existing upload endpoint performs authoritative validation. The UI shows **Uploading** during HTTP transfer and **Processing** after the browser reports transfer completion while the synchronous backend request remains pending. It does not fabricate percentages or claim per-stage progress that the API does not expose. Success shows the actual document, chunk count, and separate extraction/embedding statuses. Partial, failed, and disabled stages remain visible, including sanitized backend chunk error codes.

The Documents list is **uploads this browser session**, held in React memory across client navigation. It resets on reload and does not list all stored documents: the backend has no document-listing endpoint. Original document binaries remain unretained as before. Network/timeout failure is not a successful upload; since backend processing may continue after disconnect, inspect Neo4j before repeating an uncertain upload.

### GraphRAG chat and citations

Open **Chat**, enter a question, and submit with the button or Enter (Shift+Enter adds a line). The centralized client calls `POST /api/graphrag/ask`. Each submission is an independent question, matching the existing stateless backend; earlier displayed turns are not sent as conversation context. The UI displays the question, loading/error state, grounded answer, insufficiency badge, backend citation IDs, and retrieval counts/truncation. Failed requests restore the question for another attempt and never create a fake answer.

Click a bracketed citation to expand and scroll to its supporting source. Document cards show filename, available page number, the backend's **zero-based chunk index**, excerpt, document ID, and chunk ID. Shortened excerpts are labeled. Graph cards preserve relationship directions and distinguish graph facts from document-backed facts; supporting document source cards are shown only if supplied. Citation IDs are scoped to their answer because S1 in one response can refer to a different chunk in another. The frontend never generates citations and renders model/document strings as plain text, never HTML.

### Read-only graph visualization API

`GET /api/graph?node_limit=100&edge_limit=200` returns:

```json
{
  "nodes": [{"id":"entity-id","label":"Payment Service","type":"SERVICE","description":null}],
  "edges": [{"id":"stable-display-edge-id","source":"entity-id","target":"other-entity-id","type":"USES"}],
  "truncated": false
}
```

Default limits are 100 nodes/200 edges; accepted ranges are 1–200 nodes and 1–400 edges. The snapshot selects Entity nodes in stable ID order, then only relationships whose endpoints are in that snapshot and whose types belong to the existing configured domain allowlist. HAS_CHUNK and MENTIONS are explicitly excluded. Facts from known incomplete extraction documents are hidden, consistent with graph retrieval; unknown-source graph facts remain eligible. Nodes can appear isolated when they have no eligible edges in this snapshot.

Parallel facts from different supporting chunks collapse to one directed semantic display edge with a deterministic UUID. Original Neo4j fact/provenance edges are unchanged, and full citation provenance still comes from the existing retrieval/ask APIs. Results use one managed read transaction with parameterized Cypher, read access, database timeout, and elapsed-time bound. A truncation flag indicates the node or edge limit hid data. The snapshot is bounded, not a complete graph export or relevance-ranked search. No arbitrary Cypher or database credentials are exposed.

On **Knowledge Graph**, the client renders actual API nodes/edges using Cytoscape, with type colors and a legend. Drag to pan, scroll or use +/- to zoom, and choose **Fit graph** to reset the view. Click a node to inspect its name, type, optional description, and relationships in this snapshot. **Browse entities** provides keyboard-accessible selection. **Refresh graph** requests fresh Neo4j data after another upload. Empty results and backend errors have separate states.

### Frontend checks

```bash
cd frontend
npm run test
npm run typecheck
npm run lint
npm run format:check
npm run build
```

Tests mock backend requests and cover API configuration/errors, chat submission/loading/failure, answers/citations/insufficiency, graph-only citation rendering, upload validation/status/error handling, session history, graph response mapping, graph details, empty states, and refresh retries. Backend tests add graph snapshot mapping, limits, filtering, stable display IDs, error handling, API validation, and a real Neo4j read-only/filtering test. Run the complete backend suite as described above; enable the isolated Neo4j tests using the existing integration instructions. No paid AI calls are required.

### Complete manual demo

1. Start the full stack with all four AI stages enabled, correct credentials/model/dimensions, and the frontend pointing at the backend. Confirm `/health/ready` returns 200. Use an empty demo database or a database already compatible with the configured embedding model.
2. Create `sample.pdf` containing: **Platform Team manages Payment Service. Payment Service uses Redis for caching. Redis is hosted on AWS ElastiCache.** You may also use `docs/examples/graphrag-sample.txt`; the upload flow supports both. A three-page PDF with one sentence per page gives three separate source chunks/pages for a clearer citation demo.
3. In **Documents**, upload the file. Wait for the response and verify text/chunk storage plus **extraction: completed** and **embeddings: completed**. Failed/disabled stages are not a finished AI ingestion.
4. Open **Knowledge Graph**. Confirm MANAGES, USES, and HOSTED_ON connect Platform Team, Payment Service, Redis, and AWS ElastiCache. Select Redis and inspect its type/description and directed connections. Try pan, zoom, and Fit graph.
5. Open **Chat**. Ask **Which cloud service hosts the technology used by the service managed by Platform Team?** Confirm the supported answer identifies AWS ElastiCache and includes backend citations.
6. Click each source citation. Verify filename, available page, chunk index, and excerpt. A short TXT may put all three facts in one chunk and legitimately produce one S citation; do not require two/three citations when only one source chunk is needed.
7. Verify a document source in Neo4j Browser using the IDs shown in its expanded card:

```cypher
:param document_id => 'document-id-from-the-source-card';
:param chunk_id => 'chunk-id-from-the-source-card';
MATCH (d:Document {id:$document_id})-[:HAS_CHUNK]->(c:Chunk {id:$chunk_id})
RETURN d.filename, c.text, c.page_number, c.chunk_index, size(c.embedding) AS dimensions;
```

8. Ask **Who is the CEO of Payment Service?** With only the sample evidence, verify the insufficient-evidence response and absence of invented sources. Grounding/citation validity is tested, but live-model semantic accuracy still requires this manual evaluation.
9. Test an unsupported or empty file and stop/restart the backend to verify upload/chat/graph error handling. A failed request must not produce a fake success or fabricated graph.

### Screenshots

Browser verification captures are in `docs/screenshots/`. They show real backend/Neo4j operations against an isolated test database with **mocked AI providers**; they are interface demonstrations, not a live-model quality evaluation. Replace or add final MCA demo screenshots after configuring the real provider:

- [Documents upload and completed stage metadata](screenshots/documents-upload.jpg).
- [Knowledge Graph with the sample domain relationships and selected node](screenshots/knowledge-graph.jpg).
- [GraphRAG answer with expanded source citations](screenshots/chat-citations.jpg).
- [Insufficient-evidence response](screenshots/insufficient-evidence.jpg) and [a narrow mobile layout](screenshots/mobile-documents.jpg).

Milestone 7 stops here: no authentication, registration, payments, admin system, external vector database/reranker, unrestricted Text-to-Cypher, or complex deployment infrastructure.

## Milestone 8: evaluation and test-case reports

The evaluation CLI lives in `backend/src/kg_assistant/evaluation/`. It compares an **evaluation-only Vector RAG baseline** with the **production GraphRAGService**. Both use the same vector retriever, answer provider, grounded prompt, validation, top-K, model settings, retries, and context limits. The baseline supplies only vector-retrieved text; it never calls graph retrieval. Production APIs and frontend behavior remain unchanged.

### Dataset and metrics

`evaluation/dataset.json` contains eight public synthetic questions across factual, semantic, relationship, multi-hop, and insufficient-evidence categories. The six supporting documents are in `evaluation/corpus/`. Add cases using the existing JSON schema; IDs must be unique. `expected_entities` describes names expected in the answer; `expected_anchors` separately describes query resolution. `expected_path` is an ordered list of directed `{source, type, target}` relationships.

Supporting sources can be annotated with an exact `document_id`/`chunk_id` pair, or a `filename`/verbatim `quote` pair, optionally narrowed by page and chunk index. Resolution is read-only. Missing or ambiguous matches produce **N/A**, never an invented match. Uploading the same filename/content twice makes filename/quote selectors ambiguous; use exact IDs or an isolated corpus. Mark `sources_complete=true` only when the list exhaustively describes relevant supporting chunks.

- Recall@K = distinct relevant returned chunks / distinct annotated supporting chunks. This measures the **vector branch** in both modes; GraphRAG does not replace that branch.
- Precision@K = distinct relevant returned chunks / requested K; missing positions count as non-relevant. It is calculated only for complete source annotations. Duplicate chunks count once.
- Exact/normalized answer match compare the entire answer after removing citation markers; normalization folds Unicode/case, punctuation, and whitespace. Correct longer explanations may score poorly against short reference answers. Expected entity coverage is a separate name-matching proxy, not semantic accuracy.
- Insufficient-evidence correctness compares the explicit response flag with annotated ground truth.
- Graph metrics check resolved anchor names, a contiguous directed expected path, relationship coverage, and retrieval of that complete hop chain. Baseline graph metrics are N/A.
- Citation metrics validate supplied IDs and metadata, verify document/chunk existence and their HAS_CHUNK link, and compare sources with supplied evidence. They do not measure whether a claim semantically follows from an excerpt. Citation validity is N/A for citation-free insufficient answers.

Errors are retained per question, with sanitized codes. Summary rates show measured/total denominators; missing annotations and failed requests cannot disappear into an unqualified accuracy claim. The runner saves full raw responses, retrieved chunks, graph paths, fused context, provenance, metrics, and measured timings. Retrieval timing includes embedding/index checks or anchor extraction/traversal; total answer timing excludes evaluation-only annotation/citation audits. Mode order alternates across questions/repeats; caches are not forcibly reset.

### Run deterministic evaluation without paid APIs

From the repository root, after installing backend dependencies:

```bash
uv run --project backend --locked python -m kg_assistant.evaluation.run --mode mock
# Optional repeat/sensitivity run; use a separate output directory:
uv run --project backend --locked python -m kg_assistant.evaluation.run \
  --mode mock --top-k 1 --repeats 3 --output-dir evaluation/runs/mock-top1
```

Default outputs: `evaluation/results.json` and `evaluation/report.md`. The CLI exits 1 if any evaluation request failed, while retaining its raw error record; dataset/configuration failures exit 2. The default scripted embedding/LLM/database test doubles verify the harness and production service composition. **Their scores and latency do not establish real-model quality, Neo4j performance, or an empirical GraphRAG improvement. Live-provider evaluation: Not evaluated yet.** No token or monetary values are invented.

### Real-provider manual evaluation

1. Use a dedicated application Neo4j database compatible with your configured embedding model/dimensions. Do not use the integration-test database, which deliberately retains a three-dimensional mock-model index.
2. Configure the root `.env` as described in milestones 3–6: actual credentials/model names and `LLM_EXTRACTION_ENABLED`, `EMBEDDING_ENABLED`, `GRAPH_RETRIEVAL_ENABLED`, and `GRAPHRAG_ENABLED` all true. Start the backend and Neo4j using the existing setup instructions. The live runner uses these same settings.
3. Upload the public corpus through the real ingestion API, once per file:

   ```bash
   for file in evaluation/corpus/*.txt; do
     curl --fail-with-body -F "file=@$file" http://localhost:8000/api/documents/upload
   done
   ```

   Verify every response reports completed extraction and embeddings. Inspect chunks, facts, and the vector index using the earlier README Cypher examples. Real extraction is nondeterministic: review the generated facts before interpreting evaluation scores.
4. Run the existing vector-search, graph-search, and GraphRAG ask endpoints for Q005, then the insufficient-evidence question Q006. Confirm source IDs correspond to actual chunks; do not infer a successful test from these instructions.
5. Execute the comparison:

   ```bash
   uv run --project backend --locked python -m kg_assistant.evaluation.run \
     --mode live --dataset evaluation/dataset.json --top-k 5 --repeats 3
   ```

   Live mode calls the configured paid providers against existing Neo4j data. It does not upload documents or rewrite production retrieval. It uses existing vector-index initialization/compatibility checks. Outputs default to an ignored timestamped `evaluation/runs/` directory because they may contain sensitive evidence. Inspect request errors and annotation coverage before reviewing the table.
6. Review each answer and citation manually. Expand the dataset with independently annotated held-out questions before making any comparative quality claim; the tiny sample alone cannot support statistical conclusions.

Optional usage observers retain actual OpenAI Responses `input_tokens`, `output_tokens`, and `total_tokens` as prompt/completion/total metadata. Query extraction and answer generation are tracked separately, including retries. Unknown or partially observed totals remain null; embedding/ingestion tokens are outside this LLM total. Pricing is not assumed and monetary cost is not calculated. See the [official Responses API usage reference](https://developers.openai.com/api/reference/typescript/resources/beta/subresources/responses/methods/create).

### Execute automated checks and generate the MCA report

Existing backend tests cover extraction/chunking, ingestion transactions/provenance, embeddings, vector retrieval, bounded/cyclic graph retrieval, context fusion, grounded answers, citations, and failures. New evaluation tests cover metric denominators, missing annotations, baseline isolation, directed paths, source audits, token accounting, limits, failure records, and report generation. The new real-Neo4j evaluation E2E uploads the six corpus documents, runs both answer modes, verifies a three-hop path and citations, and tests insufficient evidence; AI providers are mocked. Frontend tests cover upload, chat, citations, graph data/interaction, loading, API errors, and upload transport timeout.

Run from the repository root:

```bash
# Unit tests; no Neo4j or paid API calls:
uv run --project backend --locked pytest backend/tests --ignore=backend/tests/integration
uv run --project backend --locked ruff check backend
uv run --project backend --locked ruff format backend --check

# Full backend suite: first export isolated Neo4j settings as documented above.
KG_RUN_NEO4J_TESTS=1 uv run --project backend --locked pytest backend/tests \
  --junitxml=evaluation/test-results/backend.xml

cd frontend
npm ci
npm run test -- --reporter=default --reporter=junit \
  --outputFile.junit=../evaluation/test-results/frontend.xml
npm run lint
npm run typecheck
npm run format:check
npm run build
cd ..

uv run --project backend --locked python -m kg_assistant.evaluation.test_report
```

For just integration/E2E tests, use `KG_RUN_NEO4J_TESTS=1 uv run --project backend --locked pytest backend/tests/integration`. Tests use an isolated database and clean up their documents/chunks/facts; shared entities, constraints, and the mock embedding index remain. Run the full backend command above to generate the complete report.

`evaluation/test-cases.md` and `.json` are generated from actual pytest/Vitest JUnit outcomes. Every row includes Test ID, module, scenario, input, expected result, actual result, and status, plus automation identity/duration. Source JUnit files and SHA-256 fingerprints permit auditing. Failures/errors/skips are preserved; missing result files cannot generate PASS entries. Expected-result descriptions come from `evaluation/test-catalog.json` and the named automated assertions; actual results come from the runners. Use these reports for MCA Review-II/final documentation, with the mock/live distinction retained. Current execution evidence is recorded in `docs/milestone8-verification.md`.

## Citation format troubleshooting

If GraphRAG returns answer_invalid_citation, the generated answer failed strict source validation. A supported answer must include literal inline markers such as [S1] and list the same bare IDs in citations, once each in first-appearance order. The prompt and GroundedAnswer field descriptions explicitly require this format and include formatting-only examples. The examples do not supply facts. Unknown IDs, missing inline citations and mismatched lists remain rejected; repeated failure returns 502 rather than an unsupported answer. Provider authentication errors are separate and should be fixed in private environment configuration.

For missing facts, including an explicit statement that a founder is not documented, the model must set insufficient_evidence=true. Such responses are canonicalized before validating discarded citation content: the complete original answer and all source IDs are removed, so no unsupported claim survives. Supported answers retain strict citation validation. OpenAI retries receive explicit citation-validation feedback rather than repeating identical instructions. Optional provider feedback is reused by the evaluation wrapper, with retry usage still counted.
