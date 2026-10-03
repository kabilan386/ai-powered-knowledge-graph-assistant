# Vector RAG vs GraphRAG evaluation

Run kind: **scripted_mock**. Generated: 2026-10-03T07:14:50.142370+00:00.

Dataset: MCA platform services evaluation. Questions: 8. Paired observations: 8. Top-K: 5.

## Interpretation

Scripted mock runs verify the evaluation framework only. They do not establish learned embedding quality, real LLM accuracy, Neo4j performance, or a GraphRAG improvement. Live-provider evaluation is **Not evaluated yet** unless this run is explicitly marked live.

Rates below are deterministic proxies, not semantic correctness judgments. Citation validity verifies supplied evidence identity/provenance, not entailment. Null metrics are N/A; denominators show measured/all observations, including unavailable/error cases. Errors are reported separately and must not be hidden when interpreting measured-only rates.

## Comparison

| Metric | Vector RAG | GraphRAG |
|---|---|---|
| recall_at_k | 95.2% (n=7/8) | 95.2% (n=7/8) |
| precision_at_k | 25.7% (n=7/8) | 25.7% (n=7/8) |
| exact_match | 85.7% (n=7/8) | 100.0% (n=7/8) |
| normalized_answer_match | 85.7% (n=7/8) | 100.0% (n=7/8) |
| answer_entity_coverage | 85.7% (n=7/8) | 100.0% (n=7/8) |
| insufficient_evidence_correct | 87.5% (n=8/8) | 100.0% (n=8/8) |
| anchor_resolution_success | N/A (not evaluated) | 100.0% (n=7/8) |
| expected_path_found | N/A (not evaluated) | 100.0% (n=5/8) |
| expected_relationship_coverage | N/A (not evaluated) | 100.0% (n=5/8) |
| hop_retrieval_success | N/A (not evaluated) | 100.0% (n=5/8) |
| citation_ids_valid | 100.0% (n=8/8) | 100.0% (n=8/8) |
| cited_documents_exist | 100.0% (n=6/8) | 100.0% (n=7/8) |
| cited_chunks_exist | 100.0% (n=6/8) | 100.0% (n=7/8) |
| citations_match_evidence | 100.0% (n=8/8) | 100.0% (n=8/8) |
| citation_validity | 100.0% (n=6/8) | 100.0% (n=7/8) |
| factual: normalized answer match | 100.0% (n=2/2) | 100.0% (n=2/2) |
| semantic: normalized answer match | 100.0% (n=1/1) | 100.0% (n=1/1) |
| relationship: normalized answer match | 100.0% (n=2/2) | 100.0% (n=2/2) |
| multi_hop: normalized answer match | 50.0% (n=2/2) | 100.0% (n=2/2) |
| insufficient_evidence: normalized answer match | N/A (not evaluated) | N/A (not evaluated) |
| Average latency_ms | 0.448 (n=8/8) | 0.723 (n=8/8) |
| Average vector_retrieval_ms | 0.170 (n=8/8) | 0.145 (n=8/8) |
| Average graph_retrieval_ms | N/A (not evaluated) | 0.226 (n=8/8) |

vector_rag: 8/8 successful requests; 0 errors.

graphrag: 8/8 successful requests; 0 errors.

## Provider metadata

LLM: fixture-rules; embedding: fixture-hash-bag (64 dimensions).

| Mean provider-reported tokens per request | Vector RAG | GraphRAG |
|---|---|---|
| prompt_tokens | N/A (not evaluated) | N/A (not evaluated) |
| completion_tokens | N/A (not evaluated) | N/A (not evaluated) |
| total_tokens | N/A (not evaluated) | N/A (not evaluated) |

Missing token usage remains null. Query-anchor and answer-generation usage are separately retained in raw JSON, including returned retry responses. Total usage is reported only when all invoked LLM calls supplied usage. Embedding token usage and ingestion calls are outside this LLM-token total. Monetary cost is not estimated.

## Per-question observations

| ID / repeat | Category | Source annotations | Vector status / answer match | GraphRAG status / answer match |
|---|---|---|---|---|
| Q001 / 1 | factual | resolved | ok / True | ok / True |
| Q002 / 1 | semantic | resolved | ok / True | ok / True |
| Q003 / 1 | relationship | resolved | ok / True | ok / True |
| Q004 / 1 | multi_hop | resolved | ok / True | ok / True |
| Q005 / 1 | multi_hop | resolved | ok / False | ok / True |
| Q006 / 1 | insufficient_evidence | unannotated | ok / N/A | ok / N/A |
| Q007 / 1 | factual | resolved | ok / True | ok / True |
| Q008 / 1 | relationship | resolved | ok / True | ok / True |

## Reproducibility

Dataset SHA-256: `6969b9a30c301afb9585bfe39d4016a97c0ab56105195c97928e96a5d4864f41`. Answer prompt SHA-256: `5562706b4b3fbf5850b2a7ddea9a12320dea1237217d7c3f5a97ff7d32b01180`.

Both modes use the same query, top-K, embedding/LLM model, answer prompt, retry settings, and context limits. GraphRAG uses the production orchestrator, including its graph/text budget allocation. Mode order alternates by question/repetition to reduce systematic warm-cache order bias; there is no forced cache reset. Retrieval timings include query embedding/index checks or anchor extraction/traversal, respectively. Total answer timings exclude evaluation-only ground-truth/citation audits. Small datasets and scripted fixtures do not support statistical improvement claims.
