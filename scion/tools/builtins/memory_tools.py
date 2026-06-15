"""Memory tools: remember durable facts, search memory, maintain core blocks."""

from __future__ import annotations

from scion.memory.store import get_memory
from scion.security.policy import MODERATE, SAFE
from scion.tools.base import tool


@tool(risk=MODERATE)
def remember(fact: str) -> str:
    """Save a durable fact or lesson to long-term memory (MEMORY.md).

    Args:
        fact: a concise, reusable fact or lesson worth keeping.
    """
    return get_memory().remember(fact)


@tool(risk=SAFE, parallel_safe=True)
def search_memory(query: str, limit: int = 8) -> str:
    """Search long-term memory, the operator profile, and journals.

    Args:
        query: words to look for.
        limit: max results.
    """
    hits = get_memory().search(query, limit=limit)
    if not hits:
        return "(nothing relevant in memory)"
    return "\n".join(f"[{src}] {line}" for src, line in hits)


@tool(risk=MODERATE)
def update_user(note: str) -> str:
    """Record something learned about the operator (their profile, USER.md).

    Args:
        note: a fact/preference/constraint about the operator.
    """
    return get_memory().update_user(note)


@tool(risk=MODERATE)
def journal(note: str) -> str:
    """Append a short note to today's episodic journal.

    Args:
        note: what happened / what you did.
    """
    return get_memory().journal(note)


@tool(risk=MODERATE)
def core_memory_append(block: str, text: str) -> str:
    """Append to a core-memory block kept in the system prompt every turn.

    Args:
        block: block label, e.g. ``current_task`` or ``open_loops``.
        text: text to append.
    """
    b = get_memory().blocks.append(block, text)
    return f"{block} now {len(b.value)}/{b.limit} chars"


@tool(risk=MODERATE)
def core_memory_replace(block: str, old: str, new: str) -> str:
    """Replace text inside a core-memory block.

    Args:
        block: block label.
        old: text to find.
        new: replacement.
    """
    try:
        get_memory().blocks.replace(block, old, new)
    except KeyError:
        return f"no such block: {block}"
    return f"updated {block}"
