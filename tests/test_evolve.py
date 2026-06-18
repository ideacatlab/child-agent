import subprocess

import pytest

import agent.evolve.evolve as E


class _FakeSettings:
    """Minimal settings so evolve operates on a throwaway repo, never the real one."""

    def __init__(self, root):
        self.root = root
        self.git_author = "Test Agent <test@localhost>"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()

    def git(*args):
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)

    git("init", "-q")
    git("config", "user.email", "setup@localhost")
    git("config", "user.name", "Setup")
    (root / "core.py").write_text("x = 1\n")
    git("add", "-A")
    git("commit", "-qm", "initial")
    monkeypatch.setattr(E, "get_settings", lambda: _FakeSettings(root))
    return root


def test_checkpoint_clean_is_noop(repo):
    msg = E.checkpoint("nothing changed")
    assert "nothing to checkpoint" in msg


def test_checkpoint_diff_revert_cycle(repo):
    # make a change, see the diff
    (repo / "core.py").write_text("x = 2\n")
    assert "x = 2" in E.diff()

    # checkpoint it
    msg = E.checkpoint("bump x")
    assert msg.startswith("checkpoint ")
    assert "bump x" in E.log()
    assert E.diff() == "(no changes since last checkpoint)"

    # change again, then revert back to the checkpoint
    (repo / "core.py").write_text("x = 999\n")
    assert "x = 999" in E.diff()
    out = E.revert()
    assert "reverted to" in out
    assert (repo / "core.py").read_text() == "x = 2\n"  # restored to the checkpoint


def test_log_lists_history(repo):
    (repo / "core.py").write_text("x = 3\n")
    E.checkpoint("third")
    log = E.log(limit=10)
    assert "third" in log and "initial" in log
