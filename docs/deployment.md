# Deployment — running it 24/7 for a cohort

This runtime runs as **two long-lived pieces**, and a real deployment keeps both up:

- the **daemon** — a deterministic, no-LLM service (`agent daemon`) that receives
  Telegram messages, ticks cron, and (optionally) fires periodic supervision, dropping
  everything onto a durable SQLite queue. Supervise it with systemd or `nohup`.
- the **orchestrator** — one **Claude Code session** in this repo running `/loop agent
  autopilot`. It follows [`MASTER_PROMPT.md`](../MASTER_PROMPT.md): every cycle it claims
  the next task and either does it or **dispatches it to spawned worker agents**. **No
  Anthropic API, no SDK, no per-token cost** — the brain (and every worker) is your
  subscription.

Each deployment is for a specific **cohort of users** (you, or a few colleagues) and is
given an identity via `AGENT_NAME` — the base template ships nameless.

## 1. The two processes (and why you need both)

```
  daemon  ──  agent daemon  (no LLM)
     Telegram receiver ─┐
     cron ticker        ┼─►  workspace/queue.db  ◄─  agent task add / cron firings
     supervision tick  ─┘             │  (nothing is lost — the queue is durable)
                                      ▼
  orchestrator  ──  ONE Claude Code session:  /loop agent autopilot
     each cycle:  agent autopilot → claim → do it OR `agent fleet run <role>` → reply → done
                                      │ spawns
                                      ▼
  workers  ──  headless `claude` processes (agents/<role>/AGENT.md), runs recorded in fleet.db
```

**The pieces fail independently and safely:**
- The **daemon without the orchestrator** still queues Telegram/cron work; nothing gets
  *done* until an orchestrator drains it.
- The **orchestrator without the daemon** still drains whatever is queued (feed it with
  `agent task add`); it just has no Telegram/cron input.
- **Workers** are spawned on demand by the orchestrator (or the supervisor); they don't
  need to be kept running.

## 2. The daemon — `agent daemon`

Runs the always-on deterministic layer and blocks until Ctrl-C:

| Command | What runs |
|---|---|
| `agent daemon` | Telegram receiver (foreground) + cron + supervision (background threads) |
| `agent daemon --no-telegram` | cron + supervision only (main thread parked) |
| `agent daemon --no-cron` | Telegram + supervision |
| `agent daemon --no-supervise` | Telegram + cron, no automatic supervision |

**Headless (no Telegram).** If `TELEGRAM_BOT_TOKEN` is empty the receiver is skipped
automatically; cron (and supervision, if enabled) run in background threads. That's the
normal shape for a backend node with no chat channel.

**Supervision cadence.** Set `AGENT_SUPERVISE_EVERY=30m` (or `2h`, `1d`) to have the
daemon fire one `agent fleet supervise` cycle on that interval — the always-on improver,
with no human session open. Empty = off.

**Restart-on-crash is layered.** Each component (`telegram-receiver`, `cron`,
`supervision`) runs under a keep-alive that restarts it with capped backoff (2s → 60s);
`scripts/run-daemon.sh` restarts the whole process if it exits; systemd (§4) restarts the
script — three layers, so a crash anywhere self-heals.

## 3. State & persistence

Everything the running system writes lives under **`workspace/`** — gitignored,
machine-local, the one tree you must back up:

```
workspace/
  queue.db          durable task queue (Telegram + cron + CLI tasks, status, results)
  fleet.db          per-run worker metrics (role, status, duration, summary)
  vectors.db        RAG vector store
  scheduler.db      cron jobs
  IDENTITY.md USER.md MEMORY.md   identity + operator profile + long-term memory
  memory/           core-memory blocks + daily journals
  runs/             captured stdout of spawned workers
  tool_drafts/      authored-tool drafts awaiting `agent tool approve`
  logs/agent.log    rolling log
```

Relocate the whole tree with **`AGENT_WORKSPACE`** (absolute path or `~`), e.g.
`AGENT_WORKSPACE=/var/lib/agent/workspace` onto a backed-up volume. For a consistent
SQLite snapshot, copy the tree while the daemon is stopped and the orchestrator idle
(`tar czf agent-ws.tgz workspace`).

By contrast **`agents/`, `authored_tools/`, `knowledge/`, and `skills/`** live at the
repo root and are **committed** — the agent's durable, shareable growth. They're persisted
with `agent publish commit "…"` (§8) or ordinary git, *not* the workspace backup.

## 4. Run the daemon as a service

`scripts/run-daemon.sh` wraps `agent daemon` in its own restart loop and `cd`s to the repo
root. Point systemd at it. **systemd manages the daemon only — not the Claude Code
session** (you start that yourself in tmux, §5).

```ini
# /etc/systemd/system/agent-daemon.service
[Unit]
Description=agent daemon — Telegram + cron + supervision (no LLM)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=agent
WorkingDirectory=/opt/agent
EnvironmentFile=/opt/agent/.env
Environment=PATH=/opt/agent/.venv/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/opt/agent/scripts/run-daemon.sh
Restart=always
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now agent-daemon
journalctl -u agent-daemon -f    # app logs also go to workspace/logs/agent.log
```

`WorkingDirectory` is the repo root and the venv's `bin/` is on `PATH` so the bare `agent`
resolves. The runtime loads `.env` from the project root itself, so `EnvironmentFile` is
belt-and-braces. The `claude` binary must be on this `PATH` too, so the daemon's
supervision cycles (and any worker spawned off-session) can run.

## 5. Keeping the orchestrator alive

It's interactive, so run it inside **tmux**/**screen** so it survives SSH disconnects:

```bash
tmux new -s agent-loop
#  inside: launch Claude Code in this repo, then start the loop:
/loop agent autopilot
#  detach: Ctrl-b d  ·  reattach: tmux attach -t agent-loop
```

`/loop` re-invokes `MASTER_PROMPT.md` each cycle; `agent autopilot` hands it the next
task (or prints `IDLE`). If the orchestrator dies, **nothing is lost**: the daemon keeps
queuing, `queue.db` is durable, and on restart `agent autopilot` first re-queues any task
that was claimed but never finished, then resumes draining.

## 6. Scheduling recurring work

Cron jobs persist in `scheduler.db`; each firing drops a task on the durable queue.

```bash
agent cron add-interval <name> <30m|2h|1d> "<task>"
agent cron add-daily    <name> <HH:MM>     "<task>"
agent cron list | remove <name> | run
```

```bash
agent cron add-daily    memory-consolidation 04:00 "Merge duplicate MEMORY.md entries; prune stale notes."
agent cron add-interval inbox-check          1h    "Check the shared inbox; summarize anything that needs attention."
```

The daemon's ticker checks for due jobs ~every 30s and de-duplicates each firing.

## 7. Safety knobs for unattended operation

**Claude Code's own permission model is the primary control** — for the orchestrator and
every spawned worker. The `AGENT_*` flags are behavioral guidance + spawn policy on top.

| Var | Default | Meaning |
|---|---|---|
| `AGENT_CONFIRM_DANGEROUS` | `1` | Ask the operator before destructive/outward actions (delete, send, push). |
| `AGENT_ALLOW_PUBLISH` | `1` | Whether the agent may commit + push at all. |
| `AGENT_FLEET_PERMISSION_MODE` | `bypassPermissions` | How autonomous spawned workers are (`acceptEdits` / `default` to tighten). |
| `AGENT_FLEET_TIMEOUT` | `1800` | Per-worker hard timeout (seconds). |
| `AGENT_FLEET_MAX_CONCURRENCY` | `3` | Max simultaneous workers. |

> Workers default to **fully autonomous** so the fleet runs unattended. For a tighter
> cohort, set `AGENT_FLEET_PERMISSION_MODE=acceptEdits` (or `default`) and lean on Claude
> Code's allow/deny lists.

**Sandbox the tool-workshop smoke checks.** `agent tool validate` runs a `--help` smoke
test on authored code. Point `AGENT_SANDBOX_DOCKER_IMAGE` at an image and that run routes
through `docker run --rm` with the working dir bind-mounted at `/work` and networking off
by default (`AGENT_SANDBOX_NET=none`).

## 8. Self-publish in production

To let the agent push its own growth (agents, tools, skills, knowledge, core changes),
configure a remote:

```bash
AGENT_GIT_REMOTE=git@github.com:you/your-agent.git   # SSH recommended (deploy key)
AGENT_GIT_AUTHOR=YourAgent <agent@your-host>
```

`agent publish commit "<message>"` commits + pushes; `agent publish status` shows the
pending diff. The publisher **hard-aborts if a secret got staged**, regardless of flags.
With `AGENT_CONFIRM_DANGEROUS=1` the agent confirms before the push lands; with
`AGENT_ALLOW_PUBLISH=0` it won't publish at all. Self-rewrite of the core uses the same
path plus `agent evolve checkpoint`/`revert` for recovery.

## 9. Operations

```bash
tail -f workspace/logs/agent.log      # follow the live log (AGENT_LOG=debug for verbose)

agent doctor                          # workspace, flags, deps, subsystems, FLEET, channels
agent task list                       # recent tasks + counts (--status failed / --limit N)
agent fleet status                    # running / recent worker runs (reaps finished ones)
agent fleet metrics                   # per-agent performance digest
agent cron list                       # schedules + next fire time
agent autopilot                       # claim + print ONE task to hand-drain it yourself
```

`agent doctor` is the first thing to run on a new host: it prints the workspace, flags,
optional deps, subsystem health, the **fleet section** (whether `claude` is reachable,
the agent roles found, recorded runs, identity, permission mode), the Telegram/git
status, and the two commands to start the runtime. A failed task or worker never stalls
anything, and the durable queue means nothing is lost between runs.
