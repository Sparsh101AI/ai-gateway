import os
from typing import Literal

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from .config import load_settings
from .core import AllModelsFailed, Gateway, RateLimited
from .observability import Metrics
from .providers import build_providers


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1)
    model: str = "auto"
    quality: Literal["low", "medium", "high"] | None = None
    max_tokens: int = Field(512, ge=1, le=8192)


def create_app(gateway: Gateway | None = None) -> FastAPI:
    if gateway is None:
        settings = load_settings()
        metrics = Metrics(log_path=os.getenv("GATEWAY_LOG", "logs/requests.jsonl"))
        gateway = Gateway(settings, build_providers(settings.providers), metrics)

    app = FastAPI(title="AI Gateway", version="0.1.0")
    app.state.gateway = gateway

    @app.post("/v1/chat/completions")
    async def chat(req: ChatRequest, x_client_id: str = Header("anonymous")):
        try:
            res = await gateway.complete(
                [m.model_dump() for m in req.messages],
                client=x_client_id, model=req.model, quality=req.quality, max_tokens=req.max_tokens,
            )
        except RateLimited as e:
            return JSONResponse({"error": str(e)}, status_code=429,
                                headers={"Retry-After": str(int(e.retry_after) + 1)})
        except AllModelsFailed as e:
            return JSONResponse({"error": str(e), "attempts": [a.__dict__ for a in e.outcome.attempts]},
                                status_code=502)
        except KeyError as e:
            return JSONResponse({"error": f"unknown model {e}"}, status_code=400)

        return {
            "id": res.id,
            "model": res.model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": res.text}}],
            "usage": {"prompt_tokens": res.input_tokens, "completion_tokens": res.output_tokens},
            "gateway": {
                "complexity": res.complexity,
                "cost_usd": res.cost_usd,
                "baseline_cost_usd": res.baseline_cost_usd,
                "latency_ms": res.latency_ms,
                "attempts": res.attempts,
            },
        }

    @app.get("/health")
    async def health():
        return {"status": "ok", "models": gateway.health()}

    @app.get("/stats")
    async def stats():
        return gateway.metrics.snapshot()

    @app.get("/metrics", response_class=PlainTextResponse)
    async def metrics():
        return gateway.metrics.prometheus()

    return app
