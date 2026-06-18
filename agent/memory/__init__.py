"""Persistent memory.

Two complementary layers, both human-readable and git-diffable (OpenClaw's
file-first state + Letta's self-editing blocks):

* **Files** — ``IDENTITY.md`` (identity), ``USER.md`` (operator profile),
  ``MEMORY.md`` (durable facts), and append-only daily journals.
* **Blocks** — topic-scoped *core memory* the agent edits with tools and that is
  rendered into the system prompt every turn under a character budget.
"""

from agent.memory.blocks import BlockStore, MemoryBlock
from agent.memory.store import MemoryStore, get_memory

__all__ = ["BlockStore", "MemoryBlock", "MemoryStore", "get_memory"]
