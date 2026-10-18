import httpx

from .base import Completion, ProviderError


class OpenAIProvider:
    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1"):
        self.client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60,
        )

    async def complete(self, model, messages, max_tokens):
        try:
            r = await self.client.post(
                "/chat/completions",
                json={"model": model.upstream, "messages": messages, "max_tokens": max_tokens},
            )
        except httpx.HTTPError as e:
            raise ProviderError(str(e)) from e

        if r.status_code >= 400:
            raise ProviderError(
                f"openai {r.status_code}: {r.text[:200]}",
                retryable=r.status_code in (408, 429) or r.status_code >= 500,
            )

        data = r.json()
        usage = data.get("usage", {})
        return Completion(
            text=data["choices"][0]["message"]["content"],
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )
