"""The fleet — spawn, coordinate, measure, and improve worker/supervisor agents.

The orchestrator (the looping Claude Code session) decomposes work and dispatches
it to **worker agents**: headless ``claude`` processes, each booted with a role
charter from ``agents/<role>/AGENT.md``. Every run is recorded so an always-on
**supervisor** can see how each agent performs and rewrite the underperformers.

- :mod:`agent.fleet.registry`     — load agent-role charters (agents/<role>/AGENT.md)
- :mod:`agent.fleet.runner`       — spawn a ``claude`` worker, capture + record the run
- :mod:`agent.fleet.metrics`      — durable per-run / per-role performance store
- :mod:`agent.fleet.orchestrator` — deterministic dispatch (one / many in parallel)
- :mod:`agent.fleet.supervisor`   — one supervision cycle (evaluate + improve)
"""

from __future__ import annotations

from agent.fleet.metrics import FleetMetrics, RunRecord, get_metrics
from agent.fleet.orchestrator import dispatch, run_parallel
from agent.fleet.registry import AgentRegistry, AgentRole, get_registry
from agent.fleet.runner import reap, run_worker, spawn_worker
from agent.fleet.supervisor import supervise_once

__all__ = [
    "AgentRegistry",
    "AgentRole",
    "FleetMetrics",
    "RunRecord",
    "dispatch",
    "get_metrics",
    "get_registry",
    "reap",
    "run_parallel",
    "run_worker",
    "spawn_worker",
    "supervise_once",
]
