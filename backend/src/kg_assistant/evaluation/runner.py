from dataclasses import dataclass
from time import perf_counter

from kg_assistant.core.config import Settings
from kg_assistant.core.exceptions import IngestionError
from kg_assistant.evaluation.baseline import VectorRAGBaseline
from kg_assistant.evaluation.citations import citation_metrics
from kg_assistant.evaluation.metrics import answer_metrics, graph_metrics, retrieval_metrics
from kg_assistant.evaluation.models import (
    EvaluationCase,
    EvaluationDataset,
    Mode,
    ModeResult,
    ResolvedGroundTruth,
)
from kg_assistant.evaluation.observations import (
    ObservedAnswerProvider,
    ObservedContextBuilder,
    ObservedRetriever,
    UsageLedger,
    current_usage,
)
from kg_assistant.models.graphrag import AskRequest
from kg_assistant.providers.base import ExtractionError
from kg_assistant.services.answers import AnswerGenerationService
from kg_assistant.services.graphrag import GraphRAGService


@dataclass
class EvaluationRuntime:
    settings: Settings
    vector: object
    graph: object
    context_repository: object
    answer_provider: object
    audit_repository: object


async def evaluate_mode(
    runtime: EvaluationRuntime, case: EvaluationCase, mode: Mode, truth: ResolvedGroundTruth
) -> ModeResult:
    vector = ObservedRetriever(runtime.vector)
    graph = ObservedRetriever(runtime.graph)
    builder = ObservedContextBuilder(runtime.settings)
    generator = AnswerGenerationService(
        runtime.settings, ObservedAnswerProvider(runtime.answer_provider)
    )
    ledger = UsageLedger()
    token = current_usage.set(ledger)
    started = perf_counter()
    response = None
    code = None
    try:
        service = (
            VectorRAGBaseline(
                runtime.settings, vector, runtime.context_repository, builder, generator
            )
            if mode == "vector_rag"
            else GraphRAGService(
                runtime.settings, vector, graph, runtime.context_repository, builder, generator
            )
        )
        response = await service.ask(AskRequest(question=case.question))
    except (IngestionError, ExtractionError) as exc:
        code = exc.code
    except Exception as exc:
        # Raw provider/DB error messages may contain secrets or source text.
        code = type(exc).__name__
    finally:
        latency = (perf_counter() - started) * 1000
        current_usage.reset(token)
    metrics = {
        **answer_metrics(case, response),
        **retrieval_metrics(case, vector.result, truth, runtime.settings.vector_top_k),
        **graph_metrics(case, graph.result),
    }
    try:
        metrics.update(await citation_metrics(response, builder.context, runtime.audit_repository))
    except Exception:
        # Never turn an unavailable source audit into a validity success or failed retrieval.
        metrics.update(
            dict.fromkeys(
                [
                    "citation_ids_valid",
                    "cited_documents_exist",
                    "cited_chunks_exist",
                    "citations_match_evidence",
                    "citation_validity",
                ]
            )
        )
        code = code or "citation_audit_unavailable"
    return ModeResult(
        status="error" if code else "ok",
        response=response,
        vector=vector.result,
        graph=graph.result,
        context=builder.context,
        latency_ms=latency,
        vector_retrieval_ms=vector.latency_ms,
        graph_retrieval_ms=graph.latency_ms,
        token_usage=ledger.summary(),
        error_code=code,
        metrics=metrics,
    )


def serialize_result(result: ModeResult) -> dict:
    data = result.model_dump(mode="json")
    data.update(
        answer=result.response.answer if result.response else None,
        retrieved_chunks=result.vector.model_dump(mode="json")["results"] if result.vector else [],
        graph_paths=result.graph.model_dump(mode="json")["paths"] if result.graph else [],
        citations=result.response.citations if result.response else [],
    )
    return data


async def evaluate_dataset(
    runtime: EvaluationRuntime, dataset: EvaluationDataset, repeats: int = 1
) -> list[dict]:
    records = []
    for repeat in range(repeats):
        for index, case in enumerate(dataset.cases):
            try:
                truth = await runtime.audit_repository.resolve_sources(case.expected_sources)
            except Exception:
                truth = ResolvedGroundTruth(status="error")
            record = {
                "id": case.id,
                "type": case.question_type,
                "question": case.question,
                "expected_answer": case.expected_answer,
                "case": case.model_dump(mode="json"),
                "repeat": repeat + 1,
                "ground_truth": truth.model_dump(mode="json"),
            }
            order: list[Mode] = (
                ["vector_rag", "graphrag"]
                if (repeat + index) % 2 == 0
                else ["graphrag", "vector_rag"]
            )
            record["mode_order"] = order
            for mode in order:
                record[mode] = serialize_result(await evaluate_mode(runtime, case, mode, truth))
            records.append(record)
    return records
