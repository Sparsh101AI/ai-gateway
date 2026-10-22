# Cost-Efficient AI Gateway

A small gateway for LLM requests. It sends each prompt to the cheapest model that can handle it, rate-limits each client, and falls back to another model when one fails. It also tracks latency, tokens, cost and failures.

**Stack:** Python · FastAPI · LLM routing · Observability

## How it works

```
request ─► rate limiter ─► router ─► try models in order (fallback + circuit breaker) ─► metrics / log
```

| File | What it does |
|---|---|
| `gateway/router.py` | Scores each prompt from 0 to 1 using its length, keywords ("analyze", "prove", "design" raise the score; "translate", "summarize" lower it) and code blocks. The score picks a tier (small / medium / large). Models are tried cheapest first: same tier, then higher tiers, then lower tiers as a last resort. |
| `gateway/ratelimit.py` | Per-client token bucket (requests per minute), keyed by the `X-Client-Id` header. Returns `429` with `Retry-After`. |
| `gateway/gateway.py` | Runs the request: rate limit → route → call models in order with a timeout. After 3 failures in a row a model is skipped for 30 seconds (circuit breaker). |
| `gateway/metrics.py` | Counts requests, failures and fallbacks; tracks tokens, cost and p50/p95 latency; compares cost against sending everything to the most expensive model. Writes every request to `logs/requests.jsonl`. |
| `gateway/providers.py` | A mock provider (simulated latency and failures, so it runs without keys) and an OpenAI-compatible provider. |
| `gateway/app.py` | HTTP API. |

## Results

`bench.py` sends 2,000 simple, medium and complex prompts through the gateway and compares the cost against sending everything to the `large` model:

| Traffic mix (simple / medium / complex) | Savings |
|---|---|
| 60 / 25 / 15 | **35.6%** |
| 55 / 25 / 20 | **28.5%** |
| 45 / 30 / 25 | **23.7%** |

How much you save depends on how much of your traffic is simple. With 2–5% simulated upstream failures, fallback still served all 2,000 requests.

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

pytest -q                                   # tests
python bench.py --mix 0.60,0.25,0.15        # cost benchmark
uvicorn gateway.app:create_app --factory    # start the server on :8000
```

```bash
curl localhost:8000/v1/chat/completions -H 'content-type: application/json' \
  -d '{"messages":[{"role":"user","content":"Translate hello to Spanish"}]}'
```

The response includes the model used, token usage, cost, baseline cost, latency and the number of fallbacks.

| Endpoint | |
|---|---|
| `POST /v1/chat/completions` | Routed chat completion |
| `GET /health` | Circuit breaker state per model |
| `GET /stats` | Latency, tokens, cost, savings, per-model breakdown |

## Using real models

1. Copy `.env.example` to `.env` and add your key. `.env` is gitignored, so **never commit keys**.
2. Add models to `config.yaml` with `provider: openai` (there's a commented example), giving each a tier and its per-million-token prices.
3. Load the keys and start the server:

```bash
set -a && source .env && set +a
uvicorn gateway.app:create_app --factory
```

All settings (models, prices, rate limit, fallback, breaker, routing thresholds) live in `config.yaml`.
