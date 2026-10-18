import asyncio
import random

from .base import Completion, ProviderError, estimate_tokens


class MockProvider:
    def __init__(self, seed: int | None = None, speed: float = 1.0):
        self.rng = random.Random(seed)
        self.speed = speed

    async def complete(self, model, messages, max_tokens):
        opts = model.mock or {}
        latency = opts.get("latency_ms", 200) / 1000
        await asyncio.sleep(self.rng.uniform(0.6, 1.4) * latency * self.speed)

        if self.rng.random() < opts.get("failure_rate", 0.0):
            raise ProviderError(f"{model.upstream}: upstream 503")

        prompt = " ".join(m.get("content", "") for m in messages)
        input_tokens = estimate_tokens(prompt)
        output_tokens = min(max_tokens, int(input_tokens * self.rng.uniform(0.8, 2.5)) + 20)
        return Completion(
            text=f"[{model.upstream}] response to: {prompt[:60]}",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
