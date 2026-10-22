import argparse
import asyncio
import json
import random

from gateway.config import load_settings
from gateway.gateway import AllModelsFailed, Gateway
from gateway.providers import MockProvider

SIMPLE = [
    "Translate 'good morning, see you tomorrow' to Spanish.",
    "Summarize in one sentence: the meeting moved to Thursday at 3pm in room B.",
    "Classify the sentiment as positive or negative: 'Arrived late and broken.'",
    "Extract the email address from: contact jane.doe@example.com for details.",
    "Fix the typo: 'Teh quick brown fox'.",
    "List three synonyms for 'happy'.",
]
MEDIUM = [
    "Explain how HTTP caching headers like ETag and Cache-Control work together.",
    "Compare PostgreSQL and MongoDB for an e-commerce product catalog.",
    "Write a short product description for a waterproof 30L hiking backpack.",
    "Why does my React component re-render twice in development mode?",
    "Draft a polite email telling a customer their refund takes 5 business days.",
]
COMPLEX = [
    "Design a multi-region architecture for a payments service with 99.99% uptime. "
    "Analyze the trade-offs between active-active and active-passive and explain failover step by step.",
    "Debug and optimize this, then analyze the complexity:\n```python\ndef dedupe(items):\n"
    "    out = []\n    for i in items:\n        if i not in out:\n            out.append(i)\n    return out\n```",
    "Prove that the sum of the first n odd numbers is n^2, then derive a closed form for the sum of the first n squares and explain each step.",
    "Refactor this service to be testable and explain the design:\n```python\nclass OrderService:\n"
    "    def place(self, order):\n        db = connect()\n        db.save(order)\n```",
]


def workload(n, mix, seed=7):
    rng = random.Random(seed)
    for _ in range(n):
        pool = rng.choices([SIMPLE, MEDIUM, COMPLEX], weights=mix)[0]
        prompt = rng.choice(pool)
        if pool is COMPLEX and rng.random() < 0.5:
            prompt += "\nContext: " + "Service logs show intermittent timeouts under load. " * rng.randint(10, 60)
        yield [{"role": "user", "content": prompt}]


async def main(n, mix, speed):
    settings = load_settings("config.yaml")
    settings.requests_per_minute = 10**9
    gw = Gateway(settings, {"mock": MockProvider(seed=42, speed=speed)})
    sem = asyncio.Semaphore(50)

    async def one(messages):
        async with sem:
            try:
                await gw.complete(messages, "bench", max_tokens=800)
            except AllModelsFailed:
                pass

    await asyncio.gather(*(one(m) for m in workload(n, mix)))
    print(json.dumps(gw.metrics.snapshot(), indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("-n", type=int, default=2000)
    p.add_argument("--mix", default="0.60,0.25,0.15", help="simple,medium,complex share")
    p.add_argument("--speed", type=float, default=0.05, help="mock latency multiplier")
    a = p.parse_args()
    asyncio.run(main(a.n, [float(x) for x in a.mix.split(",")], a.speed))
