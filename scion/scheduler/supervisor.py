"""Supervisor for the sentinel: Telegram receiver + cron ticker, restart-on-crash.

This is the deterministic, always-on layer — the part you keep running as a daemon
(systemd / nohup). It contains no LLM and never blocks on the brain. Claude Code
drains what it enqueues.
"""

from __future__ import annotations

import threading
import time

from scion.config import get_settings
from scion.logging import get_logger
from scion.scheduler.cron import get_scheduler

log = get_logger("scheduler.supervisor")


def _supervise(name: str, fn) -> None:
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
    return threading.Thread(target=_supervise, args=(name, fn), name=name, daemon=True)


def run_sentinel(*, telegram: bool = True, cron: bool = True) -> None:
    """Run the always-on deterministic layer. Blocks (Ctrl-C to stop)."""
    s = get_settings()
    have_tg = telegram and bool(s.telegram_bot_token)

    background: list[threading.Thread] = []
    if cron:
        background.append(_thread("cron", lambda: get_scheduler().run()))
    for t in background:
        t.start()

    try:
        if have_tg:
            from scion.channels.telegram import TelegramReceiver

            _supervise("telegram-receiver", lambda: TelegramReceiver(s).run())
        elif cron:
            # nothing to keep the foreground busy besides cron (already threaded)
            while True:
                time.sleep(3600)
        else:
            log.warning("sentinel started with nothing to do (no telegram, no cron)")
    except KeyboardInterrupt:
        log.info("sentinel shutting down")
