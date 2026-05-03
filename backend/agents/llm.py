"""``OpenRouterLlmClient`` — concrete ``LlmClient`` for OpenRouter.

Implements the ``LlmClient`` protocol from ``backend.agents.base`` by
wrapping ``AsyncOpenAI`` pointed at the OpenRouter endpoint. Matches
the pattern Kevin established in ``backend/agents/base_agent.py`` so
the API key, base URL, and headers are consistent across the codebase.

Tests do not use this class — they pass a fake client. This file only
matters at runtime when the FastAPI process is actually serving
requests.
"""

from __future__ import annotations

import os
from typing import Optional

from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()


_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_REFERER = "http://localhost:8000"
_TITLE = "BeaverHacks Fact-Checker"


class OpenRouterLlmClient:
    """Async OpenRouter client implementing the ``LlmClient`` protocol.

    A single instance can be shared across all agents — the underlying
    ``AsyncOpenAI`` client is connection-pooled and thread-safe for
    async use.
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: str = _OPENROUTER_BASE_URL,
        referer: str = _REFERER,
        title: str = _TITLE,
    ) -> None:
        resolved_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        # We don't raise here even on a missing key — agent instantiation
        # at module-import time should not crash a server that hasn't
        # set up its env yet. Failures surface at the first call as
        # AuthenticationError, which the agent base catches and logs
        # as ``error="llm_error: ..."``.
        self._client = AsyncOpenAI(base_url=base_url, api_key=resolved_key or "placeholder")
        self._extra_headers = {
            "HTTP-Referer": referer,
            "X-Title": title,
        }

    async def complete(self, *, model: str, system: str, user: str) -> str:
        response = await self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            extra_headers=self._extra_headers,
        )
        content = response.choices[0].message.content or ""
        return content


# Module-level singleton. Agents use this by default; tests inject fakes.
_default_client: Optional[OpenRouterLlmClient] = None


def get_default_llm_client() -> OpenRouterLlmClient:
    """Lazy singleton accessor. Avoids constructing the AsyncOpenAI
    client at import time when no LLM call is imminent."""
    global _default_client
    if _default_client is None:
        _default_client = OpenRouterLlmClient()
    return _default_client
