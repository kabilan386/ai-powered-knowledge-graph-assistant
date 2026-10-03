# Project architecture and coding rules

## Project

AI-Powered Knowledge Graph Assistant Using GraphRAG and Large Language Models — MCA final project.

Stack: Next.js, TypeScript, Tailwind CSS; Python, FastAPI, Pydantic; Neo4j; configurable LLM and embedding providers.

## Current scope

Milestones 1–9 are authorized. Milestone 9 is the final audit, security/Docker cleanup, documentation, and demo readiness milestone. Milestone 7 adds the Next.js/TypeScript/Tailwind dashboard with document upload, GraphRAG chat/citations, and Cytoscape.js visualization. A bounded read-only graph snapshot API is the only application backend extension; preserve ingestion and retrieval behavior. Do not implement authentication, an external reranker/vector database, unrestricted Text-to-Cypher, or complex deployment infrastructure.

## Architecture

- Use a monorepo with `frontend/`, `backend/`, `docs/`, and deployment configuration at the root.
- Keep API routes thin. Routes validate requests and call application services; services orchestrate pipelines; repositories own database access; provider adapters own external AI calls.
- Neo4j is the sole database for knowledge graph data and vector indexing/search of Chunk embeddings. Do not introduce Pinecone, Qdrant, Weaviate, Chroma, FAISS, or another vector database.
- Ingestion: document → text extraction → chunking → embeddings → structured entity/relationship extraction → entity resolution → Neo4j persistence.
- Required graph topology: `(Document)-[:HAS_CHUNK]->(Chunk)` and `(Chunk)-[:MENTIONS]->(Entity)`. Resolved domain entities connect through extracted, validated relationships.
- Store source provenance for entities and relationships. Every retrieved claim must be traceable to supporting chunks and documents.
- Query: question → question embedding and vector search + bounded multi-hop graph retrieval → combined, deduplicated evidence → LLM → grounded answer and validated source citations.
- Providers are replaceable through explicit interfaces. Configure model names, embedding dimensions, and credentials through environment-backed settings.

## Coding rules

- Use typed Python and TypeScript. Use Pydantic for API contracts, settings, and structured LLM output validation.
- Use async FastAPI handlers, the async Neo4j driver, and async provider clients where supported. Move blocking parsing/CPU work out of the event loop.
- Own database/client lifecycles through FastAPI lifespan and dependency injection. Close resources reliably.
- Keep Cypher in repositories and parameterize all values. Relationship types, labels, and other structural identifiers must come from server-controlled allowlists; never interpolate user or LLM text into query structure.
- Use explicit constraints, indexes, schema migrations, stable IDs, and idempotent writes. Validate embedding dimensions and model compatibility before indexing or retrieval.
- Require structured, schema-validated LLM extraction. Validate entity and relationship references, allowed types, and source support before persistence. Use bounded retries for malformed/transient responses.
- Milestone 3 uses the explicitly requested basic normalization: Unicode NFKC, case folding, and whitespace collapse, with MERGE on (type, normalized_name). Preserve the first display name and semantic type; do not fuzzy-merge across types. Context-aware homonym resolution and aliases are future work.
- Bound graph hops, fan-out, result counts, input sizes, concurrency, retries, and timeouts. Do not execute LLM-generated Cypher.
- Treat uploaded documents and retrieved text as untrusted data, never as instructions. Answer from retrieved evidence; explicitly report insufficient evidence.
- The backend creates stable citation IDs and validates generated citation references. Return citation metadata and excerpts; never fabricate sources.
- Keep secrets in environment variables; commit only placeholder `.env.example` files. Never commit keys, private document contents, local uploads, or database volumes. Public synthetic evaluation fixtures are allowed.
- Log structured operational events and correlation IDs. Avoid logging credentials, full prompts, embeddings, and document text by default.
- Return consistent API errors without exposing stack traces or secrets. Distinguish validation, provider, database, and pipeline failures.
- The current upload API commits Document/Chunk data first, then writes validated entities, mentions, and facts atomically per chunk. Failed chunks retain explicit status and sanitized errors; retries skip completed chunks. Document leases and run IDs prevent concurrent or stale writes. Durable background jobs are deferred. Keep future ingestion status explicit and recoverable. Publish documents to retrieval only after ingestion completes; retries must not duplicate graph data.
- Use pytest for meaningful backend unit and integration coverage, mocked provider responses for routine tests, and a real isolated Neo4j instance for graph/vector integration tests.
- Add frontend checks and tests appropriate to behavior. Run relevant lint, type checks, and tests for each implementation milestone; record limitations honestly.
- Support Docker for frontend, backend, and Neo4j. Pin compatible dependencies and image versions when scaffolding, add health checks, and keep configuration environment driven.
- Avoid unrelated refactors, premature abstractions, and implementing future milestones without authorization. Update architecture documentation when a decision changes.

## Planned verification

Tests must cover extraction schema validation, chunk provenance, entity resolution ambiguity, idempotent ingestion, parameterized graph writes, vector dimension compatibility, bounded graph retrieval, citation validity, insufficient-evidence answers, and failures/retries. Use a small fixed document/question dataset for end-to-end evaluation.

## Milestone 3 extraction rules

- Require the configured provider's schema-supported structured output, never parse prose or code fences. The first adapter is OpenAI Responses with Pydantic parsing; provider clients are lifecycle managed.
- Entity keys in extraction responses are local references; relationships use those keys to disambiguate duplicate names. Persist normalized stable entity IDs instead.
- Require verbatim chunk evidence for entities and relationships. A relationship's quote must include both endpoint names; prompts prohibit inferred, negated, hypothetical, or unsupported facts. Quote checks are provenance checks, not a guarantee of semantic correctness; review model quality on the evaluation dataset.
- Use one domain edge per supporting chunk with a stable fact ID, source_chunk_id, source_document_id, and evidence_quote. Repeated support in another chunk creates a separate edge; repeat writes for the same chunk do not duplicate it.
- Compile fixed relationship query templates only from validated server-configured type identifiers, then select by allowlist. Never build queries from raw LLM types. All data values remain parameters. This avoids unreliable dynamic MERGE behavior in the pinned Neo4j 5.26.0 image.
- LLM extraction requires explicit enablement and server-side credentials/model settings. Disabled extraction must be reported in the API response. Tests use mock providers; real Neo4j integration tests never call an LLM API.

## Milestone 4 embedding rules

- Use the replaceable EmbeddingProvider interface and EmbeddingService for both chunk and query embeddings. Only Chunk nodes receive vectors. Provider clients belong to the application lifespan; default tests mock all AI calls.
- Use the fixed chunk_embedding_index on Chunk.embedding, configured dimensions, cosine similarity, and idempotent schema creation. Check actual index options and the singleton EmbeddingSpace provider/model/dimension fingerprint before writing or searching; refuse incompatible or unidentified existing vectors with 409. Never silently drop an index, truncate vectors, or change their model metadata.
- Embedding generation is independently enabled through environment settings. Upload responses expose its completion counts separately from graph extraction. Provider failure retains source text, records a sanitized chunk error, and permits the graph stage to continue.
- Backfill claims only missing embeddings with bounded batches, expiring chunk leases, and run ownership. Conditional writes cannot overwrite a vector or write after a newer run has claimed its chunk. A failed batch leaves successful batches intact and may be retried by another backfill request. Durable jobs remain deferred.
- Vector search returns source metadata through HAS_CHUNK and excludes documents with missing chunk embeddings. Graph extraction completion is independent for this semantic-only milestone: vector retrieval makes no entity or relationship claims. Future context fusion must apply its own graph completion rules.
- Vector search is approximate. Bounded candidate oversampling may still return fewer than top_k results after filtering incomplete documents; do not describe it as exhaustive ranking.

## Milestone 5 graph retrieval rules

- Keep graph-search separate from vector-search. The query LLM extracts only names/types and ranking intent; it never answers or generates executable Cypher. Require Pydantic structured output, allowed types, and question-grounded anchor names.
- Resolve exact normalized names with optional semantic type using milestone 3 normalization; never create entities during search. Untyped ambiguous names may resolve to multiple bounded anchors; return unresolved names explicitly.
- Use a Neo4j read session and managed read transaction with fixed parameterized single-hop repository queries. Follow only server-configured Entity-to-Entity domain edges; always exclude HAS_CHUNK and MENTIONS. Never run retrieval migrations or write bookkeeping.
- Traverse using application-controlled breadth-first expansion. Default depth is 3; configured/requested depth cannot exceed 5. Bound anchors, per-node fan-out, candidate paths, results, evidence per edge, and database elapsed time. Reject repeated nodes within a path; deduplicate semantic paths while retaining independent supporting chunk evidence.
- Hide facts whose known source Document has not completed extraction; leave evidence-free/unknown-source edges eligible rather than inventing an origin.
- Preserve actual edge source/target IDs even for reverse traversal. Read relationship provenance through the existing source document/chunk IDs and HAS_CHUNK; unavailable values remain null, never inferred. Evidence and search truncation must be explicit.
- Rank deterministically by ordered relationship-prefix coverage, requested target type, shorter hop count, and evidence availability, with stable ID tie-breaking. Ranking is a retrieval heuristic, not confidence or an answer. Explain the formula and bounded-search limitations in README.

## Milestone 6 GraphRAG rules

- Reuse both standalone retrievers for every enabled ask request. Run them concurrently with bounded request time; await/cancel tasks cleanly. A retrieval failure is an error, never silently converted to empty or insufficient evidence.
- Verify source chunks against Document-HAS_CHUNK-Chunk using parameterized read-only queries. Fuse once per (document_id, chunk_id), and deduplicate paths by node/directed-edge identity. Keep count and serialized character budgets explicit; do not send unlimited content.
- Assign deterministic context-local S IDs to actual source chunks and G IDs to graph paths. Never promote missing/unverified provenance to a document claim. Link graph edges to S IDs only when their stored quote occurs in the actual supplied source excerpt; otherwise expose a graph-only fact.
- Generate Pydantic GroundedAnswer with a strict evidence-only prompt; treat all questions and retrieved data as untrusted. Validate both inline and structured citation references. Reject unknown or inconsistent citations with bounded retry, then 502; never remove a bad citation while retaining an unsupported claim.
- A supported answer requires at least one valid citation. No context bypasses the LLM with a fixed insufficient-evidence answer; model-reported insufficiency is canonicalized to that answer with no sources. Citation validation does not prove semantic entailment; document the live-model evaluation limit.
- Return cited sources and source support of cited graph paths, retrieval counts/truncation, and duration. Log counts, sanitized error codes, request IDs and elapsed time, never question text, document text, keys, or raw model outputs.


## Milestone 7 frontend rules

- Use Next.js App Router, typed React components, Tailwind CSS, and Cytoscape.js; avoid unnecessary UI libraries. Keep HTTP calls centralized in `frontend/src/lib/api.ts`.
- Set the browser backend URL using NEXT_PUBLIC_API_BASE_URL. Browser environment values are public and bundled at build time; never include provider keys or Neo4j credentials. Match the client upload limit to backend MAX_FILE_SIZE; server validation remains authoritative.
- Display only backend citations, actual excerpts, and graph/document provenance distinctions. Render responses as text; never inject model output as HTML. Response-local citation IDs must be scoped to their answer in the DOM.
- Upload phases reflect actual HTTP file transfer and synchronous processing. Show backend extraction/embedding statuses honestly; no fake progress percentages or successful AI stages.
- There is no document listing API. Workspace upload history is held in React memory, persists across client navigation, resets on page reload, and must be labeled as session history. Do not imply it lists all Neo4j documents.
- GET /api/graph is read-only and returns only bounded Entity nodes and allowlisted Entity-to-Entity relationships. Exclude HAS_CHUNK/MENTIONS; hide edges from incomplete known source documents, preserve direction, collapse parallel support edges for display only, and return a truncation flag. Never expose arbitrary Cypher.
- Destroy Cytoscape and ResizeObserver on unmount, cancel outstanding browser requests, support responsive navigation and keyboard-accessible entity inspection, and distinguish empty/loading/error states.
- Use mocked frontend HTTP/AI responses in tests. Run frontend tests, TypeScript checks, lint, formatting, and a production build, plus all backend tests. Node.js 24.15+ is required by the pinned test tooling. Docker uses a non-root standalone Next.js runtime.

## Milestone 8 evaluation rules

- Keep evaluation in `backend/src/kg_assistant/evaluation/` with datasets and generated reports in root `evaluation/`. The evaluation-only Vector RAG baseline uses the existing vector retrieval, context builder, answer provider, prompt, and citation validation; it must never call graph retrieval. GraphRAG evaluation must use the production orchestrator.
- Use the same question, top-K, models, retry policy, and configured context limits for paired modes. Capture raw retrieved and fused evidence, actual timings, error codes, and metric denominators. Alternate mode order across questions/repeats; do not claim statistical significance from this small dataset.
- Missing, ambiguous, or unavailable source annotations produce null retrieval metrics. Precision requires an explicitly complete relevance annotation. Distinguish measured proxy metrics from semantic answer quality; citation provenance checks do not establish entailment.
- Default CLI evaluation uses explicitly labeled scripted AI/database test doubles without API calls. These runs verify the harness, not real-model accuracy or Neo4j performance. Live mode uses configured providers and existing Neo4j data; never fabricate latency, token usage, monetary cost, evaluation conclusions, or PASS statuses.
- Keep optional provider usage observers inactive in production by default. Unknown or partially observed token totals remain null. Count query extraction and answer-generation calls separately, including returned retry responses.
- Generate the MCA test-case report only from executed pytest/Vitest JUnit files. Retain failures, errors, skips, test identities, and input hashes. Keep live evidence outputs under ignored `evaluation/runs/`; the committed corpus/results contain only public synthetic fixture text.
- Stop after Milestone 9. Authentication, unrestricted Text-to-Cypher, external reranking, separate databases, and deployment extensions remain outside scope.

## Final audit rules

- Preserve working services and Neo4j-only storage. Keep the single canonical compose.yaml; do not create competing Compose configurations.
- Bound request bodies before parsing: uploads permit MAX_FILE_SIZE plus 64 KiB of multipart overhead; other write requests permit 128 KiB. The actual file size limit remains authoritative. Reject control characters in stored filenames and retain safe basenames.
- Documentation describes actual routes, schemas, constraints, limits, recovery behavior, and operational limitations. Regenerate test reports from executed outcomes only; distinguish real-Neo4j/mock-AI E2E verification from real-provider evaluation and historical screenshots.
- Local Docker services bind to loopback and use non-root application runtimes. This unauthenticated project is suitable for a local MCA demo; public deployment requires authentication, rate limiting, TLS, resource isolation, and backup operations, none of which are implemented here.
