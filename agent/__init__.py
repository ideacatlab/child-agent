"""A self-improving, self-rewriting multi-agent runtime driven by Claude Code.

There is **no LLM API and no per-token cost**. The brain — and every worker and the
supervisor — is a ``claude`` process on your subscription. This package is the
durable infrastructure those processes drive:

- an **orchestrator** (a long-lived Claude Code ``/loop`` session) that drains a
  durable queue and, for big work, decomposes and dispatches to a **fleet** of
  spawned ``claude`` worker agents (``agent fleet run/spawn``);
- an always-on **supervisor** that watches per-agent performance and rewrites the
  underperformers — their charters, tools, skills, and the core itself;
- **unrestricted self-rewrite**: the runtime owns and may rewrite every file,
  including this package and its own CLI. ``agent evolve`` makes that recoverable.

Nothing here is meant to stay stable. The base template is name-agnostic; a
deployment is given an identity via ``AGENT_NAME``.

    always-on daemon (no LLM):   Telegram receiver + cron + supervision trigger -> queue
    orchestrator (subscription): Claude Code  /loop  +  MASTER_PROMPT.md
        -> drains the queue, dispatches workers, writes/improves agents, self-rewrites
    agent CLI: task · fleet · evolve · tg · rag · memory · know · skill · tool · publish
"""

__version__ = "0.3.0"

__all__ = ["__version__"]
