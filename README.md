# A self-rewriting, multi-agent runtime — driven by your Claude Code subscription

**Not the API.** The brain — and every worker and the supervisor — is a `claude`
process on your flat subscription. There is **no LLM API and no per-token cost**. The
entire core runs on the Python standard library.

This is the durable infrastructure around a long-lived **Claude Code** session. You
start that session once with a master prompt and the `/loop` skill; it then runs 24/7
as an **orchestrator**: draining a work queue, doing tasks with its native tools plus
the `agent` CLI, and — for larger work — **spawning a fleet of worker agents** it can
write and improve. An always-on **supervisor** watches how every agent performs and
rewrites the laggards. And nothing is fixed: the runtime **owns and rewrites its own
core**, not just the tools around it.

It is **name-agnostic**: fork it per cohort of users and give that deployment an
identity (`AGENT_NAME`). It takes full responsibility for performing the best it can
for the people it serves.

---

## How it works

```
  ┌── always-on daemon, no LLM ──────────────────────────────────┐
  │  Telegram receiver ─┐                                          │
  │  cron ticker ───────┼──►  durable queue (SQLite)              │
  │  supervision tick ──┘     (nothing is lost across restarts)   │
  └───────────────────────────────────┬──────────────────────────┘
                                       │
  ┌── ORCHESTRATOR: one Claude Code /loop session, 24/7 ──────────┐
  │  /loop  +  MASTER_PROMPT.md                                    │
  │   each cycle: `agent autopilot` → claim the next task          │
  │     • do it directly, OR decompose & dispatch to workers       │
  │     • write a new agent role when one is missing               │
  │     • reply → close → improve tools/skills/agents/core         │
  └───────────────┬───────────────────────────────▲──────────────┘
       spawns      │ (headless `claude` processes)  │ improves
                   ▼                                 │
  ┌── WORKERS (agents/<role>/AGENT.md) ──┐          │
  │  each a claude process with a role;   │          │
  │  every run recorded in the fleet db   │──metrics─┤
  └───────────────────────────────────────┘          │
                                                      │
  ┌── SUPERVISOR (always active) ──────────────────────┘
  │  reads per-agent performance → rewrites the underperformers:
  │  their charters, tools, skills — and the core itself.
  └────────────────────────────────────────────────────────────
```

- The **daemon** is deterministic shell/Python that never blocks on the model — it just
  fills the queue (and can fire periodic supervision).
- The **orchestrator** is your Claude Code session. It dispatches focused subtasks to
  **workers** (separate `claude` processes, each booted with a role charter), keeping
  its own context for planning and integration.
- The **supervisor** closes the loop: it turns *how agents actually performed* into
  *changes that make them better*, including changes to the core.

---

## Quickstart

```bash
# 1. install — no API key, no LLM SDK; core needs nothing. (`claude` CLI must be on PATH.)
python -m venv .venv && source .venv/bin/activate
pip install -e ".[recommended]"          # extras = PDF ingest, web, faster vectors

# 2. (optional) configure identity + Telegram + git in .env
cp .env.example .env && $EDITOR .env      # set AGENT_NAME; there is NO API key to set

# 3. sanity check (verifies the `claude` binary, agent roles, etc.)
agent doctor

# 4. start the always-on daemon (Telegram + cron + supervision). Leave it running.
agent daemon                              # or: scripts/run-daemon.sh under systemd

# 5. start the orchestrator: open Claude Code in this repo and run
#       /loop agent autopilot
#    (it follows MASTER_PROMPT.md and drains the queue forever)
```

Feed it work from anywhere — it picks it up on the next cycle:

```bash
agent task add "research our top 3 competitors and draft a one-pager each"
# ...or message the Telegram bot. The reply comes back in Telegram.
```

Drive the fleet directly:

```bash
agent fleet roles                                   # what roles exist
agent fleet run worker "summarize CHANGELOG.md"     # spawn one worker, get its result
agent fleet new researcher --description "Deep web + KB research."   # write a new agent
agent fleet metrics                                 # how each agent is performing
agent fleet supervise                               # one improvement cycle
```

---

## What it gives you (and what Claude Code already has)

**Claude Code already provides** the brain, file/bash/web tools, and a permission model
— for the orchestrator *and* every spawned worker. This runtime does **not**
re-implement that. It adds the durable, multi-agent, self-rewriting infrastructure, all
as one CLI:

| `agent …` | what it is |
|---|---|
| `autopilot` | claim + print the next task — the `/loop` entrypoint |
| `fleet run/spawn/status/logs/metrics` | spawn worker agents, capture + measure every run |
| `fleet new` | write a new agent role (`agents/<role>/AGENT.md`) |
| `fleet supervise` | one supervision cycle: evaluate + rewrite the laggards |
| `evolve checkpoint/diff/revert/log` | git-backed, unrestricted self-rewrite of the core |
| `task add/done/fail/list/gc` | the durable work queue |
| `tg send` / `daemon` | reply on Telegram / run the always-on receiver+cron+supervision |
| `rag ingest/search` | retrieval over your documents (PDF/MD/HTML/…), zero-dep hybrid search |
| `memory remember/search/journal/user` | persistent markdown memory + recall |
| `know note/list` | a self-rendering knowledge registry (committed) |
| `skill list/show` · `tool new/validate/approve` | on-demand playbooks + the tool workshop |
| `publish commit/status` | commit + push the agent's growth (secret-guarded) |
| `cron add-interval/add-daily` | scheduled work that lands on the queue |

---

## Self-improvement — at every level

When the runtime hits a wall, it doesn't just cope — it changes itself:

- a missing capability → **a tool** (`agent tool new`);
- a recurring procedure → **a skill** (`skills/<name>/SKILL.md`);
- a recurring kind of work → **a new agent** (`agent fleet new`);
- a structural limitation → **a core rewrite** (`agent/`, the CLI — checkpoint with
  `agent evolve`, verify, `agent publish`).

Durable facts go to **memory**, findings to the **knowledge registry**. Everything is
plain text, version-controlled, reviewable, and reversible. Capability compounds across
cycles and across forks. See [`docs/self-improvement.md`](docs/self-improvement.md).

---

## Make it a specialist (the fork story)

This repo is a **template** ("Use this template" on GitHub):

1. Set `AGENT_NAME` and write `workspace/IDENTITY.md` (who this deployment is, who it
   serves).
2. Add domain **agents** under `agents/` and **skills** under `skills/`; seed knowledge
   with `agent rag ingest ./domain_docs`.
3. Run the daemon + a Claude Code `/loop`, point your users at the Telegram bot, and let
   it author tools, write agents, record knowledge, and rewrite its own core as it
   learns — then publish so the improvements persist in *its* repo.

---

## Safety

- **Nothing to leak:** there's no API key in the loop. Secrets are masked out of
  anything logged, and `agent publish` **hard-aborts if a secret got staged**.
- **The operator stays in control:** `AGENT_CONFIRM_DANGEROUS=1` tells the agent to ask
  before destructive or outward-facing actions. Claude Code's own permission prompts
  apply on top.
- **Workers are autonomous by default** (`AGENT_FLEET_PERMISSION_MODE=bypassPermissions`)
  so the fleet runs unattended — dial this down per cohort if you want tighter control.
- **Self-rewrite is git-backed:** `agent evolve checkpoint` before deep changes;
  `agent evolve revert` to recover.

---

## Project layout

```
MASTER_PROMPT.md   the orchestrator's contract — what you give to `/loop`
agent/             the package (pure stdlib)
  cli.py           the `agent` command
  fleet/           spawn workers (runner), agent registry, run metrics, orchestrate, supervise
  evolve/          git-backed self-rewrite (checkpoint/diff/revert/log)
  queue/           durable SQLite task queue
  channels/        Telegram receiver + sender (urllib, zero-dep)
  scheduler/       cron + the always-on daemon
  rag/             loaders → chunkers → embeddings → store → hybrid retrieve
  memory/          markdown files (IDENTITY/USER/MEMORY) + core-memory blocks
  tools/           the tool workshop (scaffold/validate/promote scripts)
  publish/         git self-publish (secret-guarded)
  knowledge.py     the self-rendering knowledge registry
agents/            committed agent-role charters (worker, supervisor, + your own)
authored_tools/    tools the agent wrote (committed)
knowledge/         the knowledge registry (committed)
skills/            SKILL.md playbooks (committed)
workspace/         private runtime state (gitignored): dbs, memory, run logs
```

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the design rationale and
[`docs/`](docs/) for the how-to guides ([fleet](docs/fleet.md),
[self-improvement](docs/self-improvement.md), [deployment](docs/deployment.md),
[RAG](docs/rag.md), [Telegram](docs/telegram.md)).

MIT licensed. Built to be forked — and to rewrite itself.
