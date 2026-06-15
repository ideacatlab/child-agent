"""Channels — the surfaces the agent talks on.

A :class:`~scion.channels.base.Channel` is anything that can deliver a message
and (optionally) ask the operator to confirm a risky action. The CLI channel
backs interactive ``scion chat``; the Telegram channel backs the always-on bot.
"""

from scion.channels.base import Channel, CLIChannel

__all__ = ["Channel", "CLIChannel"]
