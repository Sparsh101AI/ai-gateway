import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bench.workload import generate
from gateway.config import load_settings
from gateway.core import AllModelsFailed, Gateway
from gateway.observability import Metrics
from gateway.providers.mock import MockProvider


async def main(n: int, concurrency: int, speed: float, mix: tuple):
    settings = load_settings(Path(__file__).resolve().parent.parent / "config.yaml")
    settings.rate_limit.requests_per_minute = 10**9
    settings.rate_limit.tokens_per_minute = 10**12
    gw = Gateway(settings, {"mock": MockProvider(seed=42, speed=speed)}, Metrics())

    sem = asyncio.Semaphore(concurrency)
    failed = 0

    async def one(req):
        nonlocal failed
        async with sem:
            try:
                await gw.complete(req["messages"], client="bench", max_tokens=req["max_tokens"])
            except AllModelsFailed:
                failed += 1

    await asyncio.gather(*(one(r) for r in generate(n, mix=mix)))
    snap = gw.metrics.snapshot()

    print(f"requests       {n} ({failed} failed after all fallbacks)")
    print(f"fallbacks      {snap['requests']['fallbacks']}")
    print(f"latency p50    {snap['latency_ms']['p50']} ms   p95 {snap['latency_ms']['p95']} ms")
    print(f"tokens         {snap['tokens']['input']} in / {snap['tokens']['output']} out")
    print(f"baseline cost  ${snap['cost_usd']['baseline']:.4f}  (everything on '{settings.baseline_model}')")
    print(f"routed cost    ${snap['cost_usd']['actual']:.4f}")
    print(f"savings        {snap['cost_usd']['savings_pct']}%")
    print("\nper model:")
    print(json.dumps(snap["by_model"], indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("-n", type=int, default=1000)
    p.add_argument("-c", "--concurrency", type=int, default=50)
    p.add_argument("--speed", type=float, default=0.05, help="mock latency multiplier")
    p.add_argument("--mix", default="0.45,0.30,0.25", help="simple,medium,complex traffic share")
    args = p.parse_args()
    mix = tuple(float(x) for x in args.mix.split(","))
    asyncio.run(main(args.n, args.concurrency, args.speed, mix))
