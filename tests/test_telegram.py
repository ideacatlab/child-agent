import agent.queue.task_queue as tq
from agent.channels.telegram import TelegramReceiver
from agent.queue.task_queue import TaskQueue


class _StubClient:
    def __init__(self):
        self.sent = []

    def send_message(self, text, chat_id, **kw):
        self.sent.append((chat_id, text))
        return {"ok": True}


def test_receiver_enqueues_and_acks(settings, monkeypatch, tmp_path):
    q = TaskQueue(tmp_path / "q.db")
    monkeypatch.setattr(tq, "_QUEUE", q)

    settings.telegram_bot_token = "dummy"
    settings.telegram_chat_id = "42"  # set so we don't write .env during the test
    r = TelegramReceiver(settings)
    r.client = _StubClient()

    r._handle({
        "chat": {"id": 42},
        "from": {"id": 7, "username": "bob"},
        "text": "draft a launch tweet",
        "message_id": 5,
    })

    pending = q.pending()
    assert pending and pending[0].text == "draft a launch tweet"
    assert pending[0].source == "telegram"
    assert pending[0].origin["chat_id"] == 42
    assert r.client.sent and "Queued" in r.client.sent[0][1]


def test_receiver_blocks_unauthorized(settings, monkeypatch, tmp_path):
    q = TaskQueue(tmp_path / "q.db")
    monkeypatch.setattr(tq, "_QUEUE", q)
    settings.telegram_bot_token = "dummy"
    settings.telegram_chat_id = "42"
    settings.telegram_allowed_user_ids = [999]  # bob (7) is not allowed
    r = TelegramReceiver(settings)
    r.client = _StubClient()

    r._handle({"chat": {"id": 42}, "from": {"id": 7}, "text": "hi", "message_id": 1})
    assert not q.pending()
    assert "Not authorized" in r.client.sent[0][1]
