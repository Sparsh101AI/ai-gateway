import asyncio
import os
import random
from dataclasses import dataclass

import httpx


class ProviderError(Exception):
    pass


@dataclass
class Completion:
    text: str
    input_tokens: int
    output_tokens: int


def estimate_tokens(text):
    return max(1, len(text) // 4)


class MockProvider:
    def __init__(self, seed=None, speed=1.0):
        self.rng = random.Random(seed)
        self.speed = speed

    async def complete(self, model, messages, max_tokens):
        await asyncio.sleep(model.latency_ms / 1000 * self.rng.uniform(0.6, 1.4) * self.speed)
        if self.rng.random() < model.failure_rate:
            raise ProviderError(f"{model.name}: upstream 503")
        prompt = " ".join(m["content"] for m in messages)
        tokens_in = estimate_tokens(prompt)
        tokens_out = min(max_tokens, int(tokens_in * self.rng.uniform(0.8, 2.5)) + 20)
        return Completion(f"[{model.name}] {prompt[:60]}", tokens_in, tokens_out)


class OpenAIProvider:
    def __init__(self, api_key, base_url="https://api.openai.com/v1"):
        self.client = httpx.AsyncClient(base_url=base_url, headers={"Authorization": f"Bearer {api_key}"})

    async def complete(self, model, messages, max_tokens):
        try:
            r = await self.client.post("/chat/completions", json={
                "model": model.name, "messages": messages, "max_tokens": max_tokens,
            })
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise ProviderError(str(e)) from e
        data = r.json()
        return Completion(
            data["choices"][0]["message"]["content"],
            data["usage"]["prompt_tokens"],
            data["usage"]["completion_tokens"],
        )


def default_providers():
    providers = {"mock": MockProvider()}
    if key := os.getenv("OPENAI_API_KEY"):
        providers["openai"] = OpenAIProvider(key, os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    return providers
