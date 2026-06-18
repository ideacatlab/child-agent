"""The always-on deterministic layer ("the daemon").

No LLM. A Telegram **receiver** enqueues messages and a **cron** scheduler drops
timed work onto the same durable queue. Run it under a supervisor; Claude Code
(the brain) drains the queue separately via ``/loop`` + the master prompt.
"""

from agent.scheduler.cron import CronScheduler, get_scheduler
from agent.scheduler.daemon import run_daemon

__all__ = ["CronScheduler", "get_scheduler", "run_daemon"]
