from __future__ import annotations

import json
import re
from typing import Any
from uuid import uuid4

from jarvis.backend.core.bot_manager import BotManager, BotMessage
from jarvis.backend.core.event_bus import EventBus
from jarvis.backend.core.lm_provider import LMProviderInterface
from jarvis.backend.core.memory_manager import MemoryManager
from jarvis.backend.utils.audit_logging import AuditLogger


# The agent identity used as the dispatch sender, so audit-log entries and any
# permission requests are clearly attributable to autonomous runs rather than to
# a human typing in chat.
AGENT_ACTOR = "deep-research-agent"

# Permissions an unattended research run needs. The user pre-approves this scope
# at launch (full-autonomy-in-a-scope); execute_scripts is deliberately absent.
RESEARCH_SCOPE = ("access_network",)

_PLAN_INSTRUCTION = (
    "You are planning web research. Break the user's goal into {n} focused, "
    "diverse web-search queries that together would answer it well. Reply with "
    "ONLY a JSON array of query strings, e.g. [\"query one\", \"query two\"]. "
    "No prose, no markdown."
)

_SYNTHESIS_INSTRUCTION = (
    "Write a concise research report answering the goal below, using ONLY the "
    "numbered sources provided. Cite sources inline as [n] matching their "
    "numbers. If the sources do not cover part of the goal, say so plainly "
    "instead of guessing. Never invent facts, numbers, quotes, or URLs."
)


class DeepResearchAgent:
    """Multi-step web research: plan queries, search, read pages, synthesize.

    Deliberately a deterministic pipeline rather than a free-form tool-calling
    loop: it is more reliable on small local models and keeps the report grounded
    in fetched text, which suits Odin's truthfulness contract. It reuses the
    existing ResearchBot for every network action, so permission gating, audit
    logging, and rate limiting all apply unchanged. Progress is streamed as
    ``agent.*`` events for the UI.
    """

    def __init__(
        self,
        lm_provider: LMProviderInterface,
        bot_manager: BotManager,
        memory: MemoryManager,
        audit_logger: AuditLogger,
        event_bus: EventBus | None = None,
        max_queries: int = 3,
        max_sources: int = 4,
        source_char_budget: int = 2500,
    ) -> None:
        self.lm_provider = lm_provider
        self.bot_manager = bot_manager
        self.memory = memory
        self.audit_logger = audit_logger
        self.event_bus = event_bus
        self.max_queries = max_queries
        self.max_sources = max_sources
        self.source_char_budget = source_char_budget

    async def run_research(self, goal: str, username: str = "local-user") -> dict[str, Any]:
        cleaned = goal.strip()
        if not cleaned:
            raise ValueError("A research goal is required")

        run_id = uuid4().hex
        user = self.memory.get_or_create_user(username)
        task = self.memory.create_task(
            user.user_id, name=f"Research: {cleaned[:60]}", description=cleaned
        )
        self.memory.update_task(user.user_id, task.task_id, status="in_progress")
        self._emit("agent.started", {"run_id": run_id, "goal": cleaned, "task_id": task.task_id})
        self.audit_logger.log(
            actor=AGENT_ACTOR,
            action="agent:research:start",
            result="ok",
            metadata={"run_id": run_id, "task_id": task.task_id},
        )

        # Pre-approved scope: the whole plan runs without per-step prompts.
        permission_manager = self.bot_manager.permission_manager
        try:
            with permission_manager.scope(RESEARCH_SCOPE):
                queries = await self._plan_queries(cleaned)
                self._emit("agent.plan", {"run_id": run_id, "queries": queries})

                results = await self._gather_results(run_id, queries)
                sources = await self._read_sources(run_id, results)
                report = await self._synthesize(run_id, cleaned, sources)
        except Exception as exc:  # noqa: BLE001 - report failure cleanly to the UI/task
            self.memory.update_task(
                user.user_id, task.task_id, status="pending", description=f"FAILED: {exc}"
            )
            self._emit("agent.error", {"run_id": run_id, "error": str(exc)})
            self.audit_logger.log(
                actor=AGENT_ACTOR,
                action="agent:research:error",
                result="error",
                metadata={"run_id": run_id, "error": str(exc)},
            )
            raise

        citations = [{"title": item["title"], "url": item["url"]} for item in sources]
        self.memory.update_task(user.user_id, task.task_id, status="complete", description=report)
        self._emit(
            "agent.complete",
            {"run_id": run_id, "report": report, "sources": citations, "task_id": task.task_id},
        )
        self.audit_logger.log(
            actor=AGENT_ACTOR,
            action="agent:research:complete",
            result="ok",
            metadata={"run_id": run_id, "task_id": task.task_id, "sources": len(citations)},
        )
        return {
            "run_id": run_id,
            "goal": cleaned,
            "report": report,
            "sources": citations,
            "queries": queries,
            "task_id": task.task_id,
        }

    async def _plan_queries(self, goal: str) -> list[str]:
        try:
            raw = await self.lm_provider.generate(
                f"{_PLAN_INSTRUCTION.format(n=self.max_queries)}\n\nGOAL:\n{goal}",
                context=[],
            )
        except RuntimeError:
            return [goal]
        queries = _parse_query_list(raw)
        if not queries:
            return [goal]
        return queries[: self.max_queries]

    async def _gather_results(self, run_id: str, queries: list[str]) -> list[dict[str, str]]:
        seen: set[str] = set()
        collected: list[dict[str, str]] = []
        for query in queries:
            self._emit(
                "agent.step",
                {"run_id": run_id, "kind": "search", "label": f"Search: {query}", "status": "running"},
            )
            response = await self.bot_manager.dispatch(
                BotMessage(
                    sender=AGENT_ACTOR,
                    recipient="research",
                    action="search",
                    payload={"text": query, "limit": 5},
                )
            )
            if response is not None and response.ok:
                for result in response.payload.get("results", []):
                    url = str(result.get("url") or "").strip()
                    if url and url not in seen:
                        seen.add(url)
                        collected.append({"title": str(result.get("title") or url), "url": url})
                self._emit(
                    "agent.step",
                    {"run_id": run_id, "kind": "search", "label": f"Search: {query}", "status": "done"},
                )
            else:
                detail = response.error if response is not None else "research bot unavailable"
                self._emit(
                    "agent.step",
                    {
                        "run_id": run_id,
                        "kind": "search",
                        "label": f"Search: {query}",
                        "status": "error",
                        "detail": detail,
                    },
                )
        return collected

    async def _read_sources(
        self, run_id: str, results: list[dict[str, str]]
    ) -> list[dict[str, str]]:
        sources: list[dict[str, str]] = []
        for result in results:
            if len(sources) >= self.max_sources:
                break
            url = result["url"]
            self._emit(
                "agent.step",
                {"run_id": run_id, "kind": "read", "label": f"Read: {result['title']}", "status": "running"},
            )
            response = await self.bot_manager.dispatch(
                BotMessage(
                    sender=AGENT_ACTOR,
                    recipient="research",
                    action="fetch",
                    payload={"text": url},
                )
            )
            if response is not None and response.ok and response.payload.get("text"):
                sources.append(
                    {
                        "title": result["title"],
                        "url": url,
                        "text": str(response.payload["text"])[: self.source_char_budget],
                    }
                )
                self._emit(
                    "agent.step",
                    {"run_id": run_id, "kind": "read", "label": f"Read: {result['title']}", "status": "done"},
                )
            else:
                detail = response.error if response is not None else "research bot unavailable"
                self._emit(
                    "agent.step",
                    {
                        "run_id": run_id,
                        "kind": "read",
                        "label": f"Read: {result['title']}",
                        "status": "error",
                        "detail": detail,
                    },
                )
        return sources

    async def _synthesize(self, run_id: str, goal: str, sources: list[dict[str, str]]) -> str:
        self._emit(
            "agent.step",
            {"run_id": run_id, "kind": "synthesize", "label": "Synthesize report", "status": "running"},
        )
        if not sources:
            report = (
                "I could not gather any readable sources for this goal "
                "(searches returned nothing usable or pages could not be fetched), "
                "so I can't give a grounded answer. Try rephrasing the goal or "
                "checking the network connection."
            )
            self._emit(
                "agent.step",
                {"run_id": run_id, "kind": "synthesize", "label": "Synthesize report", "status": "done"},
            )
            return report

        sources_block = "\n\n".join(
            f"[{index}] {item['title']} ({item['url']})\n{item['text']}"
            for index, item in enumerate(sources, start=1)
        )
        prompt = (
            f"{_SYNTHESIS_INSTRUCTION}\n\nGOAL:\n{goal}\n\nSOURCES:\n{sources_block}"
        )
        try:
            report = (await self.lm_provider.generate(prompt, context=[])).strip()
        except RuntimeError as exc:
            self._emit(
                "agent.step",
                {
                    "run_id": run_id,
                    "kind": "synthesize",
                    "label": "Synthesize report",
                    "status": "error",
                    "detail": str(exc),
                },
            )
            raise
        if not report:
            report = "The model returned an empty report."
        self._emit(
            "agent.step",
            {"run_id": run_id, "kind": "synthesize", "label": "Synthesize report", "status": "done"},
        )
        return report

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.event_bus is not None:
            self.event_bus.publish(event_type, payload, transient=True)


def _parse_query_list(raw: str) -> list[str]:
    """Pull a list of query strings out of a model reply, tolerantly.

    Prefers a JSON array; falls back to non-empty lines so a model that ignores
    the format instruction still yields usable queries.
    """
    match = re.search(r"\[.*\]", raw, flags=re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, list):
                queries = [str(item).strip() for item in parsed if str(item).strip()]
                if queries:
                    return queries
        except json.JSONDecodeError:
            pass
    lines = [
        re.sub(r'^[\s\-\*\d\.\)"]+|"$', "", line).strip()
        for line in raw.splitlines()
    ]
    return [line for line in lines if line]
