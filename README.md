# scion 🌱

**A self-improving generalist agent, driven by your Claude Code subscription — not the API.**

scion is the durable infrastructure around a long-lived **Claude Code** session.
You start that session once with a master prompt and the `/loop` skill; it then
runs 24/7, draining a work queue, doing open-ended tasks with its native tools
plus the `scion` CLI, replying to you on Telegram, and **building itself new
tools, skills, knowledge, and memory** as it goes. Fork it and grow a specialist
(a marketer, an SRE, a researcher) that gets better from real use.

> **No API. No per-token cost.** The "brain" is the Claude Code session you're
> already paying a flat subscription for. This is deliberate: harnesses that call
> the Anthropic API (like OpenClaw) can get very expensive very fast. scion has
> **zero LLM dependency** — the entire thing runs on the Python standard library.

> *scion* (n.): a descendant of a notable line — and a living shoot cut for
> grafting, so a new plant grows from an established root. A child of Claude that
> grows new capabilities onto a stable core.

This is the ali-fleet-recovery **"sentinel"** model — a real agent that's been
running this way for a while — generalized into a template anyone can fork.

---

## How it works

```
  ┌── always-on, no LLM (the "sentinel", a daemon) ──┐
  │  Telegram receiver  ──┐                            │
  │  cron scheduler     ──┴──►  durable queue (SQLite) │
  └──────────────────────────────────┬────────────────┘
                                      │  (messages, scheduled work — nothing is lost)
                                      ▼
  ┌── the brain: ONE Claude Code session, looping 24/7 ──────────────┐
  │  /loop  +  MASTER_PROMPT.md                                       │
  │     every cycle:  `scion autopilot`  → claim & print next task    │
  │                   do it (native tools + scion CLI) → reply → done │
  │                   build tools/skills/knowledge → `scion publish`  │
  └──────────────────────────────────────────────────────────────────┘
```

- The **sentinel** is deterministic shell/Python that never blocks on the model —
  it just fills the queue and acks "queued, working on it."
- The **brain** is your Claude Code session. `/loop` re-invokes the master prompt
  on a cadence; each cycle it calls `scion autopilot`, which hands it the next
  task. It uses its *own* read/write/bash/web tools **plus** the `scion` CLI for
  the durable bits (queue, Telegram, retrieval, memory, knowledge, publish).

---

## Quickstart

```bash
# 1. install — no API key, no LLM SDK; core needs nothing
python -m venv .venv && source .venv/bin/activate
pip install -e ".[recommended]"          # extras = PDF ingest, web, faster vectors

# 2. (optional) configure Telegram + git in .env
cp .env.example .env && $EDITOR .env      # there is NO API key to set

# 3. sanity check
scion doctor

# 4. start the always-on sentinel (Telegram receiver + cron). Leave it running.
scion sentinel                            # or: scripts/run-sentinel.sh under systemd

# 5. start the brain: open Claude Code in this repo and run
#       /loop scion autopilot
#    (it follows MASTER_PROMPT.md and drains the queue forever)
```

Now feed it work from anywhere:

```bash
scion task add "draft a launch tweet for our v2 release"   # the loop picks it up
# ...or just message the Telegram bot. The reply comes back in Telegram.
```

Give it documents to reason over (great for the "be my marketer" case):

```bash
scion rag ingest ./client_docs --collection acme
# then in a task: "Using the acme knowledge base, find their refund window."
```

---

## What scion gives you (and what Claude Code already has)

**Claude Code already provides** the brain, reading/writing files, running bash,
web access, spawning subagents, and its own permission/sandbox model. scion does
**not** re-implement any of that. scion adds the durable, agent-specific
infrastructure a 24/7 self-improving agent needs, all as one CLI:

| `scion …` | what it is |
|---|---|
| `autopilot` | claim + print the next task — the `/loop` entrypoint |
| `task add/next/done/fail/list/gc` | the durable work queue |
| `tg send <chat> "…"` / `sentinel` | reply on Telegram / run the receiver+cron daemon |
| `rag ingest/search/stats` | retrieval over your documents (PDF/MD/HTML/…), zero-dep hybrid search |
| `memory remember/search/journal/user` | persistent markdown memory + recall |
| `know note/list` | a self-rendering knowledge registry (committed) |
| `skill list/show` | on-demand playbooks (`SKILL.md`) |
| `tool new/validate/approve/list` | the tool workshop — scaffold, screen, promote a new tool script |
| `publish commit/status` | commit + push the agent's growth (secret-guarded) |
| `cron list/add-interval/add-daily` | scheduled work that lands on the queue |

---

## The self-improvement loop

When the agent repeatedly needs a capability it doesn't have, it **writes itself a
tool**: `scion tool new <name>` scaffolds a script, the agent implements it,
`scion tool validate` screens it (syntax + structure + a `--help` smoke run), and
`scion tool approve` promotes it into the version-controlled `authored_tools/`
folder. When it works out a repeatable procedure, it writes a **skill**
(`skills/<name>/SKILL.md`). Durable facts go to **memory**, findings to the
**knowledge registry**. Then `scion publish commit "…"` ships all of it back to
git. Capability compounds, and it's all reviewable and reversible.

---

## Make it a specialist (the fork story)

This repo is a **template** ("Use this template" on GitHub):

1. Edit `workspace/SOUL.md` (who the agent is) and add domain **skills** under
   `skills/` (an example, `competitor-research`, ships with it).
2. Seed knowledge: `scion rag ingest ./domain_docs`.
3. Run the sentinel + a Claude Code `/loop`, point your users at the Telegram bot,
   and let it author tools, write skills, and record knowledge as it learns — then
   publish so the improvements persist in *its* repo.

---

## Safety

- **Nothing to leak:** there's no API key in the loop. Secrets are masked out of
  anything logged, and `scion publish` **hard-aborts if a secret got staged**.
- **The operator stays in control:** `SCION_CONFIRM_DANGEROUS=1` tells the agent
  (via the master prompt) to ask before destructive or outward-facing actions
  (git push, sending things). Claude Code's own permission prompts apply to
  bash/file actions on top of that.
- **The tool gate:** a tool script is screened and smoke-tested before
  `scion tool approve` will promote it.

---

## Project layout

```
MASTER_PROMPT.md   the brain: what you give to `/loop` (the agent can edit it)
scion/             the package (pure stdlib)
  cli.py           the `scion` command (the brain's infrastructure surface)
  queue/           durable SQLite task queue
  channels/        Telegram receiver + sender (urllib, zero-dep)
  scheduler/       cron + the sentinel supervisor
  rag/             loaders → chunkers → embeddings → store → hybrid retrieve
  memory/          markdown files + Letta-style core-memory blocks
  tools/           the tool workshop (scaffold/validate/promote scripts)
  publish/         git self-publish (secret-guarded)
  knowledge.py     the self-rendering knowledge registry
authored_tools/    tools the agent wrote (committed)
knowledge/         the knowledge registry (committed)
skills/            SKILL.md playbooks (committed)
workspace/         private runtime state (gitignored): dbs, memory, logs
```

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the design rationale and the full
"what was inherited from where" matrix, and [`docs/`](docs/) for the how-to guides.

MIT licensed. Built to be forked.
