from kg_assistant.models.graphrag import AskResponse, FusedContext, GroundedAnswer
from kg_assistant.providers.base import ExtractionError
from kg_assistant.services.answers import map_sources, validate_answer


async def citation_metrics(
    response: AskResponse | None, context: FusedContext | None, repository
) -> dict:
    metrics = dict.fromkeys(
        [
            "citation_ids_valid",
            "cited_documents_exist",
            "cited_chunks_exist",
            "citations_match_evidence",
            "citation_validity",
        ]
    )
    if response is None or context is None:
        return metrics
    try:
        validate_answer(
            GroundedAnswer(
                answer=response.answer,
                citations=response.citations,
                insufficient_evidence=response.insufficient_evidence,
            ),
            context,
        )
        ids_valid = True
    except ExtractionError:
        ids_valid = False
    metrics["citation_ids_valid"] = ids_valid
    try:
        expected = map_sources(response.citations, context)
        matches = len({source.citation for source in response.sources}) == len(
            response.sources
        ) and {source.citation: source.model_dump() for source in response.sources} == {
            source.citation: source.model_dump() for source in expected
        }
    except KeyError:
        matches = False
    metrics["citations_match_evidence"] = matches
    documents = [source for source in response.sources if source.kind == "document"]
    if documents:
        references = [(source.document_id, source.chunk_id) for source in documents]
        if any(not doc or not chunk for doc, chunk in references):
            metrics["cited_documents_exist"] = False
            metrics["cited_chunks_exist"] = False
            matches = False
        else:
            rows = await repository.audit(references)
            indexed = {(row["document_id"], row["chunk_id"]): row for row in rows}
            metrics["cited_documents_exist"] = all(
                indexed.get(key, {}).get("document_exists", False) for key in references
            )
            metrics["cited_chunks_exist"] = all(
                indexed.get(key, {}).get("chunk_exists", False) for key in references
            )
            matches &= all(indexed.get(key, {}).get("linked", False) for key in references)
        metrics["citations_match_evidence"] = matches
    if (
        not response.citations
        and not response.sources
        and response.insufficient_evidence
        and ids_valid
    ):
        return metrics  # Citation validity is N/A, not a vacuous 100% success.
    metrics["citation_validity"] = (
        ids_valid
        and matches
        and all(
            metrics[key] is not False for key in ["cited_documents_exist", "cited_chunks_exist"]
        )
    )
    return metrics
