from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from jarvis.backend.bots.base import Bot, BotRequest, BotResponse


class SystemBot(Bot):
    name = "system"
    description = "Mediates local system actions behind explicit permissions."

    async def on_request(self, request: BotRequest) -> BotResponse:
        if request.action != "execute":
            return BotResponse(ok=False, error=f"Unsupported system action: {request.action}")
        try:
            self.permission_manager.require_allowed("execute_scripts")
        except PermissionError as exc:
            return BotResponse(ok=False, error=str(exc))
        command = str(request.payload.get("text", "")).strip()
        if not command:
            return BotResponse(ok=False, error="Command text is required")
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            return BotResponse(ok=False, error=f"Invalid command: {exc}")
        if not argv:
            return BotResponse(ok=False, error="Command text is required")
        cwd = Path(str(request.payload.get("cwd", "."))).expanduser()
        if not cwd.is_dir():
            return BotResponse(ok=False, error=f"Working directory does not exist: {cwd}")
        try:
            timeout = min(max(float(request.payload.get("timeout_seconds", 30)), 1), 120)
        except (TypeError, ValueError):
            return BotResponse(ok=False, error="Command timeout must be a number")
        try:
            result = subprocess.run(
                argv,
                capture_output=True,
                check=False,
                cwd=cwd,
                shell=False,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return BotResponse(ok=False, error=f"Command execution failed: {exc}")
        stdout = result.stdout[-8000:]
        stderr = result.stderr[-8000:]
        text = stdout.strip() or stderr.strip() or f"Command exited with code {result.returncode}"
        return BotResponse(
            ok=result.returncode == 0,
            payload={
                "text": text,
                "command": argv,
                "cwd": str(cwd.resolve()),
                "exit_code": result.returncode,
                "stdout": stdout,
                "stderr": stderr,
            },
            error=None if result.returncode == 0 else f"Command exited with code {result.returncode}",
        )

    def capabilities(self) -> list[str]:
        return ["execute"]
