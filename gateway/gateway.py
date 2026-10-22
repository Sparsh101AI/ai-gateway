import asyncio
import time

from . import router
from .metrics import Metrics
from .providers import ProviderError
from .ratelimit import RateLimiter


class RateLimited(Exception):
    def __init__(self, retry_after):
        super().__init__(f"rate limited, retry in {retry_after}s")
        self.retry_after = retry_after


class AllModelsFailed(Exception):
    def __init__(self, errors):
        super().__init__("all upstream models failed")
        self.errors = errors


class Gateway:
    def __init__(self, settings, providers, metrics=None, clock=time.monotonic):
        self.settings = settings
        self.providers = providers
        self.metrics = metrics or Metrics()
        self.limiter = RateLimiter(settings.requests_per_minute, clock)
        self.clock = clock
        self.fail_streak = {}
        self.opened_at = {}

    def is_open(self, name):
        opened = self.opened_at.get(name)
        return opened is not None and self.clock() - opened < self.settings.breaker_cooldown_seconds

    def _failed(self, name):
        self.fail_streak[name] = self.fail_streak.get(name, 0) + 1
        if self.fail_streak[name] >= self.settings.breaker_threshold:
            self.opened_at[name] = self.clock()

    def _succeeded(self, name):
        self.fail_streak[name] = 0
        self.opened_at.pop(name, None)

    async def complete(self, messages, client="anonymous", max_tokens=512):
        if wait := self.limiter.acquire(client):
            self.metrics.record("rate_limited", client=client)
            raise RateLimited(wait)

        s = self.settings
        score = router.complexity(messages)
        models = [m for m in s.models if m.provider in self.providers]
        candidates = router.plan(models, score, s.tier_thresholds, self.is_open)[: s.max_attempts]

        errors = []
        start = time.perf_counter()
        for model in candidates:
            try:
                result = await asyncio.wait_for(
                    self.providers[model.provider].complete(model, messages, max_tokens), s.timeout_seconds
                )
            except (ProviderError, asyncio.TimeoutError) as e:
                self._failed(model.name)
                errors.append((model.name, str(e) or "timeout"))
                continue

            self._succeeded(model.name)
            latency = round((time.perf_counter() - start) * 1000, 1)
            cost = model.cost(result.input_tokens, result.output_tokens)
            baseline = s.baseline.cost(result.input_tokens, result.output_tokens)
            self.metrics.record(
                "ok", client=client, model=model.name, complexity=score, latency_ms=latency,
                input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                cost=cost, baseline_cost=baseline, errors=errors,
            )
            return {
                "model": model.name,
                "text": result.text,
                "usage": {"prompt_tokens": result.input_tokens, "completion_tokens": result.output_tokens},
                "gateway": {"complexity": score, "cost_usd": round(cost, 8), "baseline_cost_usd": round(baseline, 8),
                            "latency_ms": latency, "fallbacks": len(errors)},
            }

        self.metrics.record("failed", client=client, complexity=score, errors=errors)
        raise AllModelsFailed(errors)
