import scion.scheduler.cron as cron
from scion.queue.task_queue import TaskQueue
from scion.scheduler.cron import CronScheduler, parse_interval


def test_parse_interval():
    assert parse_interval("30s") == 30
    assert parse_interval("15m") == 900
    assert parse_interval("2h") == 7200
    assert parse_interval("1d") == 86400
    assert parse_interval("45") == 45


def test_cron_fires_due_job(tmp_path, monkeypatch):
    q = TaskQueue(tmp_path / "q.db")
    monkeypatch.setattr(cron, "get_queue", lambda: q)
    sched = CronScheduler(tmp_path / "sched.db")
    sched.add_interval("ping", "1h", "run the hourly check")
    # force the job due
    with sched._conn() as c:
        c.execute("UPDATE jobs SET next_run=0 WHERE name='ping'")
    fired = sched.tick()
    assert fired == 1
    pending = q.pending()
    assert pending and pending[0].kind == "cron"
    assert "hourly check" in pending[0].text
    # it rescheduled into the future (won't fire again immediately)
    assert sched.tick() == 0
