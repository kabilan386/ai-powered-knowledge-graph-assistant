from contextvars import ContextVar
from time import perf_counter

from kg_assistant.models.graphrag import FusedContext
from kg_assistant.providers.usage import TokenUsage
from kg_assistant.retrieval.context import ContextBuilder


class UsageLedger:
    def __init__(self) -> None:
        self.calls = {"answer_generation": 0, "query_entity_extraction": 0}
        self.responses: dict[str, list[TokenUsage | None]] = {key: [] for key in self.calls}

    def start(self, stage: str) -> None:
        self.calls[stage] += 1

    def observe(self, stage: str, usage: TokenUsage | None) -> None:
        self.responses[stage].append(usage)

    def summary(self) -> dict[str, TokenUsage | None]:
        totals = {}
        for stage, calls in self.calls.items():
            rows = self.responses[stage]
            if not calls or len(rows) != calls or any(row is None for row in rows):
                totals[stage] = None
            else:
                totals[stage] = TokenUsage(
                    **{
                        key: sum(getattr(row, key) for row in rows)
                        for key in TokenUsage.model_fields
                    }
                )
        invoked = [key for key, count in self.calls.items() if count]
        totals["total_llm"] = (
            TokenUsage(
                **{
                    field: sum(getattr(totals[key], field) for key in invoked)
                    for field in TokenUsage.model_fields
                }
            )
            if invoked and all(totals[key] is not None for key in invoked)
            else None
        )
        return totals


current_usage: ContextVar[UsageLedger | None] = ContextVar("evaluation_usage", default=None)


def observe(stage: str, usage: TokenUsage | None) -> None:
    ledger = current_usage.get()
    if ledger is not None:
        ledger.observe(stage, usage)


class ObservedAnswerProvider:
    def __init__(self, provider) -> None:
        self.provider = provider

    async def generate(self, question, context):
        ledger = current_usage.get()
        if ledger is not None:
            ledger.start("answer_generation")
        return await self.provider.generate(question, context)

    async def generate_with_feedback(self, question, context, error_code):
        ledger = current_usage.get()
        if ledger is not None:
            ledger.start("answer_generation")
        method = getattr(type(self.provider), "generate_with_feedback", None)
        if method is None:
            return await self.provider.generate(question, context)
        return await method(self.provider, question, context, error_code)


class ObservedQueryProvider:
    def __init__(self, provider) -> None:
        self.provider = provider

    async def extract(self, question):
        ledger = current_usage.get()
        if ledger is not None:
            ledger.start("query_entity_extraction")
        return await self.provider.extract(question)


class ObservedRetriever:
    def __init__(self, service) -> None:
        self.service = service
        self.result = None
        self.latency_ms = None

    async def search(self, request):
        started = perf_counter()
        try:
            self.result = await self.service.search(request)
            return self.result
        finally:
            self.latency_ms = (perf_counter() - started) * 1000


class ObservedContextBuilder(ContextBuilder):
    def __init__(self, settings) -> None:
        super().__init__(settings)
        self.context: FusedContext | None = None

    def build(self, vector, graph, chunks):
        self.context = super().build(vector, graph, chunks)
        return self.context
