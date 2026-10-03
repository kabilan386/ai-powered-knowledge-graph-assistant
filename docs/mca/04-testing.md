# Testing: executed results and approach

Source: evaluation/test-cases.json generated 2026-10-03T07:15:57.230841+00:00. Backend 231 and frontend 26 executed cases. Status counts: {'PASS': 257}. No manual/live-provider procedure is counted as PASS.

## Approach

Backend pytest uses mocked AI providers; isolated Neo4j integration tests verify real transactions, indexing, provenance, and retrieval. Frontend Vitest/Testing Library mocks HTTP/XHR/Cytoscape where necessary and verifies presentation/interaction. Default evaluation exercises production service composition with scripted providers/database doubles. Live model quality, throughput and security penetration testing are not evaluated.

## Executed module table

| Module | Recorded status | Cases |
|---|---|---|
| Context fusion / Grounded answers | PASS | 28 |
| E2E / Evaluation | PASS | 1 |
| E2E / GraphRAG | PASS | 1 |
| Embeddings | PASS | 24 |
| Entity extraction | PASS | 22 |
| Evaluation framework | PASS | 33 |
| Frontend API | PASS | 7 |
| Frontend chat/citations | PASS | 5 |
| Frontend graph | PASS | 5 |
| Frontend upload | PASS | 9 |
| Graph retrieval | PASS | 27 |
| Knowledge graph ingestion | PASS | 5 |
| Security / Request validation | PASS | 9 |
| Text extraction / Chunking | PASS | 21 |
| Upload API | PASS | 11 |
| Vector retrieval | PASS | 14 |
| tests.integration.test_graph_search_neo4j | PASS | 1 |
| tests.integration.test_graph_visualization_neo4j | PASS | 1 |
| tests.integration.test_knowledge_graph | PASS | 3 |
| tests.integration.test_neo4j_upload | PASS | 4 |
| tests.integration.test_vector_search | PASS | 3 |
| tests.test_document_repository | PASS | 2 |
| tests.test_foundation | PASS | 14 |
| tests.test_graph_repository | PASS | 2 |
| tests.test_graph_visualization | PASS | 5 |

## Coverage and E2E

Tests cover PDF/DOCX/TXT extraction, empty/corrupt/oversize validation, chunk boundaries/metadata, structured extraction/normalization/duplicates, atomic graph writes and leases, embeddings/dimensions/model compatibility/backfill, vector ranking/sources, one-/two-/three-hop BFS/provenance/cycles/exclusions, context fusion/dedupe/limits, valid/invalid citations, graph-only/vector-only/no evidence, provider/retrieval failures, evaluation denominators/N/A and usage accounting. Frontend tests cover upload, chat, citations, graph transformations/inspection and error/loading states. Final regression adds body transport and filename security tests.

Real-Neo4j E2E uploads documents through FastAPI, extracts/chunks, stores mocked embeddings and extracted facts, runs production retrievers and GraphRAG, verifies the three-hop path and actual source ownership/excerpts, tests insufficiency, and cleans documents/facts. A second E2E compares both evaluation modes against the real database. Frontend rendering is tested separately with response fixtures; a new full live-provider browser E2E has not been executed in the final milestone.

## Test-case rows and comparison

The complete Test ID / Module / Scenario / Input / Expected / Actual / Status table is [evaluation/test-cases.md](../../evaluation/test-cases.md), backed by JSON and actual JUnit input hashes. [Comparison report](../../evaluation/report.md) contains measured scripted results/latency with coverage denominators. Scripted answer-match scores are not real semantic accuracy. Token/cost values remain null when unavailable.

Commands and isolated database requirements are in [README](../../README.md#19-testing). The [manual demo](../demo.md) uses configured real providers and is not a fabricated PASS report.
