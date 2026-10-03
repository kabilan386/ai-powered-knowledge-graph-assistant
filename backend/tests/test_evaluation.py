import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from graphrag_fixtures import evidence
from pydantic import ValidationError

from kg_assistant.evaluation.citations import citation_metrics
from kg_assistant.evaluation.fixtures import fixture_runtime
from kg_assistant.evaluation.metrics import answer_metrics, graph_metrics, retrieval_metrics
from kg_assistant.evaluation.models import EvaluationCase, EvaluationDataset, ResolvedGroundTruth
from kg_assistant.evaluation.observations import UsageLedger
from kg_assistant.evaluation.report import measured, summarize
from kg_assistant.evaluation.repository import resolve_rows
from kg_assistant.evaluation.runner import evaluate_dataset, evaluate_mode
from kg_assistant.evaluation.test_report import generate
from kg_assistant.providers.usage import TokenUsage, observe_usage

DATASET = Path(__file__).parents[2] / "evaluation/dataset.json"


def dataset():
    return EvaluationDataset.model_validate_json(DATASET.read_bytes())


def case(**changes):
    return dataset().cases[0].model_copy(update=changes)


@pytest.mark.parametrize(
    "change",
    [
        {"question": ""},
        {"question_type": "unknown"},
        {"question_type": "insufficient_evidence", "expected_insufficient_evidence": False},
        {"expected_insufficient_evidence": True},
        {"expected_sources": [{"filename": "sample.txt"}]},
        {"expected_entities": ["  "]},
        {
            "expected_path": [
                {"source": "A", "target": "B", "type": "USES"},
                {"source": "C", "target": "D", "type": "USES"},
            ]
        },
    ],
)
def test_dataset_rejects_invalid_ground_truth(change):
    values = dataset().cases[0].model_dump()
    values.update(change)
    with pytest.raises(ValidationError):
        EvaluationCase.model_validate(values)


def test_duplicate_question_ids_rejected():
    values = dataset().model_dump()
    values["cases"].append(values["cases"][0])
    with pytest.raises(ValidationError):
        EvaluationDataset.model_validate(values)


@pytest.mark.parametrize("status", ["unannotated", "missing", "ambiguous", "error"])
def test_unavailable_source_annotations_are_not_zero_accuracy(status):
    vector, _, _ = evidence()
    assert retrieval_metrics(case(), vector, ResolvedGroundTruth(status=status), 5) == {
        "recall_at_k": None,
        "precision_at_k": None,
    }


def test_retrieval_denominators_deduplication_and_incomplete_annotations():
    vector, _, _ = evidence()
    vector.results.insert(0, vector.results[0])
    truth = ResolvedGroundTruth(status="resolved", references=[("d", "c0"), ("d", "missing")])
    assert retrieval_metrics(case(), vector, truth, 5) == {
        "recall_at_k": 0.5,
        "precision_at_k": 0.2,
    }
    assert (
        retrieval_metrics(case(sources_complete=False), vector, truth, 5)["precision_at_k"] is None
    )


@pytest.mark.parametrize(
    "rows,status",
    [
        ([], "missing"),
        (
            [
                {"selector_index": 0, "document_id": "a", "chunk_id": "1"},
                {"selector_index": 0, "document_id": "b", "chunk_id": "2"},
            ],
            "ambiguous",
        ),
        ([{"selector_index": 0, "document_id": "a", "chunk_id": "1"}], "resolved"),
    ],
)
def test_source_resolution_does_not_guess(rows, status):
    assert resolve_rows(1, rows).status == status


async def test_answer_metrics_are_explicit_proxies():
    runtime = fixture_runtime()
    result = await evaluate_mode(
        runtime, case(), "vector_rag", ResolvedGroundTruth(status="unannotated")
    )
    response = result.response.model_copy(update={"answer": "ＲＥＤＩＳ! [S1]"})
    metrics = answer_metrics(case(), response)
    assert metrics["normalized_answer_match"] is True
    assert metrics["exact_match"] is False
    assert metrics["answer_entity_coverage"] == 1
    response.answer = "Redistribution is a different word."
    assert answer_metrics(case(), response)["answer_entity_coverage"] == 0
    assert all(value is None for value in answer_metrics(case(), None).values())


def test_graph_metrics_require_contiguous_directional_expected_path():
    _, graph, _ = evidence()
    expected = dataset().cases[4]
    assert graph_metrics(expected, graph)["expected_path_found"] is True
    graph.paths[0].edges[1].source_id, graph.paths[0].edges[1].target_id = (
        graph.paths[0].edges[1].target_id,
        graph.paths[0].edges[1].source_id,
    )
    metrics = graph_metrics(expected, graph)
    assert metrics["expected_path_found"] is False
    assert metrics["expected_relationship_coverage"] == pytest.approx(2 / 3)
    assert all(value is None for value in graph_metrics(expected, None).values())


async def test_vector_baseline_never_calls_graph_and_uses_same_answer_policy():
    runtime = fixture_runtime()
    runtime.graph = AsyncMock()
    runtime.graph.search.side_effect = AssertionError("Baseline must not traverse graph")
    result = await evaluate_mode(
        runtime, case(), "vector_rag", ResolvedGroundTruth(status="unannotated")
    )
    assert result.status == "ok"
    assert result.context.text_evidence and not result.context.graph_evidence
    assert result.graph is None and result.graph_retrieval_ms is None
    assert result.response.retrieval.graph_paths == 0
    runtime.graph.search.assert_not_called()


async def test_production_graph_and_vector_comparison_with_actual_fixture_evidence():
    records = await evaluate_dataset(fixture_runtime(), dataset(), repeats=2)
    assert len(records) == 16
    assert records[0]["mode_order"] == records[8]["mode_order"][::-1]
    for record in records:
        for mode in ["vector_rag", "graphrag"]:
            row = record[mode]
            assert row["status"] == "ok"
            assert row["latency_ms"] >= row["vector_retrieval_ms"] >= 0
            assert row["token_usage"]["total_llm"] is None
            assert isinstance(row["metrics"]["insufficient_evidence_correct"], bool)
        if record["id"] == "Q005":
            assert record["graphrag"]["metrics"]["expected_path_found"] is True
            assert record["graphrag"]["metrics"]["citation_validity"] is True
        if record["id"] == "Q006":
            assert record["graphrag"]["response"]["insufficient_evidence"] is True
            assert record["graphrag"]["metrics"]["citation_validity"] is None
    assert summarize(records)["graphrag"]["errors"] == 0


@pytest.mark.parametrize("stage", ["vector", "answer_provider", "audit_repository"])
async def test_failures_are_recorded_without_fabricated_answers(stage):
    runtime = fixture_runtime()
    if stage == "vector":
        runtime.vector = AsyncMock()
        runtime.vector.search.side_effect = RuntimeError("sensitive provider content")
    elif stage == "answer_provider":
        runtime.answer_provider = AsyncMock()
        runtime.answer_provider.generate.side_effect = RuntimeError("sensitive provider content")
    else:
        runtime.audit_repository = AsyncMock()
        runtime.audit_repository.audit.side_effect = RuntimeError("sensitive DB content")
    result = await evaluate_mode(
        runtime, case(), "vector_rag", ResolvedGroundTruth(status="unannotated")
    )
    assert result.status == "error"
    assert "sensitive" not in (result.error_code or "")
    if stage != "audit_repository":
        assert result.response is None and result.metrics["normalized_answer_match"] is None
    else:
        assert result.metrics["citation_validity"] is None


@pytest.mark.parametrize("fault", ["unknown_id", "missing_document", "missing_chunk", "wrong_link"])
async def test_citation_audits_reject_unsupported_sources(fault):
    runtime = fixture_runtime()
    result = await evaluate_mode(
        runtime, case(), "vector_rag", ResolvedGroundTruth(status="unannotated")
    )
    response = result.response.model_copy(deep=True)
    repository = AsyncMock()
    repository.audit.return_value = [
        {
            "document_id": source.document_id,
            "chunk_id": source.chunk_id,
            "document_exists": fault != "missing_document",
            "chunk_exists": fault != "missing_chunk",
            "linked": fault != "wrong_link",
        }
        for source in response.sources
    ]
    if fault == "unknown_id":
        response.answer = "Redis [S99]"
        response.citations = ["S99"]
    metrics = await citation_metrics(response, result.context, repository)
    assert metrics["citation_validity"] is False


def test_usage_does_not_invent_tokens_and_counts_retries():
    ledger = UsageLedger()
    usage = TokenUsage(prompt_tokens=10, completion_tokens=3, total_tokens=13)
    for _ in range(2):
        ledger.start("answer_generation")
        ledger.observe("answer_generation", usage)
    assert ledger.summary()["total_llm"].total_tokens == 26
    ledger.start("query_entity_extraction")
    assert ledger.summary()["total_llm"] is None
    seen = []
    observe_usage(
        SimpleNamespace(usage=SimpleNamespace(input_tokens=2, output_tokens=1, total_tokens=3)),
        seen.append,
    )
    observe_usage(SimpleNamespace(usage=None), seen.append)
    assert seen[0].total_tokens == 3 and seen[1] is None


def test_summary_preserves_missing_metric_denominators():
    assert measured([True, False, None]) == {
        "value": 0.5,
        "measured": 2,
        "total": 3,
        "not_measured": 1,
    }
    assert measured([None])["value"] is None


def test_mca_report_uses_runner_statuses_not_assumed_pass(tmp_path):
    junit = tmp_path / "tests.xml"
    junit.write_text(
        '<testsuite><testcase name="good" time=".2"/>'
        '<testcase name="bad"><failure/></testcase>'
        '<testcase name="broken"><error/></testcase>'
        '<testcase name="disabled"><skipped/></testcase></testsuite>'
    )
    catalog = tmp_path / "catalog.json"
    catalog.write_text("[]")
    result = generate({"backend": junit}, catalog, tmp_path)
    assert result["counts"] == {"PASS": 1, "FAIL": 1, "ERROR": 1, "SKIP": 1}
    assert json.loads((tmp_path / "test-cases.json").read_text())["counts"] == result["counts"]
    with pytest.raises(FileNotFoundError):
        generate({"backend": tmp_path / "absent.xml"}, catalog, tmp_path / "absent")


async def test_graph_only_citation_audit_keeps_document_existence_not_applicable():
    runtime = fixture_runtime()
    result = await evaluate_mode(
        runtime, dataset().cases[4], "graphrag", ResolvedGroundTruth(status="unannotated")
    )
    context = result.context.model_copy(deep=True)
    for edge in context.graph_evidence[0].edges:
        edge.source_citations = []
        edge.document_backed = False
    from kg_assistant.models.graphrag import GroundedAnswer
    from kg_assistant.services.answers import map_sources

    answer = GroundedAnswer(
        answer="AWS ElastiCache [G1]", citations=["G1"], insufficient_evidence=False
    )
    response = result.response.model_copy(
        update={
            "answer": answer.answer,
            "citations": answer.citations,
            "sources": map_sources(answer.citations, context),
        }
    )
    metrics = await citation_metrics(response, context, runtime.audit_repository)
    assert metrics["citation_validity"] is True
    assert metrics["cited_chunks_exist"] is None and metrics["cited_documents_exist"] is None


async def test_invalid_model_citations_become_explicit_evaluation_failure():
    from kg_assistant.models.graphrag import GroundedAnswer

    runtime = fixture_runtime()
    runtime.settings.llm_max_attempts = 1
    runtime.answer_provider = AsyncMock()
    runtime.answer_provider.generate.return_value = GroundedAnswer(
        answer="Redis [S99]",
        citations=["S99"],
        insufficient_evidence=False,
    )
    result = await evaluate_mode(
        runtime, case(), "vector_rag", ResolvedGroundTruth(status="unannotated")
    )
    assert result.status == "error" and result.response is None
    assert result.metrics["citation_validity"] is None


async def test_evaluation_respects_production_context_limits():
    runtime = fixture_runtime()
    runtime.settings.max_context_chunks = 1
    runtime.settings.max_graph_paths = 1
    result = await evaluate_mode(
        runtime, dataset().cases[4], "graphrag", ResolvedGroundTruth(status="unannotated")
    )
    assert result.status == "ok"
    assert len(result.context.text_evidence) <= 1
    assert len(result.context.graph_evidence) <= 1
    assert result.response.insufficient_evidence
