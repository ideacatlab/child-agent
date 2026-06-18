"""Self-rewrite — git-backed recovery for an agent that owns its own code.

Nothing in this runtime is fixed: the agent may rewrite any file, including the CLI
and its own core. There are **no gates** on that — git history is the safety net.
This module just makes recovery easy:

- :func:`checkpoint` — commit the current state before a deep rewrite,
- :func:`diff`       — see what changed since the last checkpoint,
- :func:`revert`     — roll a bad rewrite back,
- :func:`log`        — the rewrite/checkpoint history.
"""

from __future__ import annotations

from agent.evolve.evolve import checkpoint, current_ref, diff, log, revert

__all__ = ["checkpoint", "current_ref", "diff", "log", "revert"]
