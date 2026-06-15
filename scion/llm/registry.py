"""Provider registry. Default is Anthropic/Claude; register others by name."""

from __future__ import annotations

import os
from typing import Callable

from scion.llm.base import LLMClient

_PROVIDERS: dict[str, Callable[[], LLMClient]] = {}
_INSTANCE: LLMClient | None = None


def register_provider(name: str, factory: Callable[[], LLMClient]) -> None:
    _PROVIDERS[name] = factory


def _default_anthropic() -> LLMClient:
    from scion.llm.anthropic_client import AnthropicClient

    return AnthropicClient()


register_provider("anthropic", _default_anthropic)
register_provider("claude", _default_anthropic)


def get_llm(*, fresh: bool = False) -> LLMClient:
    global _INSTANCE
    if _INSTANCE is not None and not fresh:
        return _INSTANCE
    name = os.environ.get("SCION_LLM_PROVIDER", "anthropic").strip().lower()
    factory = _PROVIDERS.get(name, _default_anthropic)
    _INSTANCE = factory()
    return _INSTANCE
