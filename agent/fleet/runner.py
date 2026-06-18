"""Spawn headless ``claude`` worker processes — the substrate of the fleet.

A worker is a non-interactive ``claude -p`` invocation booted with a role charter as
its appended system prompt. It runs in the repo on your subscription (no API), does
the task with its own native tools plus the ``agent`` CLI, and prints a JSON result
we parse and record. Two entry points:

- :func:`run_worker`   — blocking: spawn, wait, fully record the run. The main path.
- :func:`spawn_worker` — detached: fire-and-forget, recorded as ``running``; finalize
  later with :func:`reap`.

The ``claude`` binary is configurable (``AGENT_CLAUDE_BIN``) so tests inject a fake.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from agent.config import Settings, get_settings
from agent.fleet.metrics import RunRecord, get_metrics
from agent.fleet.registry import AgentRole, get_registry
from agent.logging import get_logger

log = get_logger("fleet.runner")


# --------------------------------------------------------------------------- #
# building the claude invocation
# --------------------------------------------------------------------------- #
def build_argv(role: AgentRole, task: str, s: Settings, model: str | None) -> list[str]:
    """Construct the ``claude -p`` argv for a worker booted as *role*."""
    argv = [
        s.claude_bin, "-p", task,
        "--output-format", "json",
        "--permission-mode", role.permission_mode or s.fleet_permission_mode,
        "--add-dir", str(s.root),
    ]
    if model:
        argv += ["--model", model]
    body = role.body()
    if body:
        argv += ["--append-system-prompt", body]
    if role.tools:
        argv += ["--allowedTools", ",".join(role.tools)]
    return argv


def _parse_result(out: str) -> tuple[str, bool]:
    """Extract ``(summary, is_error)`` from a worker's ``--output-format json`` stdout."""
    out = (out or "").strip()
    try:
        data = json.loads(out)
        if isinstance(data, dict):
            summary = str(data.get("result") or data.get("error") or "").strip()
            return (summary or "(no result)")[:1000], bool(data.get("is_error"))
    except (ValueError, TypeError):
        pass
    return (out[:1000] or "(no output)"), False


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just not ours
    return True


def _worktree(s: Settings, tag: str) -> Path | None:
    """Create an isolated git worktree for a file-mutating worker (best effort)."""
    from agent.tools.sandbox import run_command

    wt = s.workspace / "worktrees" / tag
    rc, msg = run_command(f"git worktree add -b fleet/{tag} '{wt}'", cwd=s.root, timeout=60)
    if rc != 0:
        log.warning("worktree add failed (%s); running in the main tree", msg.strip()[:160])
        return None
    return wt


# --------------------------------------------------------------------------- #
# blocking run — the main path
# --------------------------------------------------------------------------- #
def run_worker(
    role_name: str, task: str, *, task_id: int | None = None,
    settings: Settings | None = None, model: str | None = None,
) -> RunRecord:
    """Spawn a worker, wait for it, record the result, and return the run record."""
    s = settings or get_settings()
    m = get_metrics()
    role = get_registry(fresh=True).get(role_name)
    if role is None:
        rid = m.start_run(role_name, task, task_id=task_id)
        m.finish_run(rid, status="error", summary=f"unknown role: {role_name}", duration_ms=0)
        return m.get(rid)

    model_final = model or role.model or s.worker_model
    s.runs_dir.mkdir(parents=True, exist_ok=True)
    log_path = s.runs_dir / f"run-{time.time_ns()}.out"
    rid = m.start_run(role_name, task, model=model_final, task_id=task_id, log_path=str(log_path))

    cwd = str(s.root)
    if s.fleet_worktree:
        wt = _worktree(s, f"run-{rid}")
        if wt is not None:
            cwd = str(wt)

    argv = build_argv(role, task, s, model_final)
    started = time.monotonic()
    try:
        proc = subprocess.run(
            argv, cwd=cwd, capture_output=True, text=True, timeout=s.fleet_timeout
        )
    except subprocess.TimeoutExpired:
        dur = int((time.monotonic() - started) * 1000)
        m.finish_run(rid, status="timeout", summary=f"timed out after {s.fleet_timeout}s", duration_ms=dur)
        return m.get(rid)
    except FileNotFoundError:
        m.finish_run(rid, status="error", summary=f"claude binary not found: {s.claude_bin}", duration_ms=0)
        return m.get(rid)

    out = proc.stdout or ""
    log_path.write_text(out + (f"\n[stderr]\n{proc.stderr}" if proc.stderr else ""), encoding="utf-8")
    summary, is_error = _parse_result(out)
    status = "ok" if (proc.returncode == 0 and not is_error) else "error"
    dur = int((time.monotonic() - started) * 1000)
    m.finish_run(rid, status=status, exit_code=proc.returncode, summary=summary, duration_ms=dur)
    return m.get(rid)


# --------------------------------------------------------------------------- #
# detached spawn — fire-and-forget, finalized by reap()
# --------------------------------------------------------------------------- #
def spawn_worker(
    role_name: str, task: str, *, task_id: int | None = None,
    settings: Settings | None = None, model: str | None = None,
) -> RunRecord:
    """Launch a worker in the background; return immediately with a ``running`` record."""
    s = settings or get_settings()
    m = get_metrics()
    role = get_registry(fresh=True).get(role_name)
    if role is None:
        rid = m.start_run(role_name, task, task_id=task_id)
        m.finish_run(rid, status="error", summary=f"unknown role: {role_name}", duration_ms=0)
        return m.get(rid)

    model_final = model or role.model or s.worker_model
    s.runs_dir.mkdir(parents=True, exist_ok=True)
    log_path = s.runs_dir / f"run-{time.time_ns()}.out"
    argv = build_argv(role, task, s, model_final)
    try:
        fh = open(log_path, "w", encoding="utf-8")
        proc = subprocess.Popen(
            argv, cwd=str(s.root), stdout=fh, stderr=subprocess.STDOUT, start_new_session=True
        )
    except FileNotFoundError:
        rid = m.start_run(role_name, task, model=model_final, task_id=task_id)
        m.finish_run(rid, status="error", summary=f"claude binary not found: {s.claude_bin}", duration_ms=0)
        return m.get(rid)

    rid = m.start_run(
        role_name, task, model=model_final, task_id=task_id, pid=proc.pid, log_path=str(log_path)
    )
    log.info("spawned %s worker (run #%d, pid %d)", role_name, rid, proc.pid)
    return m.get(rid)


def _finished(pid: int) -> bool:
    """True if the worker process has exited.

    Tries ``waitpid`` first so a child of *this* process is reaped (not left a zombie
    that ``kill(pid, 0)`` would still report alive); falls back to a liveness probe when
    the run was spawned by a different process (the normal CLI case)."""
    try:
        wpid, _ = os.waitpid(pid, os.WNOHANG)
        return wpid != 0
    except ChildProcessError:
        return not _pid_alive(pid)  # not our child — just probe liveness
    except OSError:
        return not _pid_alive(pid)


def reap(settings: Settings | None = None) -> int:
    """Finalize detached runs whose process has exited. Returns how many were reaped."""
    m = get_metrics()
    reaped = 0
    for r in m.running():
        if r.pid is None or not _finished(r.pid):
            continue
        summary, is_error = "(process exited; no output captured)", True
        if r.log_path and Path(r.log_path).exists():
            summary, is_error = _parse_result(
                Path(r.log_path).read_text(encoding="utf-8", errors="replace")
            )
        dur = max(0, int(time.time()) - r.started_at) * 1000
        m.finish_run(r.id, status="error" if is_error else "ok", summary=summary, duration_ms=dur)
        reaped += 1
    return reaped
