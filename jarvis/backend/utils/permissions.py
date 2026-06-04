from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class PermissionDecision(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"
    PROMPT = "prompt"


@dataclass(frozen=True, slots=True)
class Permission:
    name: str
    description: str
    default: PermissionDecision


class PermissionManager:
    def __init__(self, permissions: dict[str, Permission]) -> None:
        self._permissions = permissions

    @classmethod
    def from_manifest(cls, path: Path) -> "PermissionManager":
        with path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        permissions = {
            item["name"]: Permission(
                name=item["name"],
                description=item["description"],
                default=PermissionDecision(item["default"]),
            )
            for item in raw.get("permissions", [])
        }
        return cls(permissions)

    def decision_for(self, permission_name: str) -> PermissionDecision:
        permission = self._permissions.get(permission_name)
        if permission is None:
            return PermissionDecision.DENIED
        return permission.default

    def update_decisions(self, decisions: dict[str, str]) -> None:
        updated = dict(self._permissions)
        for name, raw_decision in decisions.items():
            permission = self._permissions.get(name)
            if permission is None:
                raise ValueError(f"Unknown permission: {name}")
            decision = PermissionDecision(raw_decision)
            updated[name] = Permission(
                name=permission.name,
                description=permission.description,
                default=decision,
            )
        self._permissions = updated

    def require_allowed(self, permission_name: str) -> None:
        decision = self.decision_for(permission_name)
        if decision != PermissionDecision.ALLOWED:
            raise PermissionError(f"Permission {permission_name} is {decision.value}")

    def as_settings(self) -> dict[str, str]:
        return {name: permission.default.value for name, permission in self._permissions.items()}
