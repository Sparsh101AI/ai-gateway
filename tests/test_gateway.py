import asyncio

import pytest
from fastapi.testclient import TestClient

from gateway.app import create_app
from gateway.config import load_settings
from gateway.gateway import AllModelsFailed, Gateway, RateLimited
from gateway.providers import Completion, ProviderError
from gateway.ratelimit import RateLimiter
from gateway.router import complexity


def msg(text):
    return [{"role": "user", "content": text}]


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


class FakeProvider:
    def __init__(self, down=()):
        self.down = set(down)
        self.calls = []

    async def complete(self, model, messages, max_tokens):
        self.calls.append(model.name)
        if model.name in self.down:
            raise ProviderError("down")
        return Completion("ok", 100, 200)


@pytest.fixture
def settings():
    return load_settings("config.yaml")


def test_complexity_scores():
    assert complexity(msg("Translate 'hello' to French.")) < 0.12
    assert complexity(msg("Explain how DNS works.")) < 0.45
    hard = "Design a cache, analyze the trade-offs, explain step by step.\n```python\nclass X: pass\n```"
    assert complexity(msg(hard)) >= 0.45


def test_simple_prompt_uses_cheapest_model(settings):
    res = asyncio.run(Gateway(settings, {"mock": FakeProvider()}).complete(msg("Summarize: the cat sat.")))
    assert res["model"] == "small"
    assert res["gateway"]["cost_usd"] < res["gateway"]["baseline_cost_usd"]


def test_fallback_to_next_model(settings):
    provider = FakeProvider(down={"small"})
    res = asyncio.run(Gateway(settings, {"mock": provider}).complete(msg("Translate 'yes' to German.")))
    assert provider.calls == ["small", "small-backup"]
    assert res["gateway"]["fallbacks"] == 1


def test_all_models_down(settings):
    gw = Gateway(settings, {"mock": FakeProvider(down={"small", "small-backup", "medium", "large"})})
    with pytest.raises(AllModelsFailed):
        asyncio.run(gw.complete(msg("hi")))


def test_circuit_breaker_skips_failing_model(settings):
    clock = Clock()
    provider = FakeProvider(down={"small"})
    gw = Gateway(settings, {"mock": provider}, clock=clock)
    for _ in range(settings.breaker_threshold):
        asyncio.run(gw.complete(msg("hi")))
    assert gw.is_open("small")
    provider.calls.clear()
    asyncio.run(gw.complete(msg("hi")))
    assert provider.calls[0] == "small-backup"
    clock.t = settings.breaker_cooldown_seconds + 1
    assert not gw.is_open("small")


def test_rate_limiter():
    clock = Clock()
    rl = RateLimiter(2, clock)
    assert rl.acquire("a") == 0 and rl.acquire("a") == 0
    assert rl.acquire("a") > 0
    assert rl.acquire("b") == 0
    clock.t = 30
    assert rl.acquire("a") == 0


def test_http_api(settings):
    settings.requests_per_minute = 1
    client = TestClient(create_app(Gateway(settings, {"mock": FakeProvider()})))
    r = client.post("/v1/chat/completions", json={"messages": msg("Translate 'cat' to Spanish.")})
    assert r.status_code == 200 and r.json()["model"] == "small"
    assert client.post("/v1/chat/completions", json={"messages": msg("again")}).status_code == 429
    assert client.get("/health").json()["small"] == "ok"
    assert client.get("/stats").json()["requests"] == {"ok": 1, "rate_limited": 1}
