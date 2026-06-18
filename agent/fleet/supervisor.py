"""The supervisor — the always-on improver of the whole fleet.

A supervision cycle reaps finished runs, builds a performance digest, and hands it
to a spawned ``supervisor`` worker whose job is to make the fleet better: rewrite
underperforming agents' charters, fix or add their tools/skills, and — since nothing
here is fixed — rewrite the core itself when that is what's holding an agent back.

Run it on demand (``agent fleet supervise``) or let the daemon fire it on an
interval (``AGENT_SUPERVISE_EVERY``).
"""

from __future__ import annotations

from agent.config import Settings, get_settings
from agent.fleet.metrics import RunRecord, get_metrics
from agent.fleet.registry import get_registry
from agent.fleet.runner import reap, run_worker
from agent.logging import get_logger

log = get_logger("fleet.supervisor")

_SUPERVISION_TASK = """\
Run one supervision cycle over the agent fleet. Here is the current performance digest:

{digest}

For each agent role, judge whether it is performing well. For any underperformer — low
success rate, repeated failures, slow runs, or weak results — improve it:

- rewrite its charter at `agents/<role>/AGENT.md`,
- fix or add the tools (`authored_tools/`) and skills (`skills/`) it relies on,
- and, since nothing here is fixed, fix the **core** (`agent/`, the CLI, even this
  supervision logic) when that is what's limiting an agent.

You may rewrite ANY file. Checkpoint first with `agent evolve checkpoint "<label>"` so a
bad change can be reverted, keep changes surgical and verified (`pytest -q`, `ruff check`),
and `agent publish commit "<what and why>"` when the improvement is worth keeping. Report
exactly what you changed and why.
"""


def supervise_once(settings: Settings | None = None) -> RunRecord | None:
    """Reap finished runs, build the digest, and spawn the supervisor to improve the fleet."""
    s = settings or get_settings()
    reap(s)
    if get_registry(fresh=True).get("supervisor") is None:
        log.warning("no 'supervisor' role (agents/supervisor/AGENT.md); skipping supervision")
        return None
    digest = get_metrics().digest()
    log.info("starting supervision cycle")
    return run_worker("supervisor", _SUPERVISION_TASK.format(digest=digest), settings=s)
