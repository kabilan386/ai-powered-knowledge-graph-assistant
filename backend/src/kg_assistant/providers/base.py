from typing import Protocol

from kg_assistant.models.extraction import ExtractionResult


class ExtractionProvider(Protocol):
    async def extract(self, text: str) -> ExtractionResult: ...

    async def close(self) -> None: ...


class ExtractionError(Exception):
    def __init__(self, code: str, retryable: bool = True) -> None:
        self.code = code
        self.retryable = retryable
        self.attempts = 0
        super().__init__(code)
