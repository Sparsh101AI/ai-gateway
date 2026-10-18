import random

SIMPLE = [
    "Translate 'good morning, see you tomorrow' to Spanish.",
    "Summarize this in one sentence: the meeting moved to Thursday at 3pm in room B.",
    "Classify the sentiment of this review as positive or negative: 'Arrived late and broken.'",
    "Extract the email address from: contact jane.doe@example.com for details.",
    "Fix the typo: 'Teh quick brown fox'.",
    "List three synonyms for 'happy'.",
    "Format this date as ISO 8601: March 4th 2025.",
    "Answer yes or no: is 17 a prime number?",
]

MEDIUM = [
    "Explain how HTTP caching headers like ETag and Cache-Control work together.",
    "Compare PostgreSQL and MongoDB for an e-commerce product catalog.",
    "Write a short product description for a waterproof hiking backpack with 30L capacity, "
    "padded straps, and a laptop sleeve. Keep it under 120 words and friendly in tone.",
    "Why does my React component re-render twice in development mode?",
    "Draft a polite email to a customer explaining that their refund will take 5 business days.",
]

COMPLEX = [
    "Design a multi-region architecture for a payments service that needs 99.99% uptime. "
    "Analyze the trade-offs between active-active and active-passive, explain step by step "
    "how failover works, and compare costs.",
    "Debug this function and optimize it:\n```python\ndef dedupe(items):\n    out = []\n"
    "    for i in items:\n        if i not in out:\n            out.append(i)\n    return out\n```\n"
    "Explain why the original is slow and analyze the complexity.",
    "Prove that the sum of the first n odd numbers is n^2, then derive a closed form for the "
    "sum of the first n squares and explain each step.",
    "Refactor this service to be testable and explain the design strategy:\n```python\n"
    "class OrderService:\n    def place(self, order):\n        db = connect()\n"
    "        db.save(order)\n        send_email(order.user)\n```",
]


def generate(n: int, mix=(0.45, 0.30, 0.25), seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    pools = [SIMPLE, MEDIUM, COMPLEX]
    out = []
    for _ in range(n):
        pool = rng.choices(pools, weights=mix)[0]
        prompt = rng.choice(pool)
        if pool is COMPLEX and rng.random() < 0.5:
            prompt += "\n\nContext:\n" + ("Service logs show intermittent timeouts under load. " * rng.randint(10, 60))
        out.append({"messages": [{"role": "user", "content": prompt}], "max_tokens": 800})
    return out
