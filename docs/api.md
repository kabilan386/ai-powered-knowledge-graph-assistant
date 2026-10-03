# Implemented API reference

Base URL is configured, defaulting locally to http://localhost:8000. Interactive request/response schemas are served at `/docs`; machine-readable contracts are at `/openapi.json`. The application has no authentication. Do not expose this API publicly as a protected service. This reference lists only registered application routes; no listing/delete/users/raw-Cypher/Vector-RAG-answer endpoint exists.

Unless noted otherwise, success is 200. Service errors are `{"error":{"code":"...","message":"..."}}`; unexpected exceptions are sanitized 500 `internal_error`. Pydantic/FastAPI validation uses standard 422 `detail` entries. Responses receive X-Request-ID. CORS permits configured origins and GET/POST with Content-Type; default origin is http://localhost:3000. CORS is a browser policy, not authorization.

| Method / route | Request | Response contract | Validation / errors |
|---|---|---|---|
| GET /health/live | None | HealthResponse: status, optional neo4j | Liveness only; no provider/DB verification |
| GET /health/ready | None | `{"status":"ok","neo4j":"up"}` | 503 with unavailable/down when Neo4j check fails |
| POST /api/documents/upload | Multipart `file`: PDF/DOCX/UTF-8 TXT | **201** UploadResponse: document `{id,filename,file_type,created_at,extraction_status}`, chunk_count, extraction summary, embeddings summary | 400 empty file/bad filename; 415 unsupported extension; 413 file/body/expansion/text/chunk limits; 422 corrupt/encrypted/no-text/non-UTF-8; 503 DB/config errors; embedding-space incompatibility 409; missing file 422 |
| GET /api/documents/{document_id}/extraction | Path document_id | ExtractionSummary `{status,total,completed,failed,errors:[{chunk_id,code}]}` | 404 missing document; 503 database failure; actual disabled/partial/failed statuses are preserved |
| POST /api/documents/{document_id}/extract | Path document_id, no JSON required | ExtractionSummary; retries chunks not completed | 503 extraction disabled/unconfigured; 404 missing; 409 active/superseded run; per-chunk failures recorded, not silently ignored |
| POST /api/embeddings/backfill | BackfillRequest `{document_id?:string,limit?:integer}` | BackfillResponse `{processed,updated,skipped,remaining,errors:[{chunk_id,code}]}` | limit defaults 100, range 1–1000; ID 1–128 chars; 404 missing; 409 incompatible model/index; 503 disabled/storage; provider failures retained per chunk |
| POST /api/retrieval/vector-search | `{query:string,top_k?:integer}` | VectorSearchResponse `{query,results:[{chunk_id,text,score,document_id,filename,page_number,chunk_index}]}` | Query stripped, 1–24000 chars; strict top_k default 5, range 1–100 and configured VECTOR_MAX_TOP_K (default 50); 409 incompatible index/model; 503 disabled/provider/storage; provider dimension/format failures handled explicitly |
| POST /api/retrieval/graph-search | `{query:string,max_hops?:integer}` | GraphSearchResponse `{query,anchors,unresolved_entities,paths,status,truncated}` | Query stripped 1–4000; strict depth 1–5, cannot exceed configured maximum; 503 disabled/query-provider/DB; unresolved or no-path cases are 200 with explicit status and empty paths |
| POST /api/graphrag/ask | `{question:string}` | AskResponse `{question,answer,citations,sources,retrieval,insufficient_evidence}` | Question stripped 1–4000; extra fields rejected; 503 disabled/retrieval/storage; 502 invalid/unavailable grounded generation; request timeout 504 |
| GET /api/graph | Optional query node_limit, edge_limit | GraphResponse `{nodes:[{id,label,type,description}],edges:[{id,source,target,type}],truncated}` | Defaults 100 nodes/200 edges; ranges 1–200/1–400; Entity/domain edges only; 503 storage; no-data is a legitimate empty response |

Upload request transport is limited before parsing to MAX_FILE_SIZE + 64 KiB multipart overhead. Other POST/PUT/PATCH request bodies are limited to 128 KiB. Exceeding the transport bound returns 413 `request_too_large`; invalid/negative Content-Length returns 400 `invalid_content_length`. Actual uploaded file bytes still cannot exceed MAX_FILE_SIZE. No caller can run arbitrary Cypher through any route.

## Requests

```bash
curl --fail-with-body -F 'file=@docs/demo/platform-services.txt' \
  http://localhost:8000/api/documents/upload
curl --fail-with-body -H 'Content-Type: application/json' \
  -d '{"query":"What caching solution does the payment application use?","top_k":5}' \
  http://localhost:8000/api/retrieval/vector-search
curl --fail-with-body -H 'Content-Type: application/json' \
  -d '{"query":"Which cloud service hosts the technology used by the service managed by Platform Team?","max_hops":3}' \
  http://localhost:8000/api/retrieval/graph-search
curl --fail-with-body -H 'Content-Type: application/json' \
  -d '{"question":"Which cloud service hosts the technology used by the service managed by Platform Team?"}' \
  http://localhost:8000/api/graphrag/ask
curl --fail-with-body 'http://localhost:8000/api/graph?node_limit=100&edge_limit=200'
```

These are invocation examples, not fabricated successful responses. Enable/configure providers and ingest evidence first. Copy a real document ID for status/recovery calls:

```bash
curl --fail-with-body http://localhost:8000/api/documents/YOUR_DOCUMENT_ID/extraction
curl --fail-with-body -X POST http://localhost:8000/api/documents/YOUR_DOCUMENT_ID/extract
curl --fail-with-body -H 'Content-Type: application/json' \
  -d '{"document_id":"YOUR_DOCUMENT_ID","limit":100}' \
  http://localhost:8000/api/embeddings/backfill
```

## Path and citation response details

Graph anchors/nodes contain id, name, type. Each path contains hop_count, nodes, relationships, edges, score. Edges preserve source_id/target_id, type, evidence, and evidence_truncated. Relationship evidence may include relationship_id, chunk_id, document_id, filename, page_number, chunk_index, evidence_quote; unavailable values stay null. Status is ok, no_anchors, unresolved_anchors, or no_paths. Truncation is explicit.

Sources have citation, kind=document/graph, optional document_id/chunk_id/filename/page_number/chunk_index/excerpt, excerpt_truncated, nodes, edges, supporting_citations. Text evidence uses S IDs, graph paths G IDs. Graph-only sources have no invented document metadata. Retrieval metadata includes raw/fused counts, character budget usage, settings used, graph status, truncation flags, and measured duration_ms. Canonical insufficient answers have no citations/sources. Neither score nor timing is a provider confidence estimate.

OpenAPI is authoritative for field types/defaults. [Generated contract](api-openapi.json) is an offline snapshot created from the actual app factory, not handwritten endpoint invention.
