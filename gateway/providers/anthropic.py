import httpx

from .base import Completion, ProviderError


class AnthropicProvider:
    def __init__(self, api_key: str, base_url: str = "https://api.anthropic.com/v1"):
        self.client = httpx.AsyncClient(
            base_url=base_url,
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            timeout=60,
        )

    async def complete(self, model, messages, max_tokens):
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        chat = [m for m in messages if m["role"] != "system"]
        body = {"model": model.upstream, "messages": chat, "max_tokens": max_tokens}
        if system:
            body["system"] = system

        try:
            r = await self.client.post("/messages", json=body)
        except httpx.HTTPError as e:
            raise ProviderError(str(e)) from e

        if r.status_code >= 400:
            raise ProviderError(
                f"anthropic {r.status_code}: {r.text[:200]}",
                retryable=r.status_code in (408, 429, 529) or r.status_code >= 500,
            )

        data = r.json()
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        usage = data.get("usage", {})
        return Completion(
            text=text,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )
