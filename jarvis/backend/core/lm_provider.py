from __future__ import annotations

import json
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ModelInfo:
    id: str
    provider: str
    loaded: bool = False


class LMProviderInterface(ABC):
    @abstractmethod
    async def generate(
        self, text: str, context: list[str], metadata: dict[str, Any] | None = None
    ) -> str:
        raise NotImplementedError

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]:
        raise NotImplementedError

    @abstractmethod
    async def load_model(self, model_name: str) -> ModelInfo:
        raise NotImplementedError


class EchoLMProvider(LMProviderInterface):
    def __init__(self, model_name: str = "echo-local") -> None:
        self.model_name = model_name

    async def generate(
        self, text: str, context: list[str], metadata: dict[str, Any] | None = None
    ) -> str:
        if context:
            return f"I heard: {text}\n\nRelevant memory available: {len(context)} item(s)."
        return f"I heard: {text}"

    async def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(id=self.model_name, provider="builtin", loaded=True)]

    async def load_model(self, model_name: str) -> ModelInfo:
        cleaned = model_name.strip()
        if not cleaned:
            raise ValueError("model_name is required")
        self.model_name = cleaned
        return ModelInfo(id=self.model_name, provider="builtin", loaded=True)


class LMStudioProvider(LMProviderInterface):
    def __init__(self, base_url: str, model: str | None = None, timeout_seconds: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model or "local-model"
        self.timeout_seconds = timeout_seconds

    async def generate(
        self, text: str, context: list[str], metadata: dict[str, Any] | None = None
    ) -> str:
        prompt = self._build_prompt(text, context)
        payload = json.dumps(
            {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"LM Studio request failed: {exc}") from exc
        return body["choices"][0]["message"]["content"]

    async def list_models(self) -> list[ModelInfo]:
        request = urllib.request.Request(f"{self.base_url}/v1/models", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return []
        return [
            ModelInfo(
                id=item.get("id", "unknown"),
                provider="lm-studio",
                loaded=item.get("id") == self.model,
            )
            for item in body.get("data", [])
        ]

    async def load_model(self, model_name: str) -> ModelInfo:
        cleaned = model_name.strip()
        if not cleaned:
            raise ValueError("model_name is required")
        self.model = cleaned
        return ModelInfo(id=self.model, provider="lm-studio", loaded=True)

    @staticmethod
    def _build_prompt(text: str, context: list[str]) -> str:
        if not context:
            return text
        joined = "\n".join(f"- {item}" for item in context)
        return f"Relevant memory:\n{joined}\n\nUser message:\n{text}"
