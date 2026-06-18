"""Channels — how the agent reaches the operator.

Telegram is the always-on surface: a deterministic **receiver** (no LLM) enqueues
messages and acks; Claude Code replies with the **sender**. The CLI is the brain's
own surface.
"""

from agent.channels.telegram import TelegramClient, TelegramReceiver, notify, send

__all__ = ["TelegramClient", "TelegramReceiver", "send", "notify"]
