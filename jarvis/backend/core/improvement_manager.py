from __future__ import annotations

import json
from typing import Any

from jarvis.backend.core.event_bus import EventBus
from jarvis.backend.core.lm_provider import LMProviderInterface
from jarvis.backend.core.memory_manager import MemoryManager, ProposalRecord
from jarvis.backend.core.safety_switch import SafetySwitch
from jarvis.backend.core.settings_store import SettingsStore

PROPOSE_PROMPT = (
    "You are Odin, proposing a controlled improvement to your own {kind} "
    "'{target}'. Here is its current value:\n\n{current}\n\n"
    "Propose a better version. Reply with ONLY the new value, no preamble."
)


class ImprovementManager:
    """Controlled adaptive improvement (master spec §8).

    Odin can *propose* changes to its own settings or memory blocks, but nothing
    takes effect without an explicit human ``approve`` then ``apply`` — no
    uncontrolled self-rewriting. Every applied change captures the prior value,
    so it is reversible. Targets are deliberately limited to settings keys and
    memory blocks (persona/human); source files are never touched here.
    """

    def __init__(
        self,
        memory: MemoryManager,
        settings: SettingsStore,
        lm_provider: LMProviderInterface,
        safety_switch: SafetySwitch | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.memory = memory
        self.settings = settings
        self.lm_provider = lm_provider
        self.safety_switch = safety_switch
        self.event_bus = event_bus

    async def propose(
        self,
        kind: str,
        target: str,
        proposed_value: str | None = None,
        rationale: str | None = None,
    ) -> ProposalRecord:
        current = self._read_target(kind, target)
        if proposed_value is None:
            proposed_value = await self.lm_provider.generate(
                PROPOSE_PROMPT.format(kind=kind, target=target, current=current or "(empty)"),
                context=[],
                metadata={"task": "self_improvement"},
            )
        proposed_value = (proposed_value or "").strip()
        if not proposed_value:
            raise ValueError("proposed_value is empty")
        record = self.memory.create_proposal(
            kind=kind,
            target=target,
            proposed_value=proposed_value,
            current_value=current,
            rationale=rationale,
        )
        self._publish("improvement.proposed", record)
        return record

    def list(self, status: str | None = None) -> list[ProposalRecord]:
        return self.memory.list_proposals(status=status)

    def approve(self, proposal_id: int) -> ProposalRecord:
        self._require_status(proposal_id, {"pending"}, "approve")
        return self.memory.set_proposal_status(proposal_id, "approved")

    def reject(self, proposal_id: int) -> ProposalRecord:
        self._require_status(proposal_id, {"pending"}, "reject")
        return self.memory.set_proposal_status(proposal_id, "rejected")

    def apply(self, proposal_id: int) -> ProposalRecord:
        if self.safety_switch is not None and self.safety_switch.is_engaged():
            raise ValueError("Odin is halted (emergency stop engaged); cannot apply changes.")
        record = self._require_status(proposal_id, {"approved"}, "apply")
        self._write_target(record.kind, record.target, record.proposed_value)
        applied = self.memory.set_proposal_status(proposal_id, "applied")
        self._publish("improvement.applied", applied)
        return applied

    def revert(self, proposal_id: int) -> ProposalRecord:
        record = self._require_status(proposal_id, {"applied"}, "revert")
        # Restore the captured prior value. None means the target had no value
        # before (e.g. an unset setting); write back an empty string.
        self._write_target(record.kind, record.target, record.current_value or "")
        reverted = self.memory.set_proposal_status(proposal_id, "reverted")
        self._publish("improvement.reverted", reverted)
        return reverted

    # --- target read/write -------------------------------------------------

    def _read_target(self, kind: str, target: str) -> str | None:
        if kind == "memory":
            return self.memory.get_memory_blocks().get(target)
        if kind == "setting":
            # JSON so non-string settings (bools, numbers) round-trip faithfully.
            return json.dumps(self.settings.read().get(target))
        raise ValueError(f"Invalid proposal kind: {kind}")

    def _write_target(self, kind: str, target: str, value_text: str) -> None:
        if kind == "memory":
            self.memory.update_memory_block(target, value_text)
            return
        if kind == "setting":
            try:
                value: Any = json.loads(value_text)
            except (json.JSONDecodeError, TypeError):
                value = value_text
            self.settings.update({target: value})
            return
        raise ValueError(f"Invalid proposal kind: {kind}")

    def _require_status(
        self, proposal_id: int, allowed: set[str], action: str
    ) -> ProposalRecord:
        record = self.memory.get_proposal(proposal_id)
        if record.status not in allowed:
            raise ValueError(
                f"Cannot {action} proposal in status '{record.status}'"
                f" (expected one of: {', '.join(sorted(allowed))})"
            )
        return record

    def _publish(self, event_type: str, record: ProposalRecord) -> None:
        if self.event_bus is not None:
            self.event_bus.publish(event_type, record.to_api())
