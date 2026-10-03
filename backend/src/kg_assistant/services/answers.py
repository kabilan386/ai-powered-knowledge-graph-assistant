import asyncio
import logging
import re

from kg_assistant.core.config import Settings
from kg_assistant.models.graphrag import CitationSource, FusedContext, GroundedAnswer
from kg_assistant.providers.answer import AnswerProvider
from kg_assistant.providers.base import ExtractionError

logger = logging.getLogger(__name__)
INSUFFICIENT_ANSWER = (
    "The available knowledge does not contain enough information to answer this question."
)


def validate_answer(result: GroundedAnswer, context: FusedContext) -> GroundedAnswer:
    if not isinstance(result, GroundedAnswer):
        raise ExtractionError("answer_invalid_response")
    # Discard the entire untrusted non-answer before checking citations it will not expose.
    if result.insufficient_evidence:
        return GroundedAnswer(answer=INSUFFICIENT_ANSWER, citations=[], insufficient_evidence=True)
    supplied = {item.citation for item in context.text_evidence + context.graph_evidence}
    inline = re.findall(r"\[([SG][^\[\]]*)\]", result.answer)
    if any(citation not in supplied for citation in inline + result.citations):
        raise ExtractionError("answer_invalid_citation")
    if not result.citations or result.citations != list(dict.fromkeys(inline)):
        raise ExtractionError("answer_invalid_citation")
    return result


def map_sources(citations: list[str], context: FusedContext) -> list[CitationSource]:
    mapping = {}
    for item in context.text_evidence:
        mapping[item.citation] = CitationSource(
            kind="document", **item.model_dump(exclude={"vector_score"})
        )
    for item in context.graph_evidence:
        support = list(
            dict.fromkeys(citation for edge in item.edges for citation in edge.source_citations)
        )
        mapping[item.citation] = CitationSource(
            citation=item.citation,
            kind="graph",
            nodes=item.nodes,
            edges=item.edges,
            supporting_citations=support,
        )
    selected = list(citations)
    for citation in citations:
        for supporting in mapping[citation].supporting_citations:
            if supporting not in selected:
                selected.append(supporting)
    return [mapping[citation] for citation in selected]


class AnswerGenerationService:
    def __init__(self, settings: Settings, provider: AnswerProvider) -> None:
        self.settings = settings
        self.provider = provider

    async def generate(self, question: str, context: FusedContext) -> GroundedAnswer:
        previous_error: str | None = None
        for attempt in range(1, self.settings.llm_max_attempts + 1):
            try:
                async with asyncio.timeout(self.settings.llm_request_timeout):
                    feedback_method = getattr(type(self.provider), "generate_with_feedback", None)
                    if previous_error and feedback_method is not None:
                        response = await feedback_method(
                            self.provider, question, context, previous_error
                        )
                    else:
                        response = await self.provider.generate(question, context)
                result = validate_answer(response, context)
                logger.info("answer_generation_succeeded", extra={"attempt": attempt})
                return result
            except (TimeoutError, OSError):
                error = ExtractionError("answer_provider_unavailable")
            except ExtractionError as exc:
                error = exc
            logger.warning(
                "answer_generation_failed", extra={"error_code": error.code, "attempt": attempt}
            )
            if not error.retryable or attempt == self.settings.llm_max_attempts:
                raise error
            previous_error = error.code
            await asyncio.sleep(self.settings.llm_retry_backoff * attempt)
        raise RuntimeError("Unreachable retry state")
