# Milestone 9 final verification

Executed on 2026-10-03. Milestone 9 is the final audit/security/Docker/documentation/demo milestone. Architecture and Neo4j-only persistence were retained.

## Actual results

| Check | Executed result |
|---|---|
| Pre-change backend baseline | 222 passed, including isolated Neo4j integration tests |
| Pre-change frontend baseline | 26 passed |
| Final backend suite | 231 passed: 217 unit and 14 real-Neo4j integration cases; no failures/errors/skips |
| Final frontend suite | 26 passed across four files |
| Ruff lint/format | Passed; 105 Python files formatted |
| Frontend ESLint / tsc / Prettier | Passed |
| Next.js production build | Passed; /, /chat, /documents, /graph static routes generated |
| Full Docker rebuild/start | Passed; frontend/backend/neo4j healthy |
| Scripted paired evaluation | 8 paired questions completed; actual results/report regenerated |
| MCA test-case report | 257 actual PASS rows from JUnit; source hashes retained |

One existing Starlette TestClient/httpx deprecation warning remains. The first restricted-sandbox unit attempt stalled at TestClient and was interrupted; the complete baseline and final runs with local socket permissions passed. No stalled attempt is reported as a successful execution.

Real-Neo4j/mock-AI E2E validates upload→text→chunks→embeddings→entities/facts→vector+graph retrieval→fusion→grounded answer/citations and source ownership. Frontend response rendering/interaction is separately tested with mocks. A new real-provider browser E2E/quality comparison has not been executed. Provider configuration was enabled at the user's request for manual sample testing; startup does not verify provider account billing/access. No paid API call was made during this verification.

## Genuine fixes

- Request-body transport limits now run before multipart spooling, including unknown/streamed Content-Length; actual file byte checks remain.
- Stored filenames reject control characters and retain safe basenames; UploadFile always closes.
- Compose now forwards documented Neo4j connection/health timeouts and APP_NAME.
- Docker contexts additionally exclude Git/log/test artifacts; existing non-root runtime/health/loopback/persistence configuration retained.
- Final README reorganized; detailed prior recovery/evaluation reference retained; actual schema/API/environment/architecture, MCA material, security scope, demo and feature statuses documented.

## Changed files

- Modified `AGENTS.md`, `README.md`, `.env.example`, `compose.yaml`, `backend/.dockerignore`, `frontend/.dockerignore`.
- Added `backend/src/kg_assistant/core/body_limit.py`; modified `main.py`, `services/documents.py`; added `backend/tests/test_security.py`.
- Added `docs/architecture.md`, `api.md`, `api-openapi.json`, `environment.md`, `security-review.md`, `demo.md`, `project-status.md`, `milestone9-verification.md`.
- Added `docs/implementation-guide.md` retaining the earlier detailed README; updated `docs/implementation-plan.md` to final scope.
- Added `docs/mca/01-system-design.md`, `02-database-design.md`, `03-implementation.md`, `04-testing.md`, `05-tools-technologies.md`.
- Added synthetic `docs/demo/platform-services.txt`.
- Updated `evaluation/test-catalog.json`; regenerated `results.json`, `report.md`, `test-cases.json`, `test-cases.md`, JUnit backend/frontend outputs; added the pre-change backend baseline JUnit.
- Private local `.env` changed only for user-authorized runtime setup: key retained, four AI flags enabled, compatible structured-output model configured. It is ignored, never included in documentation/build context, and its secret was not printed.

## Reproduction / boundaries

Start with `docker compose up --build -d --wait`; open http://localhost:3000. Follow docs/demo.md to upload the synthetic document, inspect completed stages/actual graph, ask semantic/relationship/multi-hop questions, expand citations, and test unsupported founder information. Root README has all test/evaluation commands and links to source/operational details.

No authentication, external database/reranker, unrestricted Cypher, durable workers, OCR or public deployment infrastructure was added. Security review is scoped source/configuration/regression work, not a CVE/image audit or penetration certification. Live-provider quality remains Not evaluated yet. Historical screenshots retain their original M7 mock-AI provenance. Stop after Milestone 9.

## Follow-up: live citation formatting diagnosis

A user-reported grounded-answer failure was traced to answer_invalid_citation: the provider listed valid supplied source IDs but omitted inline markers in answer. Strengthened prompts with formatting-only examples and explicit GroundedAnswer schema descriptions; strict validation still rejects uncited answers and unknown/mismatched IDs. GraphRAG/evaluation regression tests: 61 passed; Ruff passed; backend Docker rebuild/health passed.

A diagnostic using retrieved uploaded data was rejected by automatic approval review because it could export private content. The safe alternative used only bundled public synthetic FACTS and mock retrieval, never a Neo4j driver. The live configured answer provider then returned a validated supported multi-hop answer (citation_validity=true) and canonical insufficient evidence for the unsupported founder question (citation validity N/A). These two public formatting checks are not a full live dataset comparison or private-document E2E. No private source text or credentials were printed or sent by that diagnostic.

## Follow-up: unsupported Experiment Service founder

Clarified that an explicit statement that a requested fact is not documented requires insufficient evidence. Insufficient responses are replaced entirely with the canonical message and no citations before validating discarded content. Supported answers retain strict citation validation; retries receive fixed validation feedback, including through evaluation observers.

Executed GraphRAG/evaluation regression tests: 64 passed. Ruff lint/format checks passed; rebuilt backend is healthy. Two real-provider checks used only a public synthetic Experiment Service appendix, with no database access: the founder question returned canonical insufficient evidence with no citations; the caching question mentioned Hazelcast with valid S1 citations. This verifies answer generation against public fixtures, not the user's private retrieval workflow or overall model quality.
