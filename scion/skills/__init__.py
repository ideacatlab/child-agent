"""Skills — durable, on-demand workflows as ``SKILL.md`` folders.

A skill is a Markdown file with YAML-ish frontmatter (``name`` + ``description``)
and a body of instructions/playbook. Only the lean metadata sits in context by
default; the body is loaded when the task calls for it (progressive disclosure —
the OpenClaw/Hermes/Anthropic skills pattern). Skills are how a forked scion
becomes a *specialist* without bloating the system prompt.
"""

from scion.skills.loader import Skill, SkillLibrary, get_skills

__all__ = ["Skill", "SkillLibrary", "get_skills"]
