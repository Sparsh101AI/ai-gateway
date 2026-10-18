import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gateway.app import create_app
from gateway.config import load_settings
from gateway.core import AllModelsFailed, Gateway, RateLimited
from gateway.fallback import CircuitBreaker
from gateway.observability import Metrics
from gateway.providers import Completion, ProviderError
from gateway.ratelimit import RateLimiter
from gateway.router import Router, complexity

CONFIG = Path(__file__).resolve().parent.parent / "config.yaml"


def msg(text):
    return [{"role": "user", "content": text}]


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class ScriptedProvider:
    def __init__(self, fail_models=()):
        self.fail_models = set(fail_models)
        self.calls = []

    async def complete(self, model, messages, max_tokens):
        self.calls.append(model.name)
        if model.name in self.fail_models:
            raise ProviderError(f"{model.name} down")
        return Completion(text="ok", input_tokens=100, output_tokens=200)


@pytest.fixture
def settings():
    return load_settings(CONFIG)


def run(coro):
    return asyncio.run(coro)


def test_simple_prompts_score_low_and_complex_high():
    assert complexity(msg("Translate 'hello' to French.")) < 0.12
    hard = "Design a distributed cache, analyze the trade-offs and explain step by step.\n```python\nclass X: pass\n```"
    assert complexity(msg(hard)) >= 0.45


def test_router_picks_cheapest_model_in_tier(settings):
    plan, _ = Router(settings).plan(msg("Summarize: the cat sat on the mat."))
    assert plan[0].name == "small"
    assert [m.name for m in plan[:2]] == ["small", "small-backup"]


def test_quality_hint_overrides_score(settings):
    plan, _ = Router(settings).plan(msg("hi"), quality="high")
    assert plan[0].name == "large"


def test_router_skips_open_circuits(settings):
    plan, _ = Router(settings, is_available=lambda n: n != "small").plan(msg("List three colors."))
    assert plan[0].name == "small-backup"


def test_fallback_moves_to_next_model(settings):
    provider = ScriptedProvider(fail_models={"small"})
    gw = Gateway(settings, {"mock": provider})
    res = run(gw.complete(msg("Translate 'yes' to German.")))
    assert res.model == "small-backup"
    assert provider.calls == ["small", "small-backup"]
    assert gw.metrics.snapshot()["requests"]["fallbacks"] == 1


def test_all_models_failing_raises(settings):
    gw = Gateway(settings, {"mock": ScriptedProvider(fail_models={"small", "small-backup", "medium", "large"})})
    with pytest.raises(AllModelsFailed):
        run(gw.complete(msg("hi")))
    assert gw.metrics.snapshot()["requests"]["failed"] == 1


def test_circuit_breaker_opens_and_recovers():
    clock = FakeClock()
    cb = CircuitBreaker(threshold=2, cooldown=10, clock=clock)
    cb.failure("m")
    assert cb.available("m")
    cb.failure("m")
    assert not cb.available("m") and cb.state("m") == "open"
    clock.t = 11
    assert cb.state("m") == "half_open"
    cb.success("m")
    assert cb.state("m") == "closed"


def test_rate_limiter_blocks_then_refills():
    clock = FakeClock()
    rl = RateLimiter(requests_per_minute=2, tokens_per_minute=10_000, clock=clock)
    assert rl.acquire("a", 10) == 0
    assert rl.acquire("a", 10) == 0
    assert rl.acquire("a", 10) > 0
    assert rl.acquire("b", 10) == 0
    clock.t = 30
    assert rl.acquire("a", 10) == 0


def test_gateway_raises_when_rate_limited(settings):
    settings.rate_limit.requests_per_minute = 1
    gw = Gateway(settings, {"mock": ScriptedProvider()})
    run(gw.complete(msg("hi"), client="c1"))
    with pytest.raises(RateLimited):
        run(gw.complete(msg("hi"), client="c1"))
    assert gw.metrics.snapshot()["requests"]["rate_limited"] == 1


def test_cost_and_savings_tracked(settings):
    gw = Gateway(settings, {"mock": ScriptedProvider()})
    res = run(gw.complete(msg("Classify: great product!")))
    small, large = settings.model("small"), settings.model("large")
    assert res.cost_usd == pytest.approx(small.cost(100, 200))
    assert res.baseline_cost_usd == pytest.approx(large.cost(100, 200))
    assert gw.metrics.snapshot()["cost_usd"]["savings_pct"] > 90


def test_http_api_and_metrics(settings, tmp_path):
    gw = Gateway(settings, {"mock": ScriptedProvider()}, Metrics(log_path=tmp_path / "log.jsonl"))
    client = TestClient(create_app(gw))

    r = client.post("/v1/chat/completions", json={"messages": msg("Translate 'cat' to Spanish.")},
                    headers={"X-Client-Id": "tester"})
    assert r.status_code == 200
    body = r.json()
    assert body["model"] == "small"
    assert body["usage"] == {"prompt_tokens": 100, "completion_tokens": 200}

    assert client.get("/health").json()["models"]["small"] == "closed"
    assert client.get("/stats").json()["requests"]["served"] == 1
    prom = client.get("/metrics").text
    assert 'gateway_requests_total{model="small"} 1' in prom
    assert "gateway_latency_ms_bucket" in prom
    assert (tmp_path / "log.jsonl").read_text().count('"event": "request"') == 1

    assert client.post("/v1/chat/completions", json={"messages": msg("x"), "model": "nope"}).status_code == 400
