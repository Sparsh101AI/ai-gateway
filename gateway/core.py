import time
import uuid
from dataclasses import dataclass

from .config import Settings
from .fallback import CircuitBreaker, FallbackExecutor, Outcome
from .observability import Metrics
from .providers import Provider
from .providers.base import estimate_tokens
from .ratelimit import RateLimiter
from .router import Router


class RateLimited(Exception):
    def __init__(self, retry_after: float):
        super().__init__(f"rate limited, retry in {retry_after}s")
        self.retry_after = retry_after


class AllModelsFailed(Exception):
    def __init__(self, outcome: Outcome):
        super().__init__("all upstream models failed")
        self.outcome = outcome


@dataclass
class GatewayResponse:
    id: str
    model: str
    text: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    baseline_cost_usd: float
    complexity: float
    latency_ms: float
    attempts: list


class Gateway:
    def __init__(self, settings: Settings, providers: dict[str, Provider], metrics: Metrics | None = None):
        self.settings = settings
        self.breaker = CircuitBreaker(settings.fallback.breaker_threshold, settings.fallback.breaker_cooldown_seconds)
        self.router = Router(settings, is_available=self.breaker.available)
        self.limiter = RateLimiter(settings.rate_limit.requests_per_minute, settings.rate_limit.tokens_per_minute)
        self.executor = FallbackExecutor(providers, settings.fallback, self.breaker)
        self.metrics = metrics or Metrics()

    async def complete(self, messages: list[dict], *, client: str = "anonymous", model: str = "auto",
                       quality: str | None = None, max_tokens: int = 512) -> GatewayResponse:
        request_id = uuid.uuid4().hex[:12]
        estimated = estimate_tokens(" ".join(m.get("content", "") for m in messages)) + max_tokens

        wait = self.limiter.acquire(client, estimated)
        if wait:
            self.metrics.record_rate_limited(client)
            raise RateLimited(wait)

        plan, score = self.router.plan(messages, model=model, quality=quality)
        start = time.perf_counter()
        outcome = await self.executor.run(plan, messages, max_tokens)
        latency = (time.perf_counter() - start) * 1000

        cost = baseline = 0.0
        if outcome.ok:
            c = outcome.completion
            cost = outcome.model.cost(c.input_tokens, c.output_tokens)
            baseline = self.settings.baseline.cost(c.input_tokens, c.output_tokens)
            self.limiter.settle(client, estimated, c.input_tokens + c.output_tokens)

        self.metrics.record(request_id=request_id, client=client, score=score, outcome=outcome,
                            latency_ms=latency, cost=cost, baseline_cost=baseline)

        if not outcome.ok:
            raise AllModelsFailed(outcome)

        return GatewayResponse(
            id=request_id,
            model=outcome.model.name,
            text=outcome.completion.text,
            input_tokens=outcome.completion.input_tokens,
            output_tokens=outcome.completion.output_tokens,
            cost_usd=round(cost, 8),
            baseline_cost_usd=round(baseline, 8),
            complexity=score,
            latency_ms=round(latency, 1),
            attempts=[a.__dict__ for a in outcome.attempts],
        )

    def health(self) -> dict:
        return {m.name: self.breaker.state(m.name) for m in self.settings.models}
