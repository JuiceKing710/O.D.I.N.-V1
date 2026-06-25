from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
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

    def to_api(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "permission": self.permission,
            "actor": self.actor,
            "reason": self.reason,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }


class PermissionApprovalRequired(PermissionError):
    def __init__(self, request: PermissionRequest) -> None:
        self.request = request
        super().__init__(
            f"Permission {request.permission} requires approval "
            f"(request {request.request_id})"
        )


class PermissionManager:
    def __init__(self, permissions: dict[str, Permission], storage_path: Path | None = None) -> None:
        self._permissions = permissions
        self.storage_path = storage_path
        self._pending_requests: dict[str, PermissionRequest] = {}
        self._one_time_grants: dict[tuple[str, str, str], int] = {}
        # Pre-approved permission scopes, keyed by scope id. While a scope is
        # open, the permissions it lists are treated as allowed without prompting
        # — this is how an autonomous agent runs a whole plan unattended after
        # the user grants it a scope up front. A scope never overrides a hard
        # `denied` default, so execute_scripts stays locked unless explicitly on.
        self._active_scopes: dict[str, set[str]] = {}
        self._load_pending_requests()

    @classmethod
    def from_manifest(cls, path: Path, storage_path: Path | None = None) -> "PermissionManager":
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
        return cls(permissions, storage_path=storage_path)

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

        if self._in_open_scope(permission_name):
            return

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
        self._save_pending_requests()
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
        self._save_pending_requests()
        return request

    def open_scope(self, permissions: Iterable[str]) -> str:
        """Pre-approve `permissions` until the returned scope id is closed.

        Used by autonomous agents: the user grants the scope once at launch and
        the agent then runs its full plan without per-step prompts. Hard-denied
        permissions are intentionally not elevated by a scope.
        """
        scope_id = uuid4().hex
        self._active_scopes[scope_id] = set(permissions)
        return scope_id

    def close_scope(self, scope_id: str) -> None:
        self._active_scopes.pop(scope_id, None)

    @contextmanager
    def scope(self, permissions: Iterable[str]) -> Iterator[str]:
        """Context-managed scope that always closes, even if the agent errors."""
        scope_id = self.open_scope(permissions)
        try:
            yield scope_id
        finally:
            self.close_scope(scope_id)

    def _in_open_scope(self, permission_name: str) -> bool:
        return any(permission_name in granted for granted in self._active_scopes.values())

    def as_settings(self) -> dict[str, str]:
        return {name: permission.default.value for name, permission in self._permissions.items()}

    def _load_pending_requests(self) -> None:
        if self.storage_path is None or not self.storage_path.is_file():
            return
        try:
            raw = json.loads(self.storage_path.read_text(encoding="utf-8"))
            for item in raw:
                request = PermissionRequest(
                    request_id=item["request_id"],
                    permission=item["permission"],
                    actor=item["actor"],
                    reason=item["reason"],
                    created_at=datetime.fromisoformat(item["created_at"]),
                    metadata=item.get("metadata") or {},
                )
                self._pending_requests[request.request_id] = request
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            self._pending_requests = {}

    def _save_pending_requests(self) -> None:
        if self.storage_path is None:
            return
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [request.to_api() for request in self.pending_requests()]
        self.storage_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
