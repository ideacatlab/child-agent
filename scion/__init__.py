"""scion — a self-improving generalist agent harness driven by Claude Code.

scion has **no LLM API dependency and costs nothing per token**. The "brain" is a
long-lived **Claude Code** session (your subscription), kept looping 24/7 by the
``/loop`` skill and a *master prompt*. scion is the durable infrastructure that
session drives: a task queue, Telegram, retrieval over your documents, persistent
memory + knowledge, a tool/skill workshop, and git self-publish — all exposed as a
plain ``scion`` CLI and all running on the Python standard library.

This is the ali-fleet-recovery "sentinel" model, generalized: deterministic shell
+ Python automation feeds a durable queue; Claude Code drains it, does open-ended
work with its native tools plus the ``scion`` CLI, replies on Telegram, writes
itself new tools/skills/knowledge, and publishes the improvements back to git.

    always-on shell layer (no LLM):  Telegram receiver + cron ticker -> queue
    brain layer (your subscription): Claude Code  /loop  +  MASTER_PROMPT.md
                                        |  drains the queue, acts, replies,
                                        |  builds tools/knowledge, publishes
                                        v
              scion CLI: task · tg · rag · memory · know · skill · tool · publish
"""

__version__ = "0.2.0"

__all__ = ["__version__"]
