import os
from pathlib import Path

import pytest

import agent.fleet.metrics as M
import agent.fleet.registry as R
from agent.config import get_settings, reload_settings
from agent.fleet import get_metrics, get_registry, run_parallel, run_worker
from agent.fleet.registry import AgentRegistry
from agent.fleet.runner import build_argv

FAKE = Path(__file__).parent / "fake_claude.sh"


@pytest.fixture
def fleet(tmp_path, monkeypatch):
    """Isolated fleet: temp workspace + the fake `claude` binary; singletons reset."""
    os.chmod(FAKE, 0o755)
    monkeypatch.setenv("AGENT_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("AGENT_CLAUDE_BIN", str(FAKE))
    M._METRICS = None
    R._REGISTRY = None
    s = reload_settings()
    yield s
    M._METRICS = None
    R._REGISTRY = None
    get_settings.cache_clear()


# ---- registry ------------------------------------------------------------- #
def test_registry_loads_committed_roles(fleet):
    reg = get_registry(fresh=True)
    assert "worker" in reg.names()
    assert "supervisor" in reg.names()
    assert reg.get("worker").body()  # charter body is non-empty


def test_registry_scaffold_new_role(tmp_path):
    reg = AgentRegistry(dirs=[tmp_path / "agents"])
    path = reg.scaffold("researcher", "Deep web research.")
    assert path.exists()
    assert reg.get("researcher") is not None
    assert "researcher" in reg.get("researcher").body()


# ---- runner argv ---------------------------------------------------------- #
def test_build_argv_shape(fleet):
    role = get_registry(fresh=True).get("worker")
    argv = build_argv(role, "do the thing", fleet, model="claude-x")
    assert argv[0] == str(FAKE)
    assert "-p" in argv and "do the thing" in argv
    assert "--output-format" in argv and "json" in argv
    assert "--permission-mode" in argv
    assert "--append-system-prompt" in argv
    assert argv[argv.index("--model") + 1] == "claude-x"


# ---- run + record --------------------------------------------------------- #
def test_run_worker_records_ok(fleet):
    r = run_worker("worker", "say hi")
    assert r.status == "ok"
    assert r.exit_code == 0
    assert "say hi" in r.summary  # fake echoes the task back
    recent = get_metrics().recent()
    assert len(recent) == 1 and recent[0].role == "worker"
    assert "worker" in get_metrics().digest()


def test_run_worker_error_path(fleet, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_FAIL", "1")
    r = run_worker("worker", "will fail")
    assert r.status == "error"
    assert r.exit_code == 1


def test_unknown_role_is_error(fleet):
    r = run_worker("does-not-exist", "x")
    assert r.status == "error"
    assert "unknown role" in r.summary


# ---- parallel + aggregate ------------------------------------------------- #
def test_run_parallel_preserves_order(fleet):
    results = run_parallel([("worker", "a"), ("worker", "b"), ("worker", "c")])
    assert [r.status for r in results] == ["ok", "ok", "ok"]
    assert "a" in results[0].summary and "c" in results[2].summary


def test_metrics_aggregate(fleet):
    run_worker("worker", "one")
    run_worker("worker", "two")
    agg = get_metrics().aggregate("worker")
    assert agg and agg[0]["role"] == "worker"
    assert agg[0]["total"] == 2
    assert agg[0]["success_rate"] == 1.0


def test_spawn_and_reap(fleet):
    import time

    from agent.fleet import reap, spawn_worker

    r = spawn_worker("worker", "background task")
    assert r.status == "running" and r.pid
    # the fake exits ~instantly; wait briefly, then finalize
    deadline = time.time() + 5
    while time.time() < deadline and reap() == 0:
        time.sleep(0.05)
    fr = get_metrics().get(r.id)
    assert fr.status == "ok"
    assert "background task" in fr.summary
