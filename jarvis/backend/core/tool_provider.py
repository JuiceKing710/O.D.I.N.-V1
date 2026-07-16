from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, AsyncIterator


@dataclass(slots=True, frozen=True)
class ToolDefinition:
    """Definition of a tool/function callable by the model."""
    id: str
    name: str
    description: str
    input_schema: dict[str, Any]  # JSON schema
    output_schema: dict[str, Any] | None = None


@dataclass(slots=True, frozen=True)
class ToolCall:
    """A model's invocation of a tool."""
    tool_id: str
    params: dict[str, Any]


class ToolRegistry:
    """Registry of available tools for model dispatch."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        """Register a tool definition."""
        if tool.id in self._tools:
            raise ValueError(f"Tool already registered: {tool.id}")
        self._tools[tool.id] = tool

    def unregister(self, tool_id: str) -> None:
        """Unregister a tool."""
        self._tools.pop(tool_id, None)

    def list(self) -> list[ToolDefinition]:
        """List all registered tools."""
        return list(self._tools.values())

    def find(self, tool_id: str) -> ToolDefinition | None:
        """Find a tool by ID."""
        return self._tools.get(tool_id)

    def to_prompt_format(self) -> str:
        """Format tool definitions for prompt injection."""
        tools_list = []
        for tool in self.list():
            tools_list.append({
                "id": tool.id,
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            })
        return json.dumps(tools_list, indent=2)


class ToolInvocationHandler:
    """Handles tool invocation and result injection."""

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry
        self._handlers: dict[str, Callable] = {}

    def register_handler(self, tool_id: str, handler: Callable) -> None:
        """Register a handler function for a tool."""
        self._handlers[tool_id] = handler

    async def invoke(self, tool_id: str, params: dict[str, Any]) -> dict[str, Any]:
        """Invoke a tool and return result."""
        tool = self.registry.find(tool_id)
        if tool is None:
            return {"error": f"Tool not found: {tool_id}"}

        handler = self._handlers.get(tool_id)
        if handler is None:
            return {"error": f"No handler registered for tool: {tool_id}"}

        try:
            if hasattr(handler, "__call__"):
                import asyncio
                if asyncio.iscoroutinefunction(handler):
                    result = await handler(params)
                else:
                    result = await asyncio.get_event_loop().run_in_executor(
                        None, handler, params
                    )
            else:
                result = handler(params)
            return {"result": result}
        except Exception as exc:
            return {"error": str(exc)}


class ToolCallExtractor:
    """Extracts tool calls from model output."""

    @staticmethod
    def extract_tool_calls(text: str) -> list[ToolCall]:
        """Extract all <tool_call>...</tool_call> blocks from text."""
        pattern = r"<tool_call>\s*(.*?)\s*</tool_call>"
        calls = []
        for match in re.finditer(pattern, text, re.DOTALL):
            try:
                json_str = match.group(1).strip()
                obj = json.loads(json_str)
                if "id" in obj and "params" in obj:
                    calls.append(ToolCall(tool_id=obj["id"], params=obj["params"]))
            except (json.JSONDecodeError, KeyError):
                pass
        return calls

    @staticmethod
    def remove_tool_calls(text: str) -> str:
        """Remove all <tool_call> blocks from text, returning clean response."""
        return re.sub(r"<tool_call>.*?</tool_call>\s*", "", text, flags=re.DOTALL)

    @staticmethod
    def inject_tool_results(text: str, results: dict[str, Any]) -> str:
        """Inject tool results back into response for continued generation."""
        injection = "\n\n[Tool Results]\n"
        for tool_id, result in results.items():
            injection += f"- {tool_id}: {json.dumps(result)}\n"
        return text + injection


class ToolUseFormatter:
    """Formats tool definitions and instructions for prompt injection."""

    @staticmethod
    def tool_use_preamble(registry: ToolRegistry) -> str:
        """Generate preamble instructing model to use tools."""
        tools_json = registry.to_prompt_format()
        return (
            "You have access to the following tools:\n"
            f"{tools_json}\n\n"
            "When you need to use a tool, respond with a tool_call block:\n"
            "<tool_call>\n"
            '{"id": "tool_id", "params": {"key": "value"}}\n'
            "</tool_call>\n\n"
            "You can then continue your response after the tool_call block. "
            "The tool result will be provided, and you can incorporate it into your answer."
        )
