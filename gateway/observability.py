import json
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

LATENCY_BUCKETS = [50, 100, 250, 500, 1000, 2500, 5000, 10000]


def percentile(values, p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo), 2)


class Metrics:
    def __init__(self, log_path: str | None = None, window: int = 5000):
        self.lock = threading.Lock()
        self.started = time.time()
        self.requests = defaultdict(int)
        self.failures = defaultdict(int)
        self.fallbacks = 0
        self.rate_limited = 0
        self.input_tokens = defaultdict(int)
        self.output_tokens = defaultdict(int)
        self.cost = defaultdict(float)
        self.baseline_cost = 0.0
        self.latency_hist = defaultdict(lambda: [0] * (len(LATENCY_BUCKETS) + 1))
        self.latency_sum = defaultdict(float)
        self.recent_latency = deque(maxlen=window)
        self.log_path = Path(log_path) if log_path else None
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def _observe_latency(self, model: str, ms: float):
        idx = next((i for i, b in enumerate(LATENCY_BUCKETS) if ms <= b), len(LATENCY_BUCKETS))
        self.latency_hist[model][idx] += 1
        self.latency_sum[model] += ms
        self.recent_latency.append(ms)

    def record_rate_limited(self, client: str):
        with self.lock:
            self.rate_limited += 1
        self._log({"event": "rate_limited", "client": client})

    def record(self, *, request_id, client, score, outcome, latency_ms, cost, baseline_cost):
        with self.lock:
            for a in outcome.attempts:
                if not a.ok and a.error != "circuit open":
                    self.failures[a.model] += 1
            if len([a for a in outcome.attempts if a.error != "circuit open"]) > 1:
                self.fallbacks += 1

            if outcome.ok:
                name = outcome.model.name
                self.requests[name] += 1
                self.input_tokens[name] += outcome.completion.input_tokens
                self.output_tokens[name] += outcome.completion.output_tokens
                self.cost[name] += cost
                self.baseline_cost += baseline_cost
                self._observe_latency(name, latency_ms)
            else:
                self.requests["_failed"] += 1

        self._log({
            "event": "request",
            "id": request_id,
            "client": client,
            "complexity": score,
            "model": outcome.model.name if outcome.ok else None,
            "ok": outcome.ok,
            "latency_ms": round(latency_ms, 1),
            "input_tokens": outcome.completion.input_tokens if outcome.ok else 0,
            "output_tokens": outcome.completion.output_tokens if outcome.ok else 0,
            "cost_usd": round(cost, 6),
            "attempts": [a.__dict__ for a in outcome.attempts],
        })

    def _log(self, record: dict):
        if not self.log_path:
            return
        record["ts"] = time.time()
        with self.lock, self.log_path.open("a") as f:
            f.write(json.dumps(record) + "\n")

    def snapshot(self) -> dict:
        with self.lock:
            total_cost = sum(self.cost.values())
            served = sum(v for k, v in self.requests.items() if k != "_failed")
            savings = 1 - total_cost / self.baseline_cost if self.baseline_cost else 0.0
            return {
                "uptime_s": round(time.time() - self.started, 1),
                "requests": {"served": served, "failed": self.requests.get("_failed", 0),
                             "rate_limited": self.rate_limited, "fallbacks": self.fallbacks},
                "latency_ms": {"p50": percentile(self.recent_latency, 0.5),
                               "p95": percentile(self.recent_latency, 0.95),
                               "p99": percentile(self.recent_latency, 0.99)},
                "tokens": {"input": sum(self.input_tokens.values()), "output": sum(self.output_tokens.values())},
                "cost_usd": {"actual": round(total_cost, 6), "baseline": round(self.baseline_cost, 6),
                             "savings_pct": round(savings * 100, 2)},
                "by_model": {
                    m: {"requests": n, "failures": self.failures.get(m, 0), "cost_usd": round(self.cost[m], 6),
                        "input_tokens": self.input_tokens[m], "output_tokens": self.output_tokens[m]}
                    for m, n in self.requests.items() if m != "_failed"
                },
                "upstream_failures": dict(self.failures),
            }

    def prometheus(self) -> str:
        lines = []
        with self.lock:
            lines.append("# TYPE gateway_requests_total counter")
            for m, n in self.requests.items():
                lines.append(f'gateway_requests_total{{model="{m}"}} {n}')
            lines.append("# TYPE gateway_upstream_failures_total counter")
            for m, n in self.failures.items():
                lines.append(f'gateway_upstream_failures_total{{model="{m}"}} {n}')
            lines.append(f"gateway_fallbacks_total {self.fallbacks}")
            lines.append(f"gateway_rate_limited_total {self.rate_limited}")
            lines.append("# TYPE gateway_tokens_total counter")
            for m in self.input_tokens:
                lines.append(f'gateway_tokens_total{{model="{m}",kind="input"}} {self.input_tokens[m]}')
                lines.append(f'gateway_tokens_total{{model="{m}",kind="output"}} {self.output_tokens[m]}')
            lines.append("# TYPE gateway_cost_usd_total counter")
            for m, c in self.cost.items():
                lines.append(f'gateway_cost_usd_total{{model="{m}"}} {c:.6f}')
            lines.append(f"gateway_baseline_cost_usd_total {self.baseline_cost:.6f}")
            lines.append("# TYPE gateway_latency_ms histogram")
            for m, counts in self.latency_hist.items():
                running = 0
                for bound, c in zip(LATENCY_BUCKETS, counts):
                    running += c
                    lines.append(f'gateway_latency_ms_bucket{{model="{m}",le="{bound}"}} {running}')
                running += counts[-1]
                lines.append(f'gateway_latency_ms_bucket{{model="{m}",le="+Inf"}} {running}')
                lines.append(f'gateway_latency_ms_sum{{model="{m}"}} {self.latency_sum[m]:.1f}')
                lines.append(f'gateway_latency_ms_count{{model="{m}"}} {running}')
        return "\n".join(lines) + "\n"
