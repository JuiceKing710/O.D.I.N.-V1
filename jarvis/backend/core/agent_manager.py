from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
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


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class AgentRun:
    """Mutable record of one research run, polled via the status endpoint."""

    run_id: str
    goal: str
    username: str
    status: str = "running"  # running | complete | error
    task_id: int | None = None
    queries: list[str] = field(default_factory=list)
    steps: list[dict[str, str]] = field(default_factory=list)
    report: str = ""
    sources: list[dict[str, str]] = field(default_factory=list)
    error: str | None = None
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    def to_api(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "goal": self.goal,
            "status": self.status,
            "task_id": self.task_id,
            "queries": list(self.queries),
            "steps": [dict(step) for step in self.steps],
            "report": self.report,
            "sources": [dict(source) for source in self.sources],
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class DeepResearchAgent:
    """Multi-step web research: plan queries, search, read pages, synthesize.

    Deliberately a deterministic pipeline rather than a free-form tool-calling
    loop: it is more reliable on small local models and keeps the report grounded
    in fetched text, which suits Odin's truthfulness contract. It reuses the
    existing ResearchBot for every network action, so permission gating, audit
    logging, and rate limiting all apply unchanged.

    Runs are tracked in a registry so a caller can fire a run and poll its status
    instead of holding a long HTTP request open. Progress is also streamed as
    ``agent.*`` events for live UI updates.
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
        max_runs: int = 50,
    ) -> None:
        self.lm_provider = lm_provider
        self.bot_manager = bot_manager
        self.memory = memory
        self.audit_logger = audit_logger
        self.event_bus = event_bus
        self.max_queries = max_queries
        self.max_sources = max_sources
        self.source_char_budget = source_char_budget
        self.max_runs = max_runs
        self._runs: dict[str, AgentRun] = {}
        self._tasks: set[asyncio.Task] = set()

    # ---- public API -------------------------------------------------------

    def start_research(self, goal: str, username: str = "local-user") -> dict[str, Any]:
        """Begin a run in the background and return its initial status at once.

        The caller polls ``get_run(run_id)`` (or listens to agent.* events) for
        progress, so a long research run never blocks the HTTP request.
        """
        run = self._new_run(goal, username)
        task = asyncio.ensure_future(self._execute(run))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return run.to_api()

    async def run_research(self, goal: str, username: str = "local-user") -> dict[str, Any]:
        """Run synchronously to completion and return the final status.

        Used by tests and the capability harness; the HTTP route uses
        ``start_research`` instead.
        """
        run = self._new_run(goal, username)
        await self._execute(run)
        return run.to_api()

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        run = self._runs.get(run_id)
        return run.to_api() if run is not None else None

    # ---- run lifecycle ----------------------------------------------------

    def _new_run(self, goal: str, username: str) -> AgentRun:
        cleaned = goal.strip()
        if not cleaned:
            raise ValueError("A research goal is required")
        run = AgentRun(run_id=uuid4().hex, goal=cleaned, username=username)
        self._runs[run.run_id] = run
        self._prune_runs()
        return run

    async def _execute(self, run: AgentRun) -> None:
        user = self.memory.get_or_create_user(run.username)
        task = self.memory.create_task(
            user.user_id, name=f"Research: {run.goal[:60]}", description=run.goal
        )
        run.task_id = task.task_id
        self.memory.update_task(user.user_id, task.task_id, status="in_progress")
        self._emit("agent.started", {"run_id": run.run_id, "goal": run.goal, "task_id": task.task_id})
        self.audit_logger.log(
            actor=AGENT_ACTOR,
            action="agent:research:start",
            result="ok",
            metadata={"run_id": run.run_id, "task_id": task.task_id},
        )

        permission_manager = self.bot_manager.permission_manager
        try:
            with permission_manager.scope(RESEARCH_SCOPE):
                run.queries = await self._plan_queries(run.goal)
                self._touch(run)
                self._emit("agent.plan", {"run_id": run.run_id, "queries": run.queries})

                results = await self._gather_results(run)
                sources = await self._read_sources(run, results)
                run.report = await self._synthesize(run, sources)
        except Exception as exc:  # noqa: BLE001 - capture into the run, not a crash
            run.status = "error"
            run.error = str(exc)
            self._touch(run)
            self.memory.update_task(
                user.user_id, task.task_id, status="pending", description=f"FAILED: {exc}"
            )
            self._emit("agent.error", {"run_id": run.run_id, "error": str(exc)})
            self.audit_logger.log(
                actor=AGENT_ACTOR,
                action="agent:research:error",
                result="error",
                metadata={"run_id": run.run_id, "error": str(exc)},
            )
            return

        run.sources = [{"title": item["title"], "url": item["url"]} for item in sources]
        run.status = "complete"
        self._touch(run)
        self.memory.update_task(user.user_id, task.task_id, status="complete", description=run.report)
        self._emit(
            "agent.complete",
            {
                "run_id": run.run_id,
                "report": run.report,
                "sources": run.sources,
                "task_id": task.task_id,
            },
        )
        self.audit_logger.log(
            actor=AGENT_ACTOR,
            action="agent:research:complete",
            result="ok",
            metadata={"run_id": run.run_id, "task_id": task.task_id, "sources": len(run.sources)},
        )

    def _prune_runs(self) -> None:
        """Drop the oldest finished runs so the registry can't grow forever."""
        if len(self._runs) <= self.max_runs:
            return
        finished = sorted(
            (run for run in self._runs.values() if run.status != "running"),
            key=lambda run: run.created_at,
        )
        for run in finished[: len(self._runs) - self.max_runs]:
            self._runs.pop(run.run_id, None)

    # ---- pipeline stages --------------------------------------------------

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

    async def _gather_results(self, run: AgentRun) -> list[dict[str, str]]:
        seen: set[str] = set()
        collected: list[dict[str, str]] = []
        for query in run.queries:
            label = f"Search: {query}"
            self._step(run, "search", label, "running")
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
                self._step(run, "search", label, "done")
            else:
                detail = response.error if response is not None else "research bot unavailable"
                self._step(run, "search", label, "error", detail or "")
        return collected

    async def _read_sources(
        self, run: AgentRun, results: list[dict[str, str]]
    ) -> list[dict[str, str]]:
        sources: list[dict[str, str]] = []
        for result in results:
            if len(sources) >= self.max_sources:
                break
            url = result["url"]
            label = f"Read: {result['title']}"
            self._step(run, "read", label, "running")
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
                self._step(run, "read", label, "done")
            else:
                detail = response.error if response is not None else "research bot unavailable"
                self._step(run, "read", label, "error", detail or "")
        return sources

    async def _synthesize(self, run: AgentRun, sources: list[dict[str, str]]) -> str:
        label = "Synthesize report"
        self._step(run, "synthesize", label, "running")
        if not sources:
            self._step(run, "synthesize", label, "done")
            return (
                "I could not gather any readable sources for this goal "
                "(searches returned nothing usable or pages could not be fetched), "
                "so I can't give a grounded answer. Try rephrasing the goal or "
                "checking the network connection."
            )

        sources_block = "\n\n".join(
            f"[{index}] {item['title']} ({item['url']})\n{item['text']}"
            for index, item in enumerate(sources, start=1)
        )
        prompt = f"{_SYNTHESIS_INSTRUCTION}\n\nGOAL:\n{run.goal}\n\nSOURCES:\n{sources_block}"
        try:
            report = (await self.lm_provider.generate(prompt, context=[])).strip()
        except RuntimeError as exc:
            self._step(run, "synthesize", label, "error", str(exc))
            raise
        if not report:
            report = "The model returned an empty report."
        self._step(run, "synthesize", label, "done")
        return report

    # ---- progress plumbing ------------------------------------------------

    def _step(self, run: AgentRun, kind: str, label: str, status: str, detail: str = "") -> None:
        """Record a step on the run (upsert by label) and emit the live event."""
        step = {"kind": kind, "label": label, "status": status, "detail": detail}
        for index, existing in enumerate(run.steps):
            if existing["label"] == label:
                run.steps[index] = step
                break
        else:
            run.steps.append(step)
        self._touch(run)
        self._emit(
            "agent.step",
            {"run_id": run.run_id, "kind": kind, "label": label, "status": status, "detail": detail},
        )

    def _touch(self, run: AgentRun) -> None:
        run.updated_at = _now()

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
