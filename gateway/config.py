import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ModelSpec:
    name: str
    provider: str
    upstream: str
    tier: int
    input_cost: float
    output_cost: float
    context_window: int = 128000
    mock: dict = field(default_factory=dict)

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.input_cost + output_tokens * self.output_cost) / 1_000_000


@dataclass
class RateLimitConfig:
    requests_per_minute: int = 120
    tokens_per_minute: int = 200000


@dataclass
class FallbackConfig:
    max_attempts: int = 3
    timeout_seconds: float = 30
    breaker_threshold: int = 3
    breaker_cooldown_seconds: float = 30


@dataclass
class Settings:
    models: list[ModelSpec]
    providers: dict[str, dict]
    baseline_model: str
    rate_limit: RateLimitConfig
    fallback: FallbackConfig
    tier_thresholds: tuple[float, float] = (0.12, 0.45)

    def model(self, name: str) -> ModelSpec:
        for m in self.models:
            if m.name == name:
                return m
        raise KeyError(name)

    @property
    def baseline(self) -> ModelSpec:
        return self.model(self.baseline_model)


def load_settings(path: str | os.PathLike | None = None) -> Settings:
    path = Path(path or os.getenv("GATEWAY_CONFIG", "config.yaml"))
    raw = yaml.safe_load(path.read_text())
    models = [ModelSpec(**m) for m in raw["models"]]
    thresholds = raw.get("routing", {}).get("tier_thresholds", [0.12, 0.45])
    return Settings(
        models=models,
        providers=raw.get("providers", {}),
        baseline_model=raw.get("baseline_model", max(models, key=lambda m: m.output_cost).name),
        rate_limit=RateLimitConfig(**raw.get("rate_limit", {})),
        fallback=FallbackConfig(**raw.get("fallback", {})),
        tier_thresholds=tuple(thresholds),
    )
