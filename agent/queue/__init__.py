"""Durable task queue (SQLite).

The backbone of unattended autonomy: every request — a Telegram message, a cron
firing, a proactive idea — becomes a persisted row, so nothing is lost across
crashes or restarts. A worker drains it by running the agent loop on each task.

Generalized from ali-fleet-recovery's ``reqqueue.py``: idempotent insert keyed on
``(source, external_id)``, a ``pending -> working -> done|skipped|obsolete``
lifecycle, and a conservative GC that closes noise but never deletes real asks.
"""

from agent.queue.task_queue import Task, TaskQueue, get_queue

__all__ = ["Task", "TaskQueue", "get_queue"]
