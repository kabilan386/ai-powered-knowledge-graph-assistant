# Final project implementation status

Statuses describe code/tests, not documentation aspirations. Milestone 9 is the final authorized scope. The system is implemented for a local MCA demonstration; it is not an authenticated public service.

| Major feature | Status | Actual scope / evidence |
|---|---|---|
| FastAPI/config/lifespan/DI/health | IMPLEMENTED | Async driver/provider lifecycles, Pydantic settings, liveness/readiness, regression tests |
| PDF/DOCX/TXT upload/extraction/chunking | IMPLEMENTED | Synchronous upload, pages where available, limits/metadata; real-Neo4j upload tests |
| Upload security checks | IMPLEMENTED | Transport/file/text/DOCX-expansion/chunk limits, safe basenames/control rejection, file cleanup; regression tests |
| Structured entity and relationship extraction | IMPLEMENTED | Configured OpenAI adapter, schema/type/reference/quote validation and retries; mocked extraction tests |
| Entity normalization | IMPLEMENTED | NFKC/case/whitespace, composite type/name identity, stable IDs |
| Context-aware aliases/homonyms | NOT IMPLEMENTED | Exact normalization only |
| Neo4j graph/provenance/persistence recovery | IMPLEMENTED | Document/Chunk/Entity/fact model, constraints, leases, per-chunk atomic writes, retry states |
| Embeddings/vector index/search/backfill | IMPLEMENTED | Chunk-only cosine vectors, configurable dimensions/model fingerprint, guarded missing-vector generation |
| Multi-hop graph retrieval | IMPLEMENTED | Grounded anchors, existing resolution, read-only bounded BFS, directions/ranking/evidence |
| Hybrid context and grounded answers | IMPLEMENTED | Both retrievers, verified dedupe/budgets, structured generation/citation checks, insufficiency |
| Source citation presentation | IMPLEMENTED | Backend S/G mapping and real excerpts; frontend expansion and provenance distinction |
| Frontend document/chat/graph dashboard | IMPLEMENTED | Next.js/Tailwind/Cytoscape, actual APIs, responsive states and mocked UI tests |
| Document listing/history persistence | PARTIALLY IMPLEMENTED | Current browser-session upload history only; no persistent listing API |
| Docker local runtime | IMPLEMENTED | Non-root applications, three services, loopback ports, health checks and persistent Neo4j volume |
| Public production operations/security | PARTIALLY IMPLEMENTED | Scoped validation/log/error/CORS controls; no auth, quotas, ingress TLS, full parser isolation, backup automation or penetration test |
| Deterministic evaluation/MCA reports | IMPLEMENTED | Paired baseline/production hybrid, annotations/metrics/N/A/timings/optional usage, actual JUnit report |
| Real-provider comparative quality evaluation | NOT IMPLEMENTED | Not evaluated yet; scripted metrics are framework checks only |
| Automated full pipeline E2E | IMPLEMENTED | Real Neo4j upload-to-grounded-answer and source checks with mocked AI |
| Final live-provider full browser E2E | NOT IMPLEMENTED | User-run procedure supplied; provider startup/readiness is not paid-call quality verification |
| Final architecture/schema/API/MCA/demo documentation | IMPLEMENTED | Actual contracts/schema, Mermaid and synthetic sample; no fabricated screenshots/results |
| Durable ingestion workers / OCR | NOT IMPLEMENTED | Synchronous processing; image-only PDFs unsupported |
| Auth/users/payments/admin | NOT IMPLEMENTED | Outside authorized scope |
| External reranker/vector database/arbitrary Cypher | NOT IMPLEMENTED | Intentionally absent; Neo4j remains sole DB |

[Final verification](milestone9-verification.md) records executed outcomes. Existing screenshots are historical M7 real-Neo4j/mock-AI captures. Model API access, billing and live-answer correctness are not implied by a healthy container. User-uploaded private documents remain in the local database; live report artifacts are ignored by default.
