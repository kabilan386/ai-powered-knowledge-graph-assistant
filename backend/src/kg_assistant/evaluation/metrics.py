import re
import unicodedata

from kg_assistant.evaluation.models import EvaluationCase, ResolvedGroundTruth
from kg_assistant.ingestion.normalization import normalize_name
from kg_assistant.models.graph_retrieval import GraphSearchResponse
from kg_assistant.models.graphrag import AskResponse
from kg_assistant.models.retrieval import VectorSearchResponse


def without_citations(answer: str) -> str:
    return re.sub(r"\[[SG][0-9]+\]", "", answer).strip()


def normalized_answer(answer: str) -> str:
    value = unicodedata.normalize("NFKC", without_citations(answer)).casefold()
    return " ".join(
        "".join(" " if unicodedata.category(c).startswith("P") else c for c in value).split()
    )


def answer_metrics(case: EvaluationCase, response: AskResponse | None) -> dict:
    result = dict.fromkeys(
        [
            "exact_match",
            "normalized_answer_match",
            "answer_entity_coverage",
            "insufficient_evidence_correct",
        ]
    )
    if response is None:
        return result
    if case.expected_answer is not None:
        result["exact_match"] = without_citations(response.answer) == case.expected_answer
        result["normalized_answer_match"] = normalized_answer(response.answer) == normalized_answer(
            case.expected_answer
        )
    if case.expected_entities:
        answer = " " + normalized_answer(response.answer) + " "
        expected = {normalized_answer(name) for name in case.expected_entities}
        result["answer_entity_coverage"] = sum(
            " " + name + " " in answer for name in expected
        ) / len(expected)
    if case.expected_insufficient_evidence is not None:
        result["insufficient_evidence_correct"] = (
            response.insufficient_evidence == case.expected_insufficient_evidence
        )
    return result


def retrieval_metrics(
    case: EvaluationCase,
    vector: VectorSearchResponse | None,
    truth: ResolvedGroundTruth,
    top_k: int,
) -> dict:
    if truth.status != "resolved" or not truth.references or vector is None:
        return {"recall_at_k": None, "precision_at_k": None}
    expected = set(truth.references)
    # Duplicate retrieval rows do not count twice; missing K positions are non-relevant.
    retrieved = list(dict.fromkeys((row.document_id, row.chunk_id) for row in vector.results))[
        :top_k
    ]
    hits = len(set(retrieved) & expected)
    return {
        "recall_at_k": hits / len(expected),
        "precision_at_k": hits / top_k if case.sources_complete else None,
    }


def graph_metrics(case: EvaluationCase, graph: GraphSearchResponse | None) -> dict:
    result = dict.fromkeys(
        [
            "anchor_resolution_success",
            "expected_path_found",
            "expected_relationship_coverage",
            "hop_retrieval_success",
        ]
    )
    if graph is None:
        return result
    if case.expected_anchors:
        resolved = {normalize_name(entity.name) for entity in graph.anchors}
        result["anchor_resolution_success"] = all(
            normalize_name(name) in resolved for name in case.expected_anchors
        )
    if not case.expected_path:
        return result
    expected = [
        (normalize_name(edge.source), edge.type, normalize_name(edge.target))
        for edge in case.expected_path
    ]
    found = False
    all_edges = set()
    for path in graph.paths:
        names = {node.id: normalize_name(node.name) for node in path.nodes}
        actual = [(names[edge.source_id], edge.type, names[edge.target_id]) for edge in path.edges]
        all_edges.update(actual)
        # Traversal order may be reversed; stored edge directions must still match.
        for chain in (actual, actual[::-1]):
            found |= any(
                chain[index : index + len(expected)] == expected
                for index in range(len(chain) - len(expected) + 1)
            )
    result.update(
        expected_path_found=found,
        expected_relationship_coverage=len(set(expected) & all_edges) / len(set(expected)),
        hop_retrieval_success=found,
    )
    return result
