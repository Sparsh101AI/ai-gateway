import os

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .config import load_settings
from .gateway import AllModelsFailed, Gateway, RateLimited
from .metrics import Metrics
from .providers import default_providers


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1)
    max_tokens: int = Field(512, ge=1, le=8192)


def create_app(gateway=None):
    gateway = gateway or Gateway(load_settings(), default_providers(),
                                 Metrics(os.getenv("GATEWAY_LOG", "logs/requests.jsonl")))
    app = FastAPI(title="AI Gateway")

    @app.post("/v1/chat/completions")
    async def chat(req: ChatRequest, x_client_id: str = Header("anonymous")):
        try:
            return await gateway.complete([m.model_dump() for m in req.messages], x_client_id, req.max_tokens)
        except RateLimited as e:
            return JSONResponse({"error": str(e)}, 429, headers={"Retry-After": str(int(e.retry_after) + 1)})
        except AllModelsFailed as e:
            return JSONResponse({"error": str(e), "attempts": e.errors}, 502)

    @app.get("/health")
    async def health():
        return {m.name: "open" if gateway.is_open(m.name) else "ok" for m in gateway.settings.models}

    @app.get("/stats")
    async def stats():
        return gateway.metrics.snapshot()

    return app
