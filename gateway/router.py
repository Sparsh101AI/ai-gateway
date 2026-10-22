import re

from .providers import estimate_tokens

SIGNALS = {
    r"\b(prove|derive|architect\w*|refactor|optimi[sz]e|debug|analy[sz]e|compare|design|why|explain|strategy)\b": 0.15,
    r"\bstep[- ]by[- ]step|trade-?offs?\b": 0.15,
    r"\b(write|draft|describe|how)\b": 0.15,
    r"\b(translate|summari[sz]e|classify|extract|format|list)\b|yes or no|typo": -0.12,
    r"```|\bdef |\bclass ": 0.2,
}


def complexity(messages):
    text = " ".join(m["content"] for m in messages).lower()
    score = min(estimate_tokens(text) / 2000, 1.0) * 0.35
    for pattern, weight in SIGNALS.items():
        score += weight * min(len(re.findall(pattern, text)), 3)
    return round(max(0.0, min(score, 1.0)), 3)


def plan(models, score, thresholds, is_open=lambda name: False):
    low, high = thresholds
    tier = 1 if score < low else 2 if score < high else 3
    up = sorted((m for m in models if m.tier >= tier), key=lambda m: (m.tier, m.output_cost))
    down = sorted((m for m in models if m.tier < tier), key=lambda m: -m.tier)
    ordered = up + down
    return [m for m in ordered if not is_open(m.name)] + [m for m in ordered if is_open(m.name)]
