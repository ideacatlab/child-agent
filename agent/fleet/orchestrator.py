"""Deterministic dispatch glue the orchestrator brain calls.

The *intelligent* part — deciding how to decompose a task and which roles to use —
stays with the brain (the looping Claude Code session). This module only does the
mechanical part: spawn one worker, or fan a list of jobs out across the fleet with a
concurrency cap, and hand back the run records.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from agent.config import Settings, get_settings
from agent.fleet.metrics import RunRecord
from agent.fleet.runner import run_worker


def dispatch(
    role: str, task: str, *, task_id: int | None = None,
    settings: Settings | None = None, model: str | None = None,
) -> RunRecord:
    """Spawn one worker (blocking) and return its run record."""
    return run_worker(role, task, task_id=task_id, settings=settings, model=model)


def _normalize(job) -> dict:
    if isinstance(job, dict):
        return job
    role, task = job  # (role, task) tuple
    return {"role": role, "task": task}


def run_parallel(jobs, *, settings: Settings | None = None) -> list[RunRecord]:
    """Run many jobs across the fleet concurrently (capped), preserving input order.

    Each job is ``(role, task)`` or ``{"role", "task", "task_id"?, "model"?}``. A job
    that raises is captured; its slot holds an ``error`` run record, never an
    exception, so one bad worker never sinks the batch.
    """
    s = settings or get_settings()
    norm = [_normalize(j) for j in jobs]
    if not norm:
        return []
    cap = max(1, s.fleet_max_concurrency)

    def _one(j: dict) -> RunRecord:
        return run_worker(
            j["role"], j["task"], task_id=j.get("task_id"), settings=s, model=j.get("model")
        )

    with ThreadPoolExecutor(max_workers=cap) as pool:
        return list(pool.map(_one, norm))
