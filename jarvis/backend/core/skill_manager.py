"""Agent Skills runtime for Odin.

Loads Agent-Skills-spec skills (a folder with a ``SKILL.md`` that has YAML-ish
frontmatter ``name``/``description`` plus a markdown body of instructions) from a
skills directory, matches them to the current request, and exposes the matched
guidance as grounded context lines. Compatible with skills installed via
``npx skills add <owner>/<repo>`` as well as hand-authored ones.

Following Odin's convention, a missing/empty skills directory is a no-op rather
than an error: the manager simply has zero skills. Skill *content* is treated as
user-installed reference material injected into context; it never bypasses the
permission-gated bots, which remain the only path to side effects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Short words carry little matching signal; drop them so scores reflect real overlap.
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_MIN_TOKEN_LEN = 3
# Cap how much of a skill body is injected, to keep prompt cost bounded.
_MAX_BODY_CHARS = 1500


def _tokenize(text: str) -> set[str]:
    return {tok for tok in _TOKEN_RE.findall(text.lower()) if len(tok) >= _MIN_TOKEN_LEN}


@dataclass(frozen=True, slots=True)
class SkillInfo:
    name: str
    description: str
    path: str
    body: str = field(default="", repr=False)


def parse_skill_md(text: str) -> tuple[dict[str, str], str]:
    """Split a SKILL.md into (frontmatter, body).

    Minimal single-line ``key: value`` frontmatter parsing — enough for the
    ``name``/``description`` the spec requires, without a YAML dependency. Files
    without frontmatter are treated as all-body.
    """
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            frontmatter: dict[str, str] = {}
            for line in parts[1].splitlines():
                if ":" in line and not line.lstrip().startswith("#"):
                    key, _, value = line.partition(":")
                    frontmatter[key.strip().lower()] = value.strip().strip("\"'")
            return frontmatter, parts[2].strip()
    return {}, text.strip()


class SkillManager:
    def __init__(self, skills_dir: Path, max_matches: int = 2) -> None:
        self.skills_dir = skills_dir
        self.max_matches = max_matches
        self._skills: dict[str, SkillInfo] = {}
        self.reload()

    def reload(self) -> list[SkillInfo]:
        """(Re)scan the skills directory. Never raises; bad skills are skipped."""
        skills: dict[str, SkillInfo] = {}
        try:
            entries = sorted(self.skills_dir.iterdir()) if self.skills_dir.is_dir() else []
        except OSError:
            entries = []
        for entry in entries:
            skill_md = entry / "SKILL.md"
            if not entry.is_dir() or not skill_md.is_file():
                continue
            try:
                text = skill_md.read_text(encoding="utf-8")
            except OSError:
                continue
            frontmatter, body = parse_skill_md(text)
            name = frontmatter.get("name") or entry.name
            description = frontmatter.get("description") or ""
            skills[name] = SkillInfo(
                name=name, description=description, path=str(entry), body=body
            )
        self._skills = skills
        return self.list_skills()

    def list_skills(self) -> list[SkillInfo]:
        return sorted(self._skills.values(), key=lambda skill: skill.name)

    def get(self, name: str) -> SkillInfo | None:
        return self._skills.get(name)

    def _score(self, message_tokens: set[str], skill: SkillInfo) -> int:
        # Name matches are the strongest signal; description words add supporting weight.
        name_hits = message_tokens & _tokenize(skill.name.replace("-", " "))
        desc_hits = message_tokens & _tokenize(skill.description)
        return 3 * len(name_hits) + len(desc_hits)

    def match(self, message: str, min_score: int = 2) -> list[SkillInfo]:
        """Return the installed skills most relevant to ``message`` (best first)."""
        tokens = _tokenize(message)
        if not tokens or not self._skills:
            return []
        scored = [
            (self._score(tokens, skill), skill) for skill in self._skills.values()
        ]
        ranked = sorted(
            (pair for pair in scored if pair[0] >= min_score),
            key=lambda pair: pair[0],
            reverse=True,
        )
        return [skill for _, skill in ranked[: self.max_matches]]

    def skill_context(self, message: str) -> list[str]:
        """Grounded context lines for the skills relevant to ``message``."""
        lines: list[str] = []
        for skill in self.match(message):
            body = skill.body[:_MAX_BODY_CHARS]
            if len(skill.body) > _MAX_BODY_CHARS:
                body += "\n…(truncated; open the skill file for the full instructions)"
            lines.append(
                f"[Installed skill: {skill.name}] This user-installed skill is relevant "
                f"to the request. Follow its guidance where it helps; any actions it "
                f"describes still go through your normal permission-gated tools.\n{body}"
            )
        return lines
