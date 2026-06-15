"""Claude via the official Anthropic SDK.

Uses streaming (avoids HTTP timeouts on long/agentic turns), adaptive thinking,
the effort control, and prompt caching on the system prompt (which also caches
the tool list, since tools render before system). Responses are normalized to
plain dicts by :func:`scion.llm.base.block_to_dict`.
"""

from __future__ import annotations

from typing import Callable

from scion.config import Settings, get_settings
from scion.llm.base import LLMResponse, block_to_dict
from scion.logging import get_logger

log = get_logger("llm.anthropic")


class AnthropicClient:
    def __init__(self, settings: Settings | None = None) -> None:
        import anthropic  # lazy: keeps the package importable without the SDK

        self.s = settings or get_settings()
        self._sdk = anthropic
        self.client = anthropic.Anthropic()
        self.model = self.s.model

    # ------------------------------------------------------------------ #
    def complete(
        self,
        *,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream_cb: Callable[[str], None] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        base = {
            "model": self.model,
            "max_tokens": max_tokens or self.s.max_tokens,
            "system": [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ],
            "messages": messages,
        }
        if tools:
            base["tools"] = tools

        extras: dict = {}
        if self.s.thinking == "adaptive":
            extras["thinking"] = {"type": "adaptive"}
        if self.s.effort:
            extras["output_config"] = {"effort": self.s.effort}

        final = self._stream(base, extras, stream_cb)
        content = [block_to_dict(b) for b in final.content]
        text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
        tool_uses = [
            {"id": b["id"], "name": b["name"], "input": b.get("input", {})}
            for b in content
            if b.get("type") == "tool_use"
        ]
        usage = {}
        if getattr(final, "usage", None):
            usage = {
                "input": getattr(final.usage, "input_tokens", 0),
                "output": getattr(final.usage, "output_tokens", 0),
                "cache_read": getattr(final.usage, "cache_read_input_tokens", 0) or 0,
            }
        return LLMResponse(
            text=text,
            content=content,
            tool_uses=tool_uses,
            stop_reason=getattr(final, "stop_reason", None),
            usage=usage,
            model=getattr(final, "model", self.model),
        )

    def _stream(self, base: dict, extras: dict, stream_cb):
        try:
            cm = self.client.messages.stream(**base, **extras)
        except TypeError:
            # older SDK: route newer params through extra_body
            cm = self.client.messages.stream(**base, extra_body=extras)
        with cm as stream:
            try:
                for text in stream.text_stream:
                    if stream_cb:
                        stream_cb(text)
            except self._sdk.APIError:
                raise
            return stream.get_final_message()

    # ------------------------------------------------------------------ #
    def simple(self, prompt: str, *, system: str | None = None, max_tokens: int = 1024) -> str:
        resp = self.complete(
            system=system or "You are a concise, helpful assistant.",
            messages=[{"role": "user", "content": prompt}],
            tools=None,
            max_tokens=max_tokens,
        )
        return resp.text
