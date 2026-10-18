import asyncio
import time
from dataclasses import dataclass, field

from .config import FallbackConfig, ModelSpec
from .providers import Completion, Provider, ProviderError


class CircuitBreaker:
    def __init__(self, threshold: int, cooldown: float, clock=time.monotonic):
        self.threshold = threshold
        self.cooldown = cooldown
        self.clock = clock
        self.failures: dict[str, int] = {}
        self.opened_at: dict[str, float] = {}

    def available(self, name: str) -> bool:
        opened = self.opened_at.get(name)
        if opened is None:
            return True
        return self.clock() - opened >= self.cooldown

    def state(self, name: str) -> str:
        if name not in self.opened_at:
            return "closed"
        return "half_open" if self.available(name) else "open"

    def success(self, name: str):
        self.failures[name] = 0
        self.opened_at.pop(name, None)

    def failure(self, name: str):
        self.failures[name] = self.failures.get(name, 0) + 1
        if self.failures[name] >= self.threshold or name in self.opened_at:
            self.opened_at[name] = self.clock()


@dataclass
class Attempt:
    model: str
    ok: bool
    latency_ms: float
    error: str | None = None


@dataclass
class Outcome:
    model: ModelSpec | None
    completion: Completion | None
    attempts: list[Attempt] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.completion is not None


class FallbackExecutor:
    def __init__(self, providers: dict[str, Provider], config: FallbackConfig, breaker: CircuitBreaker):
        self.providers = providers
        self.config = config
        self.breaker = breaker

    async def run(self, plan: list[ModelSpec], messages: list[dict], max_tokens: int) -> Outcome:
        outcome = Outcome(model=None, completion=None)
        usable = [m for m in plan if m.provider in self.providers]

        for model in usable[: self.config.max_attempts]:
            if not self.breaker.available(model.name):
                outcome.attempts.append(Attempt(model.name, False, 0.0, "circuit open"))
                continue

            start = time.perf_counter()
            try:
                result = await asyncio.wait_for(
                    self.providers[model.provider].complete(model, messages, max_tokens),
                    timeout=self.config.timeout_seconds,
                )
            except (ProviderError, asyncio.TimeoutError) as e:
                elapsed = (time.perf_counter() - start) * 1000
                self.breaker.failure(model.name)
                outcome.attempts.append(Attempt(model.name, False, elapsed, str(e) or type(e).__name__))
                if isinstance(e, ProviderError) and not e.retryable:
                    break
                continue

            elapsed = (time.perf_counter() - start) * 1000
            self.breaker.success(model.name)
            outcome.attempts.append(Attempt(model.name, True, elapsed))
            outcome.model = model
            outcome.completion = result
            break

        return outcome
