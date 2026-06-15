"""Task-queue tools: enqueue background work, inspect the queue."""

from __future__ import annotations

from scion.queue.task_queue import get_queue
from scion.security.policy import MODERATE, SAFE
from scion.tools.base import tool


@tool(risk=MODERATE)
def enqueue_task(text: str, kind: str = "chat", priority: int = 0) -> str:
    """Queue a task for the background worker to pick up and run later.

    Use this to defer or schedule work, or to split a big job into independent
    units the worker can drain.

    Args:
        text: the task instruction.
        kind: a label, e.g. ``chat`` / ``research`` / ``maintenance``.
        priority: higher runs first.
    """
    task_id, is_new = get_queue().add(text, kind=kind, source="agent", priority=priority)
    return f"queued task #{task_id}" + ("" if is_new else " (already queued)")


@tool(risk=SAFE, parallel_safe=True)
def list_tasks(status: str = "", limit: int = 15) -> str:
    """List recent tasks, optionally filtered by status.

    Args:
        status: pending|working|done|failed|skipped|obsolete (empty = any).
        limit: max rows.
    """
    q = get_queue()
    tasks = q.recent(limit=limit, status=status or None)
    if not tasks:
        return f"counts: {q.counts() or 'empty'}\n(no matching tasks)"
    lines = [f"#{t.id} [{t.status}] {t.kind}: {t.text[:80]}" for t in tasks]
    return f"counts: {q.counts()}\n" + "\n".join(lines)
