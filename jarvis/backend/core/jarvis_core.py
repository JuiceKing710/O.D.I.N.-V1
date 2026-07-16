from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import re
from typing import Any

from jarvis.backend.core.bot_manager import BotManager, BotMessage
from jarvis.backend.core.event_bus import EventBus
from jarvis.backend.core.lm_provider import LMProviderInterface
from jarvis.backend.core.memory_manager import MemoryManager
from jarvis.backend.core.skill_manager import SkillManager
from jarvis.backend.core.tool_provider import ToolInvocationHandler, ToolCallExtractor
from jarvis.backend.core.inference_optimizer import KVCacheOptimizer, PerformanceMonitor
from jarvis.backend.core.rag_engine import RAGEngine
from jarvis.backend.utils.audit_logging import AuditLogger


class JarvisCore:
    def __init__(
        self,
        memory: MemoryManager,
        bot_manager: BotManager,
        lm_provider: LMProviderInterface,
        audit_logger: AuditLogger,
        event_bus: EventBus | None = None,
        read_settings: Callable[[], dict[str, Any]] | None = None,
        skill_manager: SkillManager | None = None,
        tool_invocation_handler: ToolInvocationHandler | None = None,
        performance_monitor: PerformanceMonitor | None = None,
        rag_engine: RAGEngine | None = None,
    ) -> None:
        self.memory = memory
        self.bot_manager = bot_manager
        self.lm_provider = lm_provider
        self.audit_logger = audit_logger
        self.event_bus = event_bus
        self.read_settings = read_settings
        self.skill_manager = skill_manager
        self.tool_invocation_handler = tool_invocation_handler
        self.performance_monitor = performance_monitor
        self.rag_engine = rag_engine

    async def handle_message(
        self,
        message: str,
        username: str,
        conversation_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized = message.strip()
        if not normalized:
            raise ValueError("Message cannot be empty")

        user = self.memory.get_or_create_user(username)
        convo = (
            self.memory.get_conversation(conversation_id, user.user_id)
            if conversation_id is not None
            else self.memory.create_conversation(user.user_id, title=normalized[:80])
        )
        user_message = self.memory.add_message(convo.convo_id, "user", normalized)
        self._publish_chat_message(user_message.role, user_message.content, convo.convo_id)

        image_url = None
        fact_reply = self._maybe_handle_fact(normalized, user.user_id)
        skills_reply = self._maybe_handle_skills(normalized)
        if fact_reply is not None:
            bot_name, reply = "memory", fact_reply
        elif skills_reply is not None:
            bot_name, reply = "skills", skills_reply
        else:
            bot_name, bot_reply, bot_image_url = await self._maybe_dispatch_bot(normalized)
            if bot_reply is not None:
                reply = bot_reply
                image_url = bot_image_url
            else:
                context = (
                    self.memory.identity_context()
                    + self.memory.memory_block_context()
                    + self._active_model_context()
                    + self._skill_context(normalized)
                    + self.memory.fact_context(user.user_id)
                    + self.memory.query_context(user.user_id, normalized, limit=5)
                    + self._rag_context(normalized)
                )
                history = self._conversation_history(convo.convo_id)
                if self._truthfulness_check_enabled():
                    reply = await self._generate_verified(
                        normalized, context, history, convo.convo_id, metadata or {}
                    )
                else:
                    reply = await self._generate_streaming(
                        normalized, context, history, convo.convo_id, metadata or {}
                    )

        assistant_message = self.memory.add_message(convo.convo_id, "assistant", reply)
        self._publish_chat_message(assistant_message.role, assistant_message.content, convo.convo_id)
        self.audit_logger.log(
            actor=username,
            action="chat",
            result="ok",
            metadata={"conversation_id": convo.convo_id, "bot": bot_name},
        )
        return {
            "conversation_id": convo.convo_id,
            "reply": reply,
            "bot": bot_name,
            "created_at": datetime.now(timezone.utc),
            "image_url": image_url,
        }

    def _active_model_context(self) -> list[str]:
        """A grounded note telling Odin which model/provider is answering right now.

        Derived cheaply from settings (no network) so Odin can answer "what model
        are you?" truthfully as the user switches backends. Mirrors the routing in
        TurboSwitchProvider. Returns [] when settings are unavailable.
        """
        if self.read_settings is None:
            return []
        try:
            settings = self.read_settings()
        except Exception:  # noqa: BLE001 - a settings read must never break chat
            return []
        active = str(settings.get("active_model") or "").strip()
        if active.startswith("openrouter:"):
            note = (
                "You are currently answering through OpenRouter, using the model "
                f"'{active[len('openrouter:') :]}'."
            )
        elif active.startswith("nvidia:"):
            note = (
                "You are currently answering through NVIDIA's hosted API, using the "
                f"model '{active[len('nvidia:') :]}'."
            )
        elif active:
            note = f"You are currently answering with the local on-device model '{active}' (via Ollama)."
        elif settings.get("turbo_mode") and str(settings.get("gemini_api_key") or "").strip():
            note = "You are currently answering through Google Gemini (turbo mode is on)."
        else:
            model_name = str(settings.get("model_name") or "").strip()
            if model_name and model_name != "local-default":
                note = (
                    f"You are currently answering with the local on-device model "
                    f"'{model_name}' (via Ollama)."
                )
            else:
                note = "You are currently answering with your local on-device model (via Ollama)."
        return [f"[Current model] {note}"]

    def _skills_enabled(self) -> bool:
        if self.read_settings is None:
            return True
        try:
            return self.read_settings().get("skills_enabled") is not False
        except Exception:  # noqa: BLE001 - a settings read must never break chat
            return True

    def _skill_context(self, message: str) -> list[str]:
        """Guidance from installed Agent Skills relevant to the current message."""
        if self.skill_manager is None or not self._skills_enabled():
            return []
        return self.skill_manager.skill_context(message)

    def _maybe_handle_skills(self, message: str) -> str | None:
        """Handle the ``/skills`` command: list installed Agent Skills."""
        if self.skill_manager is None or message.strip().lower() != "/skills":
            return None
        skills = self.skill_manager.list_skills()
        if not skills:
            return (
                "No Agent Skills are installed. Drop skill folders under the skills/ "
                "directory (e.g. `npx skills add nvidia/skills`), then say /skills again."
            )
        status = "on" if self._skills_enabled() else "off (enable in Settings)"
        lines = "\n".join(
            f"- {skill.name} — {skill.description or 'no description'}" for skill in skills
        )
        return f"Installed skills ({len(skills)}) · auto-match {status}:\n{lines}"

    HISTORY_TURN_LIMIT = 20

    def _conversation_history(self, convo_id: int) -> list[dict[str, str]]:
        records = self.memory.list_conversation_messages(convo_id)
        # The just-stored current user message is the last record; the model
        # receives it separately as the prompt.
        previous = records[:-1]
        return [
            {"role": record.role, "content": record.content}
            for record in previous[-self.HISTORY_TURN_LIMIT :]
        ]

    async def _generate_streaming(
        self,
        text: str,
        context: list[str],
        history: list[dict[str, str]],
        convo_id: int,
        metadata: dict[str, Any],
    ) -> str:
        parts: list[str] = []
        try:
            async for delta in self.lm_provider.generate_stream(
                text, context=context, metadata=metadata, history=history
            ):
                parts.append(delta)
                if self.event_bus is not None:
                    self.event_bus.publish(
                        "chat.stream",
                        {"conversation_id": convo_id, "delta": delta},
                        transient=True,
                    )
        finally:
            if self.event_bus is not None:
                self.event_bus.publish(
                    "chat.stream.end", {"conversation_id": convo_id}, transient=True
                )
        response = "".join(parts)
        return await self._process_tool_calls(response)

    def _truthfulness_check_enabled(self) -> bool:
        if self.read_settings is None:
            return False
        try:
            return bool(self.read_settings().get("truthfulness_check"))
        except Exception:  # noqa: BLE001 - a settings read must never break chat
            return False

    # Verification prompts kept terse so the extra calls stay cheap on a local model.
    _VERIFY_INSTRUCTION = (
        "You are a strict fact-checker. Below are the user's message, the context "
        "the assistant was given, and the assistant's draft reply. List any "
        "statements in the draft that are NOT supported by the context or the "
        "conversation and that the assistant could not actually know — including "
        "invented facts, names, numbers, citations, or URLs. If every statement "
        'is supported or appropriately hedged, reply with exactly "OK".'
    )
    _CORRECT_INSTRUCTION = (
        "A fact-checker flagged possible unsupported or fabricated statements in "
        "your draft reply. Rewrite your reply to the user so it asserts only what "
        "is supported by the conversation, the provided context, or knowledge you "
        "are confident in. Remove or explicitly hedge anything you cannot verify, "
        "and never invent details. Reply with the corrected answer only."
    )

    async def _generate_verified(
        self,
        text: str,
        context: list[str],
        history: list[dict[str, str]],
        convo_id: int,
        metadata: dict[str, Any],
    ) -> str:
        """Generate, fact-check against context, and correct once if needed.

        Used only when the `truthfulness_check` setting is on. Live token
        streaming is intentionally skipped here because the final text isn't
        known until after verification; the reply is still delivered through the
        normal chat.message path.
        """
        draft = await self.lm_provider.generate(
            text, context=context, metadata=metadata, history=history
        )
        verdict = await self.lm_provider.generate(
            f"{self._VERIFY_INSTRUCTION}\n\n"
            f"USER MESSAGE:\n{text}\n\n"
            f"CONTEXT:\n{self._format_context(context)}\n\n"
            f"DRAFT REPLY:\n{draft}",
            context=[],
            metadata=metadata,
        )
        if verdict.strip().upper().startswith("OK"):
            self._publish_verification(convo_id, "passed")
            return draft
        corrected = await self.lm_provider.generate(
            f"{self._CORRECT_INSTRUCTION}\n\n"
            f"USER MESSAGE:\n{text}\n\n"
            f"FACT-CHECK NOTES:\n{verdict.strip()}\n\n"
            f"YOUR DRAFT REPLY:\n{draft}",
            context=context,
            metadata=metadata,
            history=history,
        )
        self._publish_verification(convo_id, "corrected")
        return corrected

    @staticmethod
    def _format_context(context: list[str]) -> str:
        return "\n".join(f"- {item}" for item in context) if context else "(none)"

    def _rag_context(self, text: str) -> list[str]:
        """Retrieve context from RAG engine if available."""
        if self.rag_engine is None:
            return []
        try:
            results = self.rag_engine.query(text, top_k=3)
            if not results:
                return []
            formatted = self.rag_engine.format_for_context(results)
            if formatted:
                return ["[RAG Document Retrieval]"] + formatted
        except Exception:
            pass
        return []

    async def _process_tool_calls(self, response: str) -> str:
        """Extract tool calls from response, invoke them, and inject results."""
        if self.tool_invocation_handler is None:
            return response

        calls = ToolCallExtractor.extract_tool_calls(response)
        if not calls:
            return response

        clean_response = ToolCallExtractor.remove_tool_calls(response)
        results: dict[str, Any] = {}

        for call in calls:
            result = await self.tool_invocation_handler.invoke(call.tool_id, call.params)
            results[call.tool_id] = result

        if results:
            return ToolCallExtractor.inject_tool_results(clean_response, results)
        return clean_response

    def _publish_verification(self, convo_id: int, outcome: str) -> None:
        if self.event_bus is not None:
            self.event_bus.publish(
                "chat.verification",
                {"conversation_id": convo_id, "outcome": outcome},
                transient=True,
            )

    def _publish_chat_message(self, role: str, content: str, conversation_id: int) -> None:
        if self.event_bus is None:
            return
        self.event_bus.publish(
            "chat.message",
            {
                "conversation_id": conversation_id,
                "role": role,
                "content": content,
            },
        )

    def _maybe_handle_fact(self, message: str, user_id: int) -> str | None:
        """Handle the /fact and /facts commands for temporal-fact memory.

        - ``/fact subject | predicate | object`` records a fact, superseding the
          prior value so a changed employer/location stops being asserted.
        - ``/facts`` (optionally ``/facts <subject>``) lists what is true now.

        Returns the reply text, or None if the message is not a fact command.
        """
        stripped = message.strip()
        lowered = stripped.lower()
        if lowered == "/facts" or lowered.startswith("/facts "):
            subject = stripped[len("/facts") :].strip() or None
            facts = self.memory.current_facts(user_id, subject=subject)
            if not facts:
                scope = f" about {subject}" if subject else ""
                return f"I have no current facts recorded{scope}."
            lines = "\n".join(
                f"- {fact.subject} {fact.predicate.replace('_', ' ')} {fact.object}"
                for fact in facts
            )
            return f"Current facts:\n{lines}"
        if lowered.startswith("/fact "):
            parts = [piece.strip() for piece in stripped[len("/fact ") :].split("|")]
            if len(parts) != 3 or not all(parts):
                return "To record a fact, use: /fact subject | predicate | object"
            subject, predicate, obj = parts
            fact = self.memory.record_fact(
                user_id, subject, predicate.replace(" ", "_"), obj, source="chat"
            )
            return f"Recorded: {fact.subject} {fact.predicate.replace('_', ' ')} {fact.object}."
        return None

    async def _maybe_dispatch_bot(
        self, message: str
    ) -> tuple[str | None, str | None, str | None]:
        parsed = self._parse_bot_request(message)
        if parsed is None:
            return None, None, None
        bot_name, action, payload = parsed
        bot = self.bot_manager.get(bot_name)
        if bot is None or action not in bot.capabilities():
            return bot_name, f"Unsupported planned action: {bot_name}.{action}", None
        response = await self.bot_manager.dispatch(
            BotMessage(sender="user", recipient=bot_name, action=action, payload=payload)
        )
        if response is None:
            return bot_name, f"Unknown bot: {bot_name}", None
        if not response.ok:
            pending = response.payload.get("permission_request")
            if isinstance(pending, dict):
                reason = pending.get("reason") or f"{bot_name}.{action}"
                return bot_name, f"Approval required before Jarvis can continue: {reason}", None
            return bot_name, response.error or "Bot request failed.", None
        text = response.payload.get("text")
        image_url = response.payload.get("image_url")
        reply = str(text) if text is not None else "Bot request completed."
        return bot_name, reply, image_url

    @staticmethod
    def _parse_bot_request(message: str) -> tuple[str, str, dict[str, Any]] | None:
        if message.startswith("/"):
            parts = message[1:].split(maxsplit=2)
            if len(parts) < 2:
                return None
            return parts[0], parts[1], {"text": parts[2] if len(parts) == 3 else ""}

        patterns = (
            (r"^(?:research|search the web for|look up)\s+(.+)$", "research", "search"),
            (r"^(?:analyze code|analyze file)\s+(.+)$", "code", "analyze"),
            (r"^(?:read file|open file)\s+(.+)$", "file", "read"),
            (r"^(?:run command|execute command)\s+(.+)$", "system", "execute"),
            (
                r"^(?:generate|draw|create|make|paint)\s+(?:an?\s+)?(?:image|picture|drawing|painting)\s+(?:of\s+|showing\s+|with\s+)?(.+)$",
                "image",
                "generate",
            ),
        )
        for pattern, bot, action in patterns:
            match = re.match(pattern, message.strip(), flags=re.IGNORECASE | re.DOTALL)
            if match:
                return bot, action, {"text": match.group(1).strip()}
        write_match = re.match(
            r"^write file\s+([^\n]+)\n(.+)$",
            message.strip(),
            flags=re.IGNORECASE | re.DOTALL,
        )
        if write_match:
            return "file", "write", {
                "path": write_match.group(1).strip(),
                "content": write_match.group(2),
            }
        return None
