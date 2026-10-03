from collections.abc import Callable

from pydantic import BaseModel, Field


class TokenUsage(BaseModel):
    prompt_tokens: int = Field(ge=0, strict=True)
    completion_tokens: int = Field(ge=0, strict=True)
    total_tokens: int = Field(ge=0, strict=True)


UsageObserver = Callable[[TokenUsage | None], None]


def observe_usage(response: object, observer: UsageObserver | None) -> None:
    if observer is None:
        return
    usage = getattr(response, "usage", None)
    values = [
        getattr(usage, key, None) for key in ("input_tokens", "output_tokens", "total_tokens")
    ]
    if any(type(value) is not int or value < 0 for value in values):
        observer(None)
        return
    observer(
        TokenUsage(prompt_tokens=values[0], completion_tokens=values[1], total_tokens=values[2])
    )
