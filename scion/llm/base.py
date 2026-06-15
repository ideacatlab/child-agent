"""LLM interface + normalized response types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


@dataclass
class LLMResponse:
    text: str                       # concatenated visible text
    content: list[dict]             # assistant content blocks (dicts, JSON-safe)
    tool_uses: list[dict] = field(default_factory=list)  # {"id","name","input"}
    stop_reason: str | None = None
    usage: dict = field(default_factory=dict)
    model: str = ""

    @property
    def wants_tools(self) -> bool:
        return self.stop_reason == "tool_use" or bool(self.tool_uses)


class LLMClient(Protocol):
    def complete(
        self,
        *,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream_cb: Callable[[str], None] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse: ...

    def simple(self, prompt: str, *, system: str | None = None, max_tokens: int = 1024) -> str: ...


def block_to_dict(block: Any) -> dict:
    """Normalize an SDK content block (or dict) into a JSON-safe dict.

    Critically preserves thinking-block ``signature`` so blocks can be replayed
    unchanged on the next turn (required for adaptive thinking + tool use).
    """
    if isinstance(block, dict):
        return block
    for attr in ("model_dump",):
        fn = getattr(block, attr, None)
        if callable(fn):
            try:
                return fn(mode="json", exclude_none=True)
            except TypeError:
                return fn()
    # last-resort manual extraction
    btype = getattr(block, "type", "text")
    out: dict[str, Any] = {"type": btype}
    for key in ("text", "thinking", "signature", "data", "id", "name", "input"):
        val = getattr(block, key, None)
        if val is not None:
            out[key] = val
    return out
