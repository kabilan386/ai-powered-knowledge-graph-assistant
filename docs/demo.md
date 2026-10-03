# MCA demonstration procedure

This is a **manual procedure**, not a record of executed live-provider PASS results. The sample is synthetic and contains no credentials or private information. Automated real-Neo4j/mock-AI E2E execution is separately recorded in the test reports. Historical screenshots show the earlier mocked-provider demonstration.

## Start and configure

1. From the repository root, copy `.env.example` to `.env` only if `.env` does not already exist. Keep existing credentials. Set a local Neo4j password and actual OpenAI key/structured-output model, plus compatible embedding model/dimensions.
2. Set LLM_EXTRACTION_ENABLED, EMBEDDING_ENABLED, GRAPH_RETRIEVAL_ENABLED, and GRAPHRAG_ENABLED to true. Default settings leave AI disabled so the dashboard/upload can start without a paid provider.
3. Run `docker compose up --build -d --wait`. Open http://localhost:3000, http://localhost:8000/docs, and http://localhost:7474. Confirm `docker compose ps` is healthy and `/health/ready` reports Neo4j up. Readiness does not validate your API key.
4. Use a database with the configured embedding fingerprint. Integration-test databases retain a mock three-dimensional index and must not be used for this real-provider demonstration.

## Upload and inspect

5. Open Documents and select `docs/demo/platform-services.txt` using the file picker or drag/drop, then upload. The UI shows actual uploading/processing phases; it does not invent progress percentages.
6. Verify the response reports completed embeddings and extraction. Copy the document ID. A partial/failed stage is not a successful AI demonstration: inspect sanitized errors, use `/api/documents/{id}/extract` to retry graph extraction or `/api/embeddings/backfill` for missing vectors. Do not blindly upload duplicate copies.
7. In Neo4j Browser inspect Document-HAS_CHUNK-Chunk, chunk embedding dimensions, and MENTIONS/domain facts using [database queries](mca/02-database-design.md). This TXT has no page number. With default 1000-character windows it normally forms one chunk; smaller configured windows may yield more.
8. Open Knowledge Graph and refresh. Inspect Platform Team → MANAGES → Payment Service → USES → Redis → HOSTED_ON → AWS ElastiCache. Click entities, inspect type/description, use zoom/pan/fit and the legend. Actual extraction may vary; inspect facts rather than assuming the illustration exists.

## Ask and inspect citations

9. Open Chat and ask the semantic question: “What caching solution does the payment application use?” Inspect the actual answer and source excerpt for Redis.
10. Ask the relationship question: “Which service is managed by Platform Team?” Inspect evidence supporting Payment Service.
11. Ask the two-hop question: “What technology is used by the service managed by Platform Team?”
12. Ask the three-hop question: “Which cloud service hosts the technology used by the service managed by Platform Team?” Inspect the retrieved chain and evidence for AWS ElastiCache. GraphRAG must run both retrieval branches; use `/api/retrieval/vector-search` and `/api/retrieval/graph-search` in Swagger to inspect each separately if desired.
13. Expand citations. S IDs identify actual source chunks; G IDs identify graph paths. Copy document/chunk IDs from the API response and verify HAS_CHUNK and stored text in Browser. A graph-only citation must not show an invented document. Longer explanations need actual supported citations, not frontend-generated IDs.
14. Ask “Who founded Payment Service?” The sample provides no founder fact. Verify the actual response flags insufficient_evidence and has no citations/sources; do not count an invented founder answer as a successful demonstration.

## Evaluation and troubleshooting

For comparable live evaluation, upload the **six separate** `evaluation/corpus/*.txt` files once into an isolated corpus and run the documented live CLI. The bundled evaluation dataset's filename/quote selectors do not target the combined demo TXT. Default scripted evaluation makes no API calls and is only framework verification.

If requests fail, inspect `docker compose logs --tail=100 backend` and sanitized response codes. Missing AI flags return 503; invalid credentials/provider responses do not become fake answers. Chat has a 150-second browser deadline and synchronous uploads a five-minute deadline; processing can outlive a closed browser request. Verify source status before retrying. Graphs may be truncated by explicit bounds and document session history resets on page reload.

Stop with `docker compose stop`; resume with `docker compose up -d --wait`. `docker compose down` removes containers/network while retaining the named data volume. Leave `.env` private; no screenshot or report should reveal its secrets.

## Larger corpus test

For a many-chunk test, upload [large-service-handbook.txt](demo/large-service-handbook.txt). At default 1000/200 chunk settings it contains 66 chunks across fictional service chapters. [Question annotations](demo/large-service-handbook-questions.md) cover factual, semantic, relationship, distinct three-hop and unsupported queries. These are expected facts, not fabricated execution results. This larger synchronous upload can take several minutes and consumes provider calls; inspect statuses before repeating a timed-out upload.
