"""The queue worker: claim a task, run the agent on it, reply, mark done."""

from __future__ import annotations

import time

from scion.config import Settings, get_settings
from scion.logging import get_logger
from scion.queue.task_queue import Task, TaskQueue, get_queue

log = get_logger("scheduler.worker")


class Worker:
    def __init__(self, settings: Settings | None = None, queue: TaskQueue | None = None, agent_loop=None) -> None:
        self.s = settings or get_settings()
        self.queue = queue or get_queue()
        self._loop = agent_loop

    def _agent(self):
        if self._loop is None:
            from scion.agent.loop import AgentLoop

            self._loop = AgentLoop(self.s)
        return self._loop

    # ------------------------------------------------------------------ #
    def run(self, *, poll: float = 2.0, once: bool = False) -> None:
        log.info("worker started (autonomous=%s)", self.s.autonomous)
        last_maintenance = 0.0
        while True:
            if time.time() - last_maintenance > 60:
                self.queue.requeue_stuck()
                last_maintenance = time.time()
            task = self.queue.claim_next()
            if task is None:
                if once:
                    return
                time.sleep(poll)
                continue
            self.process(task)
            if once:
                return

    def process(self, task: Task) -> None:
        log.info("task #%s [%s]: %s", task.id, task.kind, task.text[:80])
        channel = self._channel_for(task)
        try:
            from scion.agent.session import Session

            result = self._agent().run(
                task.text,
                session=Session.new("task"),
                channel=channel,
                autonomous=True,
                task_id=task.id,
            )
            self.queue.complete(task.id, result[:8000])
            if channel is not None and result.strip():
                channel.send(result)
        except Exception as exc:  # noqa: BLE001
            log.exception("task #%s failed", task.id)
            self.queue.fail(task.id, str(exc))
            if channel is not None:
                channel.send(f"⚠️ task #{task.id} failed: {exc}")

    def _channel_for(self, task: Task):
        chat_id = task.origin.get("chat_id") or (
            self.s.telegram_chat_id if self.s.telegram_bot_token else None
        )
        if self.s.telegram_bot_token and chat_id:
            from scion.channels.telegram import TelegramChannel, TelegramClient

            return TelegramChannel(TelegramClient(self.s.telegram_bot_token), chat_id)
        return None
