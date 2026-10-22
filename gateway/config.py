import os
from dataclasses import dataclass

import yaml


@dataclass
class Model:
    name: str
    provider: str
    tier: int
    input_cost: float
    output_cost: float
    latency_ms: int = 200
    failure_rate: float = 0.0

    def cost(self, input_tokens, output_tokens):
        return (input_tokens * self.input_cost + output_tokens * self.output_cost) / 1_000_000


@dataclass
class Settings:
    models: list
    baseline_model: str = "large"
    requests_per_minute: int = 120
    max_attempts: int = 3
    timeout_seconds: float = 30
    breaker_threshold: int = 3
    breaker_cooldown_seconds: float = 30
    tier_thresholds: tuple = (0.12, 0.45)

    @property
    def baseline(self):
        return next(m for m in self.models if m.name == self.baseline_model)


def load_settings(path=None):
    with open(path or os.getenv("GATEWAY_CONFIG", "config.yaml")) as f:
        raw = yaml.safe_load(f)
    raw["models"] = [Model(**m) for m in raw["models"]]
    return Settings(**raw)
