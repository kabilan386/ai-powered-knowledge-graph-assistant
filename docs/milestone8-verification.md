# Milestone 8 executed verification

Implementation stops after Milestone 8. Neo4j remains the only database. Production ingestion, GraphRAG routes, and frontend components were preserved. Only optional, inactive-by-default token observers were added to existing LLM provider adapters.

## Actual checks

- Backend: 222 passed (208 unit tests, 14 real-Neo4j integration tests); zero failures/errors/skips. The integration suite used an isolated Neo4j 5.26.0 instance and mocked all external AI calls.
- Frontend: 26 passed in four Vitest files; zero failures/errors/skips.
- Ruff lint and format check: passed.
- Frontend ESLint, TypeScript, and Prettier checks: passed.
- Next.js production build: passed; static routes /, /chat, /documents, /graph generated.
- Existing Starlette TestClient/httpx deprecation warning remains; it did not fail tests.
- MCA report: 248 actual PASS rows generated from recorded pytest/Vitest JUnit files, with source hashes. No unexecuted manual test is marked PASS.

## Executed deterministic evaluation

Generated: 2026-10-03T05:54:10.783500+00:00. Run kind: `scripted_mock`. Eight paired questions, top-K 5, one repetition.

| Measured fixture proxy | Vector RAG | GraphRAG |
|---|---|---|
| normalized_answer_match | 85.7% (7/8 measured) | 100.0% (7/8 measured) |
| recall_at_k | 95.2% (7/8 measured) | 95.2% (7/8 measured) |
| insufficient_evidence_correct | 87.5% (8/8 measured) | 100.0% (8/8 measured) |
| citation_validity | 100.0% (6/8 measured) | 100.0% (7/8 measured) |

Both modes completed 8/8 requests without errors. The vector branch returns the same evidence in both modes; the three-hop fixture adds document-backed graph evidence in GraphRAG. Recorded per-question timings are measured with perf_counter and available in raw JSON. Missing provider token usage and monetary cost remain null.

**These scripted fixture measurements verify the evaluation framework, not real embedding/LLM accuracy, Neo4j performance, or an empirical improvement. Live-provider evaluation: Not evaluated yet.** The real-Neo4j E2E separately verifies actual database writes/retrieval/source audits with mocked AI, not model quality.

## Changed files

- `AGENTS.md`, `README.md`, `docs/implementation-plan.md`, `.gitignore`.
- `docs/milestone8-verification.md` (this execution record).
- `backend/src/kg_assistant/providers/answer.py`, `query_entities.py`; added `usage.py`.
- Added `backend/src/kg_assistant/evaluation/__init__.py`, `models.py`, `baseline.py`, `metrics.py`, `citations.py`, `repository.py`, `observations.py`, `runner.py`, `fixtures.py`, `run.py`, `report.py`, `test_report.py`.
- Added `backend/tests/test_evaluation.py`, `backend/tests/integration/test_evaluation_neo4j.py`.
- Extended `frontend/tests/api.test.ts` with an upload transport timeout test.
- Added `evaluation/dataset.json`, six `evaluation/corpus/*.txt` files, `evaluation/test-catalog.json`.
- Generated `evaluation/results.json`, `report.md`, `test-cases.json`, `test-cases.md`, `test-results/backend.xml`, `test-results/frontend.xml`.

## Reproduction and manual procedure

See README milestone 8 for unit/integration/frontend checks, CLI arguments, source annotations, metric limitations, real-provider uploads/evaluation, and report generation. Default mock CLI makes no paid API calls and requires no running database. Live outputs default to ignored evaluation/runs/ directories. Automated E2E uploads corpus documents through FastAPI, validates completed embeddings/extraction, runs both modes, checks the full three-hop path and source existence/linkage in Neo4j, verifies insufficient evidence, and cleans up its documents/facts.
