"""The background daemon — the always-on deterministic layer (no LLM, never blocks).

Keep this running as a service (systemd / nohup). It does three things, each in a
restart-on-crash loop:

- **Telegram receiver** — long-polls for messages and drops them on the queue.
- **cron ticker** — fires scheduled jobs onto the queue.
- **supervision trigger** *(optional)* — every ``AGENT_SUPERVISE_EVERY`` it runs one
  supervision cycle so the fleet keeps improving even with no human session open.

The daemon itself contains no intelligence; the orchestrator/workers drain what it
enqueues, and the supervision cycle shells out to a ``claude`` worker.
"""

from __future__ import annotations

import threading
import time

from agent.config import get_settings
from agent.logging import get_logger
from agent.scheduler.cron import get_scheduler, parse_interval

log = get_logger("scheduler.daemon")


def _keep_alive(name: str, fn) -> None:
    """Run *fn* forever, restarting with capped backoff if it returns or crashes."""
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
    return threading.Thread(target=_keep_alive, args=(name, fn), name=name, daemon=True)


def _supervision_loop(every_seconds: int) -> None:
    """Run a supervision cycle on a fixed interval (the always-on supervisor)."""
    from agent.fleet.supervisor import supervise_once

    log.info("supervision loop started (every %ds)", every_seconds)
    while True:
        time.sleep(every_seconds)
        try:
            supervise_once()
        except Exception:
            log.exception("supervision cycle failed")


def run_daemon(*, telegram: bool = True, cron: bool = True, supervise: bool = True) -> None:
    """Run the always-on deterministic layer. Blocks (Ctrl-C to stop)."""
    s = get_settings()
    have_tg = telegram and bool(s.telegram_bot_token)

    background: list[threading.Thread] = []
    if cron:
        background.append(_thread("cron", lambda: get_scheduler().run()))
    if supervise and s.supervise_every:
        try:
            every = parse_interval(s.supervise_every)
            background.append(_thread("supervision", lambda: _supervision_loop(every)))
        except Exception:
            log.warning("invalid AGENT_SUPERVISE_EVERY=%r; supervision disabled", s.supervise_every)
    for t in background:
        t.start()

    try:
        if have_tg:
            from agent.channels.telegram import TelegramReceiver

            _keep_alive("telegram-receiver", lambda: TelegramReceiver(s).run())
        elif background:
            # the foreground has nothing to do; keep alive while threads work
            while True:
                time.sleep(3600)
        else:
            log.warning("daemon started with nothing to do (no telegram, no cron, no supervision)")
    except KeyboardInterrupt:
        log.info("daemon shutting down")
