"""Agent-control tools: message the operator mid-task, delegate to a subagent."""

from __future__ import annotations

import threading

from scion.agent.runtime import current_channel
from scion.logging import get_logger
from scion.security.policy import MODERATE
from scion.tools.base import ToolError, tool

log = get_logger("tools.agent")

_depth = threading.local()
_MAX_DEPTH = 2


@tool(risk=MODERATE)
def send_update(text: str) -> str:
    """Send the operator a message right now (a progress update or partial result).

    Useful on long tasks so the operator isn't left waiting in silence.

    Args:
        text: the message to deliver verbatim.
    """
    channel = current_channel()
    if channel is None:
        log.info("send_update (no channel): %s", text[:200])
        return "no active channel; logged the update"
    channel.send(text)
    return "delivered"


@tool(risk=MODERATE)
def spawn_subagent(task: str, context: str = "") -> str:
    """Delegate an independent subtask to a fresh subagent and return its result.

    Use for self-contained work you can describe fully (the subagent shares the
    filesystem and tools but not this conversation). Don't delegate something you
    can finish directly.

    Args:
        task: the complete instruction for the subagent.
        context: any extra context it needs (it cannot see this conversation).
    """
    depth = getattr(_depth, "value", 0)
    if depth >= _MAX_DEPTH:
        raise ToolError("subagent recursion limit reached; do this work directly")

    from scion.agent.loop import AgentLoop
    from scion.agent.session import Session

    prompt = task if not context else f"{task}\n\nContext:\n{context}"
    _depth.value = depth + 1
    try:
        loop = AgentLoop()
        result = loop.run(prompt, session=Session.new("sub"), autonomous=True)
    finally:
        _depth.value = depth
    return result or "(subagent produced no output)"
