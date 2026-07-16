from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict, is_dataclass
from typing import Any, Type, TypeVar

from pydantic import BaseModel, ValidationError


T = TypeVar("T")


class DiagnosticReport(BaseModel):
    """Structured diagnostic report schema."""
    diagnosis: str
    severity: str  # "low", "medium", "high"
    recommended_actions: list[str]
    confidence: float


class MemoryFact(BaseModel):
    """Structured memory fact schema."""
    text: str
    category: str
    related_entities: list[str]


class JSONOutputFormatter:
    """Injects JSON schema preambles into prompts and parses structured output."""

    @staticmethod
    def schema_to_json_string(schema: Type[T]) -> str:
        """Convert a Pydantic model to a JSON schema string for prompt injection."""
        try:
            if hasattr(schema, "model_json_schema"):
                json_schema = schema.model_json_schema()
            elif is_dataclass(schema):
                json_schema = {
                    "type": "object",
                    "properties": {
                        field.name: {"type": "string"}
                        for field in schema.__dataclass_fields__.values()
                    },
                }
            else:
                return "{}"
            return json.dumps(json_schema, indent=2)
        except Exception:
            return "{}"

    @staticmethod
    def for_schema(schema: Type[T]) -> str:
        """Generate a preamble instructing the model to output JSON matching this schema."""
        json_schema = JSONOutputFormatter.schema_to_json_string(schema)
        return (
            f"Respond with valid JSON matching this schema:\n```json\n{json_schema}\n```\n"
            "Ensure your response is a single, complete JSON object."
        )

    @staticmethod
    def extract_json_block(text: str) -> dict[str, Any] | None:
        """Extract the first JSON object or array from text."""
        patterns = [
            r"```json\s*(.*?)\s*```",  # json code block
            r"```\s*(.*?)\s*```",  # generic code block
            r"(\{.*?\})",  # bare JSON object
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                json_str = match.group(1)
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    continue
        return None

    @staticmethod
    def parse_output(text: str, schema: Type[T]) -> T | None:
        """Parse and validate output against a Pydantic schema or dataclass."""
        json_obj = JSONOutputFormatter.extract_json_block(text)
        if json_obj is None:
            return None
        try:
            if hasattr(schema, "model_validate"):
                return schema.model_validate(json_obj)
            elif is_dataclass(schema):
                return schema(**json_obj)
            else:
                return None
        except (ValidationError, TypeError, ValueError):
            return None


class ConstrainedGenerator:
    """Generates structured output with retry fallback."""

    def __init__(self, max_retries: int = 3) -> None:
        self.max_retries = max_retries

    async def generate_json(
        self,
        lm_provider: Any,  # LMProviderInterface
        text: str,
        context: list[str],
        schema: Type[T],
        history: list[dict[str, str]] | None = None,
    ) -> T | None:
        """Generate and validate JSON output, retrying on parse failure."""
        for attempt in range(self.max_retries):
            prompt = text
            if attempt > 0:
                prompt = f"{text}\n\nPrevious response was invalid. Please retry with valid JSON."

            response = await lm_provider.generate(
                prompt,
                context,
                history=history,
            )

            parsed = JSONOutputFormatter.parse_output(response, schema)
            if parsed is not None:
                return parsed

            if attempt == self.max_retries - 1:
                return None

        return None
