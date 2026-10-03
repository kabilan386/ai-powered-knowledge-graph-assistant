import json
from pathlib import Path
from statistics import mean

METRICS = [
    "recall_at_k",
    "precision_at_k",
    "exact_match",
    "normalized_answer_match",
    "answer_entity_coverage",
    "insufficient_evidence_correct",
    "anchor_resolution_success",
    "expected_path_found",
    "expected_relationship_coverage",
    "hop_retrieval_success",
    "citation_ids_valid",
    "cited_documents_exist",
    "cited_chunks_exist",
    "citations_match_evidence",
    "citation_validity",
]
CATEGORIES = ["factual", "semantic", "relationship", "multi_hop", "insufficient_evidence"]


def measured(values: list) -> dict:
    available = [float(value) for value in values if value is not None]
    return {
        "value": mean(available) if available else None,
        "measured": len(available),
        "total": len(values),
        "not_measured": len(values) - len(available),
    }


def summarize(records: list[dict]) -> dict:
    summary = {}
    for mode in ["vector_rag", "graphrag"]:
        rows = [record[mode] for record in records]
        summary[mode] = {
            "requests": len(rows),
            "successful_requests": sum(row["status"] == "ok" for row in rows),
            "errors": sum(row["status"] == "error" for row in rows),
            "metrics": {
                key: measured([row["metrics"].get(key) for row in rows]) for key in METRICS
            },
            "latency_ms": {
                key: measured([row.get(key) for row in rows])
                for key in ["latency_ms", "vector_retrieval_ms", "graph_retrieval_ms"]
            },
            "categories": {
                category: measured(
                    [
                        record[mode]["metrics"].get("normalized_answer_match")
                        for record in records
                        if record["type"] == category
                    ]
                )
                for category in CATEGORIES
            },
            "tokens": {
                key: measured(
                    [
                        row["token_usage"].get("total_llm", {}).get(key)
                        if row["token_usage"].get("total_llm")
                        else None
                        for row in rows
                    ]
                )
                for key in ["prompt_tokens", "completion_tokens", "total_tokens"]
            },
        }
    return summary


def display(metric: dict, unit: str = "rate") -> str:
    if metric["value"] is None:
        return "N/A (not evaluated)"
    formatted = f"{metric['value'] * 100:.1f}%" if unit == "rate" else f"{metric['value']:.3f}"
    return f"{formatted} (n={metric['measured']}/{metric['total']})"


def markdown(payload: dict) -> str:
    meta, summary, records = payload["metadata"], payload["summary"], payload["questions"]
    lines = [
        "# Vector RAG vs GraphRAG evaluation",
        "",
        f"Run kind: **{meta['run_kind']}**. Generated: {meta['generated_at']}.",
        "",
        (
            f"Dataset: {meta['dataset_name']}. Questions: {meta['question_count']}. "
            f"Paired observations: {len(records)}. Top-K: {meta['top_k']}."
        ),
        "",
        "## Interpretation",
        "",
        (
            "Scripted mock runs verify the evaluation framework only. They do not "
            "establish learned embedding quality, real LLM accuracy, Neo4j "
            "performance, or a GraphRAG improvement. Live-provider evaluation is "
            "**Not evaluated yet** unless this run is explicitly marked live."
        ),
        "",
        (
            "Rates below are deterministic proxies, not semantic correctness "
            "judgments. Citation validity verifies supplied evidence "
            "identity/provenance, not entailment. Null metrics are N/A; denominators "
            "show measured/all observations, including unavailable/error cases. "
            "Errors are reported separately and must not be hidden when interpreting "
            "measured-only rates."
        ),
        "",
        "## Comparison",
        "",
        "| Metric | Vector RAG | GraphRAG |",
        "|---|---|---|",
    ]
    for key in METRICS:
        lines.append(
            f"| {key} | {display(summary['vector_rag']['metrics'][key])} | "
            f"{display(summary['graphrag']['metrics'][key])} |"
        )
    for category in CATEGORIES:
        lines.append(
            f"| {category}: normalized answer match | "
            f"{display(summary['vector_rag']['categories'][category])} | "
            f"{display(summary['graphrag']['categories'][category])} |"
        )
    for key in ["latency_ms", "vector_retrieval_ms", "graph_retrieval_ms"]:
        lines.append(
            f"| Average {key} | "
            f"{display(summary['vector_rag']['latency_ms'][key], 'ms')} | "
            f"{display(summary['graphrag']['latency_ms'][key], 'ms')} |"
        )
    for mode in ["vector_rag", "graphrag"]:
        row = summary[mode]
        lines += [
            "",
            (
                f"{mode}: {row['successful_requests']}/{row['requests']} successful "
                f"requests; {row['errors']} errors."
            ),
        ]
    lines += [
        "",
        "## Provider metadata",
        "",
        (
            f"LLM: {meta['llm_model']}; embedding: {meta['embedding_model']} ("
            f"{meta['embedding_dimensions']} dimensions)."
        ),
        "",
        "| Mean provider-reported tokens per request | Vector RAG | GraphRAG |",
        "|---|---|---|",
    ]
    for key in ["prompt_tokens", "completion_tokens", "total_tokens"]:
        lines.append(
            f"| {key} | {display(summary['vector_rag']['tokens'][key], 'tokens')} "
            f"| {display(summary['graphrag']['tokens'][key], 'tokens')} |"
        )
    lines += [
        "",
        (
            "Missing token usage remains null. Query-anchor and answer-generation "
            "usage are separately retained in raw JSON, including returned retry "
            "responses. Total usage is reported only when all invoked LLM calls "
            "supplied usage. Embedding token usage and ingestion calls are outside "
            "this LLM-token total. Monetary cost is not estimated."
        ),
        "",
        "## Per-question observations",
        "",
        (
            "| ID / repeat | Category | Source annotations | Vector status / answer "
            "match | GraphRAG status / answer match |"
        ),
        "|---|---|---|---|---|",
    ]
    for record in records:
        cells = []
        for mode in ["vector_rag", "graphrag"]:
            value = record[mode]["metrics"].get("normalized_answer_match")
            cells.append(f"{record[mode]['status']} / {value if value is not None else 'N/A'}")
        lines.append(
            f"| {record['id']} / {record['repeat']} | {record['type']} | "
            f"{record['ground_truth']['status']} | {' | '.join(cells)} |"
        )
    lines += [
        "",
        "## Reproducibility",
        "",
        (
            f"Dataset SHA-256: `{meta['dataset_sha256']}`. Answer prompt SHA-256: `"
            f"{meta['answer_prompt_sha256']}`."
        ),
        "",
        (
            "Both modes use the same query, top-K, embedding/LLM model, answer "
            "prompt, retry settings, and context limits. GraphRAG uses the "
            "production orchestrator, including its graph/text budget allocation. "
            "Mode order alternates by question/repetition to reduce systematic "
            "warm-cache order bias; there is no forced cache reset. Retrieval "
            "timings include query embedding/index checks or anchor "
            "extraction/traversal, respectively. Total answer timings exclude "
            "evaluation-only ground-truth/citation audits. Small datasets and "
            "scripted fixtures do not support statistical improvement claims."
        ),
        "",
    ]
    return "\n".join(lines)


def save_report(payload: dict, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "results.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )
    (directory / "report.md").write_text(markdown(payload), encoding="utf-8")
