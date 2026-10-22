import json
import time
from collections import Counter, defaultdict
from pathlib import Path


def percentile(values, p):
    if not values:
        return 0.0
    values = sorted(values)
    return round(values[min(len(values) - 1, int(len(values) * p))], 1)


class Metrics:
    def __init__(self, log_path=None):
        self.latencies = []
        self.counts = Counter()
        self.failures = Counter()
        self.by_model = defaultdict(Counter)
        self.cost = 0.0
        self.baseline_cost = 0.0
        self.log_path = Path(log_path) if log_path else None
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, event, **data):
        self.counts[event] += 1
        for name, error in data.get("errors", []):
            self.failures[name] += 1
        if event == "ok":
            m = self.by_model[data["model"]]
            m["requests"] += 1
            m["input_tokens"] += data["input_tokens"]
            m["output_tokens"] += data["output_tokens"]
            self.cost += data["cost"]
            self.baseline_cost += data["baseline_cost"]
            self.latencies.append(data["latency_ms"])
        if self.log_path:
            with self.log_path.open("a") as f:
                f.write(json.dumps({"ts": time.time(), "event": event, **data}) + "\n")

    def snapshot(self):
        saved = 1 - self.cost / self.baseline_cost if self.baseline_cost else 0.0
        return {
            "requests": dict(self.counts),
            "latency_ms": {"p50": percentile(self.latencies, 0.5), "p95": percentile(self.latencies, 0.95)},
            "tokens": {
                "input": sum(m["input_tokens"] for m in self.by_model.values()),
                "output": sum(m["output_tokens"] for m in self.by_model.values()),
            },
            "cost_usd": {"actual": round(self.cost, 6), "baseline": round(self.baseline_cost, 6),
                         "savings_pct": round(saved * 100, 2)},
            "by_model": {k: dict(v) for k, v in self.by_model.items()},
            "upstream_failures": dict(self.failures),
        }
