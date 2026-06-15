"""Supervisor: run worker + scheduler + Telegram bot with restart-on-crash."""

from __future__ import annotations

import threading
import time

from scion.config import get_settings
from scion.logging import get_logger
from scion.scheduler.cron import get_scheduler
from scion.scheduler.worker import Worker

log = get_logger("scheduler.supervisor")


def _supervise(name: str, fn) -> None:
    """Run *fn* forever, restarting on crash with capped backoff."""
    backoff = 2
    while True:
        try:
            log.info("starting %s", name)
            fn()
            log.warning("%s returned; restarting", name)
        except KeyboardInterrupt:
            raise
        except Exception:
            log.exception("%s crashed; restarting in %ss", name, backoff)
        time.sleep(backoff)
        backoff = min(backoff * 2, 60)


def _thread(name: str, fn) -> threading.Thread:
    t = threading.Thread(target=_supervise, args=(name, fn), name=name, daemon=True)
    return t


def serve(*, bot: bool = True, worker: bool = True, scheduler: bool = True) -> None:
    """Start the autonomy stack. Blocks (Ctrl-C to stop)."""
    s = get_settings()
    have_bot = bot and bool(s.telegram_bot_token)

    background: list[threading.Thread] = []
    if scheduler:
        background.append(_thread("scheduler", lambda: get_scheduler().run()))
    if worker and have_bot:
        # bot takes the foreground; worker runs behind it
        background.append(_thread("worker", lambda: Worker(s).run()))
    for t in background:
        t.start()

    try:
        if have_bot:
            from scion.channels.telegram import TelegramBot

            _supervise("telegram-bot", lambda: TelegramBot(s).run())
        elif worker:
            _supervise("worker", lambda: Worker(s).run())
        else:
            while True:
                time.sleep(3600)
    except KeyboardInterrupt:
        log.info("shutting down")
