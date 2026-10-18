from dataclasses import dataclass
from typing import Protocol


class ProviderError(Exception):
    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class Completion:
    text: str
    input_tokens: int
    output_tokens: int


class Provider(Protocol):
    async def complete(self, model, messages: list[dict], max_tokens: int) -> Completion: ...


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)
