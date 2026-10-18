# Cost-Efficient AI Gateway

A gateway that handles LLM requests. It sends each prompt to the cheapest model that can do the job, rate-limits each client, and falls back to another model when an upstream fails. An observability pipeline tracks latency, token use, cost and failures.

**Stack:** Python · FastAPI · LLM routing · Observability (Prometheus metrics + JSONL request logs)

## How it works

```
client ──► rate limiter ──► router ──► fallback executor ──► provider (OpenAI / Anthropic / mock)
              │                │               │
              └────────────────┴───────────────┴──► metrics + request log  ──►  /stats  /metrics
```

| Component | File | What it does |
|---|---|---|
| **Router** | `gateway/router.py` | Gives each prompt a complexity score from 0 to 1, based on length, reasoning keywords ("analyze", "prove", "design"…), code blocks and conversation depth. The score maps to a tier (1 = small, 2 = medium, 3 = large), and the cheapest model in that tier is tried first. Clients can force a tier with `quality` or pin a specific `model`. |
| **Rate limiter** | `gateway/ratelimit.py` | Two token buckets per client (keyed by the `X-Client-Id` header): requests per minute and tokens per minute. The token estimate is corrected to actual usage once the response arrives. Returns `429` with `Retry-After`. |
| **Fallback + circuit breaker** | `gateway/fallback.py` | Works through the routing plan: same-tier alternatives first, then higher tiers, then lower tiers as a last resort. Each attempt has a timeout. After N failures in a row a model's circuit opens, the router skips it, and after a cooldown it gets one trial request. Errors that retrying won't fix (for example a 400) stop the chain. |
| **Observability** | `gateway/observability.py` | Counts requests, failures, fallbacks and rate-limit hits; tracks tokens and cost per model; keeps a latency histogram and p50/p95/p99. Compares the cost against a baseline of sending everything to the most expensive model. Writes every request to `logs/requests.jsonl`. |
| **Providers** | `gateway/providers/` | OpenAI-compatible (`/chat/completions`), Anthropic (`/messages`), and a mock provider with configurable latency and failure rate, so the project runs without API keys. |

## Results

`bench/run.py` sends a synthetic workload of simple, medium and complex prompts through the gateway. It compares the routed cost with sending everything to the `large` model (2,000 requests, mock providers, prices from `config.yaml`):

| Traffic mix (simple / medium / complex) | Baseline cost | Routed cost | Savings |
|---|---|---|---|
| 60 / 25 / 15 | $3.40 | $2.25 | **33.8%** |
| 55 / 25 / 20 | $4.05 | $2.95 | **27.1%** |
| 45 / 30 / 25 | $4.67 | $3.54 | **24.1%** |

Savings depend mostly on how much of your traffic is simple. Complex prompts still go to the large model on purpose. With 2–5% simulated upstream failure rates, fallback brought requests that failed completely down to 0.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Run the tests:

```bash
pytest -q
```

Run the cost benchmark:

```bash
python bench/run.py -n 2000 --mix 0.60,0.25,0.15
```

Start the gateway (uses the mock models by default, no keys needed):

```bash
uvicorn gateway.app:create_app --factory --port 8000
```

Send a request:

```bash
curl localhost:8000/v1/chat/completions \
  -H 'content-type: application/json' -H 'X-Client-Id: team-a' \
  -d '{"messages":[{"role":"user","content":"Translate hello to Spanish"}]}'
```

The response follows the OpenAI chat format, plus a `gateway` block:

```json
"gateway": {"complexity": 0.0, "cost_usd": 1.89e-05, "baseline_cost_usd": 0.000468,
            "latency_ms": 91.2, "attempts": [{"model": "small", "ok": true, ...}]}
```

Request options: `model` (`"auto"` or a model name from config), `quality` (`low` / `medium` / `high`), `max_tokens`.

## Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/v1/chat/completions` | Routed chat completion |
| GET | `/health` | Circuit breaker state per model (`closed` / `open` / `half_open`) |
| GET | `/stats` | JSON summary: latency percentiles, tokens, cost, savings, per-model breakdown |
| GET | `/metrics` | Prometheus format, ready to scrape (counters + latency histogram) |

## Using real models

1. Copy `.env.example` to `.env` and fill in your keys. `.env` is gitignored, so **never commit keys**.
2. In `config.yaml`, add models under the `openai` or `anthropic` provider (there's a commented example). Set the `tier` and per-million-token `input_cost` / `output_cost` for each one.
3. Export the variables and start the server:

```bash
set -a && source .env && set +a
uvicorn gateway.app:create_app --factory --port 8000
```

A provider whose key variable isn't set is skipped, and the router falls through to the remaining models.

## Configuration

Everything lives in `config.yaml`: models and prices, `baseline_model` (used for the savings comparison), rate limits, fallback attempts and timeouts, circuit breaker threshold and cooldown, and the routing `tier_thresholds`. Use a different file with `GATEWAY_CONFIG=path.yaml`.

## Project layout

```
gateway/
  app.py            FastAPI app and endpoints
  core.py           ties rate limiting, routing, fallback and metrics together
  router.py         complexity scoring and model selection
  ratelimit.py      per-client token buckets
  fallback.py       retry chain and circuit breaker
  observability.py  metrics, Prometheus export, JSONL log
  providers/        openai, anthropic, mock
bench/              workload generator and cost benchmark
tests/              unit and API tests
```
