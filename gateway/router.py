import re

from .config import ModelSpec, Settings
from .providers.base import estimate_tokens

HARD_PATTERNS = [
    r"\bprove\b", r"\bderive\b", r"\barchitect", r"\brefactor\b", r"\boptimi[sz]e\b",
    r"\bdebug\b", r"\bstep[- ]by[- ]step\b", r"\btrade-?offs?\b", r"\banaly[sz]e\b",
    r"\bcompare\b", r"\bdesign\b", r"\bwhy\b", r"\bexplain\b", r"\bstrategy\b",
]
EASY_PATTERNS = [
    r"\btranslate\b", r"\bsummari[sz]e\b", r"\bclassify\b", r"\bextract\b",
    r"\bfix (the )?typo", r"\bformat\b", r"\byes or no\b", r"\bone word\b", r"\blist\b",
]
OPEN_ENDED_PATTERNS = [r"\bwrite\b", r"\bdraft\b", r"\bdescribe\b", r"\bhow\b"]
QUALITY_TIER = {"low": 1, "medium": 2, "high": 3}


def complexity(messages: list[dict]) -> float:
    text = "\n".join(m.get("content", "") for m in messages)
    lower = text.lower()
    tokens = estimate_tokens(text)

    score = min(tokens / 2000, 1.0) * 0.35
    score += min(sum(bool(re.search(p, lower)) for p in HARD_PATTERNS) * 0.15, 0.45)
    score += min(sum(bool(re.search(p, lower)) for p in OPEN_ENDED_PATTERNS) * 0.15, 0.3)
    score -= min(sum(bool(re.search(p, lower)) for p in EASY_PATTERNS) * 0.12, 0.25)
    if "```" in text or re.search(r"\bdef |\bclass |function\s*\(|SELECT .* FROM", text):
        score += 0.2
    if len(messages) > 6:
        score += 0.1
    return round(max(0.0, min(score, 1.0)), 3)


class Router:
    def __init__(self, settings: Settings, is_available=lambda name: True):
        self.settings = settings
        self.is_available = is_available

    def tier_for(self, score: float) -> int:
        low, high = self.settings.tier_thresholds
        if score < low:
            return 1
        if score < high:
            return 2
        return 3

    def plan(self, messages: list[dict], model: str = "auto", quality: str | None = None) -> tuple[list[ModelSpec], float]:
        score = complexity(messages)
        prompt_tokens = estimate_tokens(" ".join(m.get("content", "") for m in messages))
        candidates = [m for m in self.settings.models if m.context_window >= prompt_tokens]

        if model != "auto":
            pinned = self.settings.model(model)
            rest = sorted(
                (m for m in candidates if m.tier >= pinned.tier and m.name != pinned.name),
                key=lambda m: (m.tier, m.output_cost),
            )
            return [pinned, *rest], score

        tier = QUALITY_TIER.get(quality) or self.tier_for(score)
        ordered = sorted(
            (m for m in candidates if m.tier >= tier),
            key=lambda m: (m.tier, m.output_cost, m.input_cost),
        )
        ordered += sorted(
            (m for m in candidates if m.tier < tier),
            key=lambda m: (-m.tier, m.output_cost),
        )
        healthy = [m for m in ordered if self.is_available(m.name)]
        degraded = [m for m in ordered if not self.is_available(m.name)]
        return healthy + degraded, score
