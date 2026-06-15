"""Autonomy: a worker that drains the task queue, a cron scheduler, and a
supervisor that runs them (plus the Telegram bot) with restart-on-crash.

This is the piece ali-fleet-recovery deliberately left to a human launching
Claude Code out-of-band — here it's built in, so the agent runs hands-off.
"""

from scion.scheduler.cron import CronScheduler, get_scheduler
from scion.scheduler.worker import Worker

__all__ = ["CronScheduler", "get_scheduler", "Worker"]
