from __future__ import annotations

import json
from typing import Protocol

from openai import AsyncOpenAI

from agent.config import Settings
from agent.prompts import SYSTEM_PROMPT
from agent.schemas import MoveDecision


class ModelBoundary(Protocol):
    async def decide(self, message: str) -> MoveDecision:
        """Return a validated interpretation from the configured model."""


class RealModelClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.api_key:
            raise RuntimeError("OPENAI_API_KEY is required for model execution")
        options: dict[str, str] = {"api_key": settings.api_key}
        if settings.base_url:
            options["base_url"] = settings.base_url
        self._client = AsyncOpenAI(**options)
        self._model = settings.model_name

    async def decide(self, message: str) -> MoveDecision:
        response = await self._client.chat.completions.create(
            model=self._model,
            temperature=0,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "move_decision",
                    "strict": True,
                    "schema": MoveDecision.model_json_schema(),
                },
            },
        )
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("Model returned no decision content")
        return MoveDecision.model_validate_json(content)

    async def ping(self) -> None:
        response = await self._client.chat.completions.create(
            model=self._model,
            temperature=0,
            max_tokens=1,
            messages=[{"role": "user", "content": "Reply with OK"}],
        )
        if not response.choices:
            raise RuntimeError("Provider ping returned no choices")


def decode_decision(raw_content: str) -> MoveDecision:
    """Validate a provider-compatible JSON decision payload."""
    return MoveDecision.model_validate(json.loads(raw_content))
