from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Callable
from typing import Any

from jarvis.backend.bots.base import Bot, BotRequest, BotResponse

# A finished osascript invocation: the executable plus its arguments.
Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


class DesktopBot(Bot):
    """Drives native macOS apps via AppleScript behind a control-desktop permission.

    This is the lean, dependency-free path to "Odin can operate the machine": it
    shells out to ``osascript`` (built into macOS) rather than pulling in pyobjc.
    Every user-supplied value is passed to AppleScript through ``argv`` and read
    with ``item N of argv`` — never interpolated into the script text — so an app
    name or typed string can't break out and inject AppleScript.

    A pyobjc Accessibility backend can replace ``_runner`` later for finer-grained
    element control without changing this bot's surface.
    """

    name = "desktop"
    description = "Controls native macOS apps via AppleScript behind a control-desktop permission."

    TIMEOUT_SECONDS = 30.0
    # Dispatch must outlive the osascript timeout above, with margin.
    timeout_seconds = 35.0

    def __init__(
        self,
        permission_manager,
        audit_logger,
        runner: Runner | None = None,
    ) -> None:
        super().__init__(permission_manager, audit_logger)
        self._runner = runner or self._default_runner

    def capabilities(self) -> list[str]:
        return ["activate", "keystroke", "menu", "state"]

    async def on_request(self, request: BotRequest) -> BotResponse:
        builders = {
            "activate": self._activate,
            "keystroke": self._keystroke,
            "menu": self._menu,
            "state": self._state,
        }
        builder = builders.get(request.action)
        if builder is None:
            return BotResponse(ok=False, error=f"Unsupported desktop action: {request.action}")
        try:
            self.permission_manager.require_allowed(
                "control_desktop",
                actor=request.sender,
                reason=f"Desktop {request.action}",
                metadata=self.permission_metadata(request),
            )
        except PermissionError as exc:
            return self.permission_response(exc)
        try:
            script_lines, args = builder(request.payload)
        except ValueError as exc:
            return BotResponse(ok=False, error=str(exc))
        # osascript blocks for up to TIMEOUT_SECONDS; keep it off the event loop.
        return await asyncio.to_thread(self._execute, request.action, script_lines, args)

    # ---- action builders (return AppleScript lines + argv) ----------------

    @staticmethod
    def _activate(payload: dict[str, Any]) -> tuple[list[str], list[str]]:
        app = str(payload.get("text") or payload.get("app") or "").strip()
        if not app:
            raise ValueError("An application name is required")
        return (
            ["on run argv", "tell application (item 1 of argv) to activate", "end run"],
            [app],
        )

    @staticmethod
    def _keystroke(payload: dict[str, Any]) -> tuple[list[str], list[str]]:
        text = str(payload.get("text") or "").strip()
        if not text:
            raise ValueError("Keystroke text is required")
        return (
            [
                "on run argv",
                'tell application "System Events" to keystroke (item 1 of argv)',
                "end run",
            ],
            [text],
        )

    @staticmethod
    def _menu(payload: dict[str, Any]) -> tuple[list[str], list[str]]:
        app = str(payload.get("app") or "").strip()
        menu = str(payload.get("menu") or "").strip()
        item = str(payload.get("item") or "").strip()
        if not (app and menu and item):
            raise ValueError("A menu click requires app, menu, and item")
        return (
            [
                "on run argv",
                'tell application "System Events" to tell process (item 1 of argv) to '
                "click menu item (item 3 of argv) of menu (item 2 of argv) of menu bar 1",
                "end run",
            ],
            [app, menu, item],
        )

    @staticmethod
    def _state(payload: dict[str, Any]) -> tuple[list[str], list[str]]:
        return (
            [
                'tell application "System Events" to get '
                "name of first application process whose frontmost is true"
            ],
            [],
        )

    # ---- execution --------------------------------------------------------

    def _execute(self, action: str, script_lines: list[str], args: list[str]) -> BotResponse:
        command = ["osascript"]
        for line in script_lines:
            command += ["-e", line]
        if args:
            command.append("--")
            command += args
        try:
            result = self._runner(command)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return BotResponse(ok=False, error=f"Desktop automation failed: {exc}")
        if result.returncode != 0:
            detail = (result.stderr or "").strip() or f"osascript exited {result.returncode}"
            return BotResponse(ok=False, error=detail)
        text = (result.stdout or "").strip() or f"Desktop {action} completed"
        return BotResponse(ok=True, payload={"text": text, "command": command})

    def _default_runner(self, command: list[str]) -> "subprocess.CompletedProcess[str]":
        return subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=self.TIMEOUT_SECONDS,
        )
