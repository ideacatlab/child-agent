from agent.queue.task_queue import TaskQueue


def test_enqueue_idempotent_and_claim(tmp_path):
    q = TaskQueue(tmp_path / "q.db")
    tid, is_new = q.add("do thing", source="telegram", external_id="chat:1")
    assert is_new
    tid2, is_new2 = q.add("do thing again", source="telegram", external_id="chat:1")
    assert not is_new2 and tid2 == tid  # idempotent on (source, external_id)

    task = q.claim_next()
    assert task is not None and task.status == "working" and task.id == tid
    assert q.claim_next() is None  # nothing else pending

    q.complete(task.id, "result")
    assert q.get(task.id).status == "done"
    assert q.counts().get("done") == 1


def test_priority_order(tmp_path):
    q = TaskQueue(tmp_path / "q.db")
    q.add("low", priority=0)
    q.add("high", priority=5)
    first = q.claim_next()
    assert first.text == "high"


def test_gc_obsoletes_empty(tmp_path):
    q = TaskQueue(tmp_path / "q.db")
    q.add("  ")  # trivially empty
    n = q.gc(max_age_hours=72)
    assert n == 1
    assert q.counts().get("obsolete") == 1
