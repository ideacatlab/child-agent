"""LLM provider layer.

The harness is Claude-first (the one hard dependency), but the loop talks to a
small :class:`~scion.llm.base.LLMClient` interface so a provider is a swappable
plugin. Responses are normalized to plain dicts so the transcript is JSON and
round-trips cleanly across turns (thinking blocks preserved unchanged).
"""

from scion.llm.base import LLMClient, LLMResponse
from scion.llm.registry import get_llm

__all__ = ["LLMClient", "LLMResponse", "get_llm"]
