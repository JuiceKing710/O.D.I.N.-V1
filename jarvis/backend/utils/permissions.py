from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4


class PermissionDecision(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"
    PROMPT = "prompt"


@dataclass(frozen=True, slots=True)
class Permission:
    name: str
    description: str
    default: PermissionDecision


@dataclass(frozen=True, slots=True)
class PermissionRequest:
    request_id: str
    permission: str
    actor: str
    reason: str
    created_at: datetime
    metadata: dict[str, Any]

    def to_api(self) -> dict[str, str]:
        return {
            "request_id": self.request_id,
            "permission": self.permission,
            "actor": self.actor,
            "reason": self.reason,
            "created_at": self.created_at.isoformat(),
        }


class PermissionApprovalRequired(PermissionError):
    def __init__(self, request: PermissionRequest) -> None:
        self.request = request
        super().__init__(
            f"Permission {request.permission} requires approval "
            f"(request {request.request_id})"
        )


class PermissionManager:
    def __init__(self, permissions: dict[str, Permission]) -> None:
        self._permissions = permissions
        self._pending_requests: dict[str, PermissionRequest] = {}
        self._one_time_grants: dict[tuple[str, str, str], int] = {}

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

    def require_allowed(
        self,
        permission_name: str,
        *,
        actor: str = "user",
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        decision = self.decision_for(permission_name)
        if decision == PermissionDecision.ALLOWED:
            return
        if decision == PermissionDecision.DENIED:
            raise PermissionError(f"Permission {permission_name} is denied")

        grant_key = (permission_name, actor, reason)
        remaining_grants = self._one_time_grants.get(grant_key, 0)
        if remaining_grants:
            if remaining_grants == 1:
                self._one_time_grants.pop(grant_key)
            else:
                self._one_time_grants[grant_key] = remaining_grants - 1
            return

        for pending in self._pending_requests.values():
            if (pending.permission, pending.actor, pending.reason) == grant_key:
                raise PermissionApprovalRequired(pending)
        request = PermissionRequest(
            request_id=uuid4().hex,
            permission=permission_name,
            actor=actor,
            reason=reason,
            created_at=datetime.now(timezone.utc),
            metadata=metadata or {},
        )
        self._pending_requests[request.request_id] = request
        raise PermissionApprovalRequired(request)

    def pending_requests(self) -> list[PermissionRequest]:
        return sorted(self._pending_requests.values(), key=lambda request: request.created_at)

    def resolve_request(self, request_id: str, decision: PermissionDecision) -> PermissionRequest:
        request = self._pending_requests.pop(request_id, None)
        if request is None:
            raise ValueError(f"Permission request not found: {request_id}")
        if decision == PermissionDecision.PROMPT:
            raise ValueError("Permission request decision must be allowed or denied")
        if decision == PermissionDecision.ALLOWED:
            grant_key = (request.permission, request.actor, request.reason)
            self._one_time_grants[grant_key] = self._one_time_grants.get(grant_key, 0) + 1
        return request

    def as_settings(self) -> dict[str, str]:
        return {name: permission.default.value for name, permission in self._permissions.items()}
