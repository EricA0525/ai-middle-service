"""
OpenAI-compatible LLM client.

Supports:
- OpenAI official API
- Self-hosted / proxy endpoints that follow the OpenAI API schema
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from loguru import logger

from app.config import settings


@dataclass(frozen=True)
class LLMResponse:
    content: str


class OpenAICompatLLM:
    """
    Minimal async wrapper for OpenAI-compatible chat.completions.

    If `LLM_API_KEY` is empty, `is_configured()` returns False and callers should
    fallback to deterministic/mock content.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self.base_url = base_url or settings.llm_base_url
        self.api_key = api_key if api_key is not None else settings.llm_api_key
        self.model = model or settings.llm_model

        self._client = None

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _get_client(self):
        if self._client is not None:
            return self._client

        try:
            from openai import AsyncOpenAI
        except Exception as e:
            raise RuntimeError("openai package is required for LLM calls") from e

        self._client = AsyncOpenAI(base_url=self.base_url, api_key=self.api_key)
        return self._client

    async def generate_html(
        self,
        prompt: str,
        *,
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> LLMResponse:
        if not self.is_configured():
            raise RuntimeError("LLM is not configured (missing LLM_API_KEY)")

        client = self._get_client()
        logger.info(f"LLM generating content (model={self.model})")

        resp = await client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a senior market analyst. "
                        "Return only a concise HTML fragment (no <html>, <head>, <body>). "
                        "Use <h3>, <p>, <ul>, <li>, <table> when appropriate."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )

        content = (resp.choices[0].message.content or "").strip()
        return LLMResponse(content=content)

