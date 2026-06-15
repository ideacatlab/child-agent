"""Skill authoring: write durable playbooks (SKILL.md) for the agent to reuse."""

from __future__ import annotations

import re

from scion.config import get_settings
from scion.security.policy import MODERATE, SAFE
from scion.security.secrets import looks_like_secret
from scion.skills.loader import get_skills
from scion.tools.base import ToolError, tool

_NAME = re.compile(r"^[a-z0-9][a-z0-9\-]{1,48}$")


@tool(risk=MODERATE)
def author_skill(name: str, description: str, body: str) -> str:
    """Write a reusable skill (a playbook) the agent loads on demand.

    A skill is Markdown instructions for a recurring task. Once written it appears
    in the skill index and can be read and followed later. This is how you turn a
    workflow you figured out into permanent know-how.

    Args:
        name: kebab-case skill name (e.g. ``competitor-research``).
        description: one line describing when to use it (shown in the index).
        body: the Markdown instructions / playbook.
    """
    name = name.strip().lower()
    if not _NAME.match(name):
        raise ToolError("name must be kebab-case, 2-49 chars, e.g. 'lead-qualification'")
    if looks_like_secret(body) or looks_like_secret(description):
        raise ToolError("refusing to save a skill containing secret-like values")

    s = get_settings()
    skill_dir = s.root / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    front = f"---\nname: {name}\ndescription: {description.strip()}\n---\n\n"
    (skill_dir / "SKILL.md").write_text(front + body.strip() + "\n", encoding="utf-8")
    get_skills(fresh=True)  # reload so it's usable immediately
    return f"wrote skill '{name}'. It's now in the skill index."


@tool(risk=SAFE, parallel_safe=True)
def read_skill(name: str) -> str:
    """Read a skill's full instructions by name.

    Args:
        name: the skill name from the index.
    """
    skill = get_skills().get(name)
    if skill is None:
        return f"no such skill: {name}"
    return skill.body()


@tool(risk=SAFE, parallel_safe=True)
def list_skills() -> str:
    """List available skills (name + description)."""
    return get_skills(fresh=True).index() or "(no skills yet)"
