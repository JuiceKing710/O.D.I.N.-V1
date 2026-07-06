from __future__ import annotations

import ast
import asyncio
from pathlib import Path

from jarvis.backend.bots.base import Bot, BotRequest, BotResponse


class CodeBot(Bot):
    name = "code"
    description = "Analyzes code-related requests without executing generated code."
    # Reading and AST-parsing a large source file can stall on slow storage;
    # give it headroom beyond the 10s default.
    timeout_seconds = 30.0

    async def on_request(self, request: BotRequest) -> BotResponse:
        if request.action != "analyze":
            return BotResponse(ok=False, error=f"Unsupported code action: {request.action}")
        raw_path = str(request.payload.get("path") or request.payload.get("text") or "").strip()
        if not raw_path:
            return BotResponse(ok=False, error="Code file path is required")
        try:
            self.permission_manager.require_allowed(
                "read_files",
                actor=request.sender,
                reason=f"Analyze code file: {raw_path}",
                metadata=self.permission_metadata(request),
            )
        except PermissionError as exc:
            return self.permission_response(exc)
        # File read + parse runs off the event loop like the other bots' blocking work.
        return await asyncio.to_thread(self._analyze, raw_path)

    @staticmethod
    def _analyze(raw_path: str) -> BotResponse:
        path = Path(raw_path).expanduser()
        if not path.is_file():
            return BotResponse(ok=False, error=f"Code file does not exist: {path}")
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return BotResponse(ok=False, error=str(exc))

        lines = content.splitlines()
        report = {
            "path": str(path.resolve()),
            "language": path.suffix.lstrip(".") or "unknown",
            "line_count": len(lines),
            "character_count": len(content),
            "todo_count": sum(
                line.count(marker) for line in lines for marker in ("TODO", "FIXME", "HACK")
            ),
        }
        if path.suffix == ".py":
            try:
                tree = ast.parse(content)
                report["function_count"] = sum(
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    for node in ast.walk(tree)
                )
                report["class_count"] = sum(
                    isinstance(node, ast.ClassDef) for node in ast.walk(tree)
                )
                report["syntax_ok"] = True
            except SyntaxError as exc:
                report["syntax_ok"] = False
                report["syntax_error"] = f"{exc.msg} at line {exc.lineno}"

        summary = (
            f"Analyzed {report['path']}: {report['line_count']} lines, "
            f"{report['todo_count']} TODO/FIXME/HACK marker(s)."
        )
        return BotResponse(ok=True, payload={"text": summary, "analysis": report})

    def capabilities(self) -> list[str]:
        return ["analyze"]
