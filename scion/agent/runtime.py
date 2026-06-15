"""Per-run context (the active channel + session), exposed to tools.

A tiny contextvars-based ambient context so tools like ``send_update`` or
``ask_user`` can reach the surface the agent is currently talking to without
threading it through every signature.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scion.channels.base import Channel

_CTX: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("scion_runtime", default=None)


@dataclass
class RuntimeContext:
    channel: "Channel | None" = None
    session_id: str = ""
    task_id: int | None = None


def set_runtime(ctx: RuntimeContext) -> contextvars.Token:
    return _CTX.set({"ctx": ctx})


def reset_runtime(token: contextvars.Token) -> None:
    _CTX.reset(token)


def current() -> RuntimeContext:
    data = _CTX.get()
    if not data:
        return RuntimeContext()
    return data["ctx"]


def current_channel() -> "Channel | None":
    return current().channel
