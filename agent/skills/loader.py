"""Load and index ``SKILL.md`` skills with progressive disclosure."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent.config import get_settings


@dataclass
class Skill:
    name: str
    description: str
    path: Path

    def body(self) -> str:
        """Read the full instruction body (everything after the frontmatter)."""
        text = self.path.read_text(encoding="utf-8")
        _, body = _split_frontmatter(text)
        return body.strip()


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Parse leading ``--- ... ---`` frontmatter (simple ``key: value`` lines)."""
    meta: dict[str, str] = {}
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            block = text[3:end].strip()
            body = text[end + 4 :]
            for line in block.splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    meta[k.strip().lower()] = v.strip().strip('"').strip("'")
            return meta, body
    return meta, text


class SkillLibrary:
    def __init__(self, dirs: list[Path] | None = None) -> None:
        self.dirs = dirs or get_settings().skills_dirs
        self._skills: dict[str, Skill] = {}
        self.reload()

    def reload(self) -> None:
        self._skills.clear()
        for d in self.dirs:
            d = Path(d)
            if not d.exists():
                continue
            for skill_md in sorted(d.glob("*/SKILL.md")):
                try:
                    meta, _ = _split_frontmatter(skill_md.read_text(encoding="utf-8"))
                except OSError:
                    continue
                name = meta.get("name") or skill_md.parent.name
                desc = meta.get("description", "").strip()
                self._skills[name] = Skill(name=name, description=desc, path=skill_md)

    def all(self) -> list[Skill]:
        return list(self._skills.values())

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def index(self) -> str:
        """A compact, always-in-context listing (name + one-line description)."""
        if not self._skills:
            return ""
        lines = [f"- {s.name}: {s.description}" for s in self._skills.values()]
        return "\n".join(lines)


_LIB: SkillLibrary | None = None


def get_skills(*, fresh: bool = False) -> SkillLibrary:
    global _LIB
    if _LIB is None or fresh:
        _LIB = SkillLibrary()
    return _LIB
