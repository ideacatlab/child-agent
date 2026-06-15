# Deployment — running scion 24/7

scion runs as **two long-lived pieces**, and a real deployment keeps both up:

- the **sentinel** — a deterministic, no-LLM daemon (`scion sentinel`) that receives
  Telegram messages and ticks cron, dropping everything onto a durable SQLite queue. You
  supervise it with systemd or `nohup`.
- the **brain** — one **Claude Code session** in this repo running `/loop scion autopilot`.
  It follows [`MASTER_PROMPT.md`](../MASTER_PROMPT.md), and every cycle claims the next task
  off the queue and does it with its own read/write/bash/web tools plus the `scion` CLI.
  **No Anthropic API, no SDK, no per-token cost** — the brain is your subscription.

> There is **no `scion serve`** and no LLM-calling worker — and no `SCION_AUTONOMOUS`,
> `SCION_REQUIRE_CONFIRMATION`, `SCION_TOOL_AUTOAPPLY`, or `SCION_ALLOW_SELF_TOOLING`.
> Those are gone; see the [README](../README.md#how-it-works) for the architecture.

## 1. The two processes (and why you need both)

```
  sentinel  ──  scion sentinel  (a daemon, no LLM)
     Telegram receiver ─┐
     cron ticker        ┴─►  workspace/queue.db  ◄─  scion task add / cron firings
                                      │  (nothing is lost — the queue is durable)
                                      ▼
  brain  ──  ONE Claude Code session:  /loop scion autopilot   (follows MASTER_PROMPT.md)
     each cycle:  scion autopilot → claim next task → do it → reply → scion task done
```

**Both are required, but they fail independently and safely:**

- The **sentinel without the brain** still works — Telegram messages and cron firings
  pile up on the queue — but nothing gets *done* until a brain drains it.
- The **brain without the sentinel** still works — `/loop` keeps draining whatever is
  queued, and you can feed it with `scion task add` — but it has no Telegram/cron input.

## 2. The sentinel — `scion sentinel`

`scion sentinel` runs the always-on deterministic layer and blocks until Ctrl-C:

| Command | What runs |
|---|---|
| `scion sentinel` | Telegram receiver (foreground) + cron ticker (background thread) |
| `scion sentinel --no-telegram` | cron ticker only (background thread; main thread parked) |
| `scion sentinel --no-cron` | Telegram receiver only |
| `scion sentinel --no-telegram --no-cron` | nothing to do — logs a warning and returns (don't) |

**Headless (no Telegram).** If `TELEGRAM_BOT_TOKEN` is empty the receiver is skipped
automatically — exactly like `--no-telegram` — so **only cron runs, in a background
thread**, while the process parks the foreground. That is the normal shape for a backend
node with no chat channel: cron firings still land on the queue for the brain to drain.

**Restart-on-crash is layered.** Each component (`telegram-receiver`, `cron`) runs under
a supervisor that logs and restarts it with capped exponential backoff (2s → 60s);
`scripts/run-sentinel.sh` restarts the whole `scion sentinel` process if it exits; and
systemd (§4) restarts the script — three layers, so a crash anywhere self-heals.

## 3. State & persistence

Everything the running system writes lives under **`workspace/`** — gitignored,
machine-local, and the one tree you must back up:

```
workspace/
  queue.db          durable task queue (Telegram + cron + CLI tasks, status, results)
  vectors.db        RAG vector store
  scheduler.db      cron jobs
  SOUL.md USER.md MEMORY.md   identity + operator profile + long-term memory
  memory/           core-memory blocks
  tool_drafts/      authored-tool drafts awaiting `scion tool approve`
  logs/scion.log    rolling log
```

Relocate the whole tree with **`SCION_WORKSPACE`** (absolute path or `~`), e.g.
`SCION_WORKSPACE=/var/lib/scion/workspace` onto a backed-up volume. **Back it up** — it is
the queue, the memory, and the audit trail. For a consistent SQLite snapshot, copy the
tree while the sentinel is stopped and the brain idle (e.g. `tar czf scion.tgz workspace`).

By contrast **`authored_tools/`, `knowledge/`, and `skills/`** live at the repo root and
are **committed** — the agent's durable, shareable growth. The brain persists them with
`scion publish commit "…"` (§8) or ordinary git, *not* the workspace backup.

## 4. Run the sentinel as a service

`scripts/run-sentinel.sh` wraps `scion sentinel` in its own restart loop and `cd`s to
the repo root. Point systemd at it. **systemd manages the sentinel only — not the
Claude Code session** (you start that yourself in a terminal/tmux, §5).

```ini
# /etc/systemd/system/scion-sentinel.service
[Unit]
Description=scion sentinel — Telegram receiver + cron ticker (no LLM)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=scion
WorkingDirectory=/opt/scion
EnvironmentFile=/opt/scion/.env
Environment=PATH=/opt/scion/.venv/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/opt/scion/scripts/run-sentinel.sh
Restart=always
RestartSec=5
KillSignal=SIGINT          # run_sentinel shuts down cleanly on the Ctrl-C path
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now scion-sentinel
journalctl -u scion-sentinel -f    # systemd's view; app logs also go to workspace/logs/scion.log
```

Notes: `WorkingDirectory` is the repo root and the venv's `bin/` is on `PATH` so the bare
`scion` in `run-sentinel.sh` resolves (adjust `/opt/scion`). scion loads `.env` from the
project root itself, so `EnvironmentFile` is belt-and-braces — keep `.env` to plain
`KEY=value` lines. Quick alternative without systemd:
`nohup ./scripts/run-sentinel.sh >/dev/null 2>&1 &` (logs still land in
`workspace/logs/scion.log`; prefer systemd where restart-on-reboot matters).

## 5. Keeping the brain alive

The brain is interactive, so run it inside **tmux** or **screen** so it survives SSH
disconnects:

```bash
tmux new -s scion-brain
#  inside the session: launch Claude Code in this repo, then start the loop:
/loop scion autopilot
#  detach with Ctrl-b d — the session keeps running. Reattach: tmux attach -t scion-brain
```

`/loop` re-invokes `MASTER_PROMPT.md` each cycle; `scion autopilot` hands the brain the
next task (or prints `IDLE`, in which case it ends the turn and the loop calls it
again). With no interval given, the loop self-paces.

If the brain *does* die, **nothing is lost**: the sentinel keeps queuing, `queue.db` is
durable, and when you restart the loop the first thing `scion autopilot` does is
**re-queue any task that was claimed but never finished**, then resume draining where it
left off.

## 6. Scheduling recurring work

Cron jobs persist in `scheduler.db`. Each firing **drops a task on the durable queue**,
and the brain runs it like any other task — same queue, same recovery, same safety
guidance.

```bash
scion cron add-interval <name> <30m|2h|1d> "<task>"   # every N s/m/h/d (or bare seconds)
scion cron add-daily    <name> <HH:MM>     "<task>"   # once a day at local HH:MM
scion cron list                                       # jobs + next fire time
scion cron remove <name>                              # delete a job
scion cron run                                        # fire all due jobs once, now (testing)
```

Re-adding an existing `<name>` updates it in place. The sentinel's ticker checks for due
jobs about every 30s and de-duplicates each firing, so a job never double-queues per tick.

```bash
# daily memory consolidation + an hourly check (each firing becomes a queue task)
scion cron add-daily    memory-consolidation 04:00 "Merge duplicate MEMORY.md entries; prune stale notes."
scion cron add-interval inbox-check          1h    "Check the shared inbox; summarize anything that needs attention."
```

## 7. Safety knobs for unattended operation

**Claude Code's own permission model is the primary control** — it governs every bash
command, file edit, and web fetch the brain runs, so configure its allow/deny lists and
sandbox to bound what the brain may do. The `SCION_*` flags below are behavioral guidance
the brain reads via the master prompt; they sit *on top* of that gate.

| Var | Default | Meaning |
|---|---|---|
| `SCION_CONFIRM_DANGEROUS` | `1` | Master prompt asks the operator before destructive/outward actions (delete, send, git push). |
| `SCION_ALLOW_PUBLISH` | `1` | Whether the brain may commit + push at all. |

**Sandbox the tool-workshop smoke checks.** `scion tool validate` runs a `--help` smoke
test on authored code. Point `SCION_SANDBOX_DOCKER_IMAGE` at an image and that run routes
through `docker run --rm` with the working dir bind-mounted at `/work` and **networking
off by default**:

```bash
SCION_CONFIRM_DANGEROUS=1
SCION_ALLOW_PUBLISH=1
SCION_SANDBOX_DOCKER_IMAGE=python:3.12-slim
SCION_SANDBOX_NET=none      # default; set e.g. "bridge" only if a check needs egress
```

The **brain's** environment (where you launched Claude Code) needs `docker` on `PATH` for
this — the sentinel never touches the sandbox.

## 8. Self-publish in production

To let the brain push its own improvements (authored tools, skills, knowledge), configure a remote:

```bash
SCION_GIT_REMOTE=git@github.com:you/your-agent.git   # SSH recommended (deploy key, no token in env)
# or HTTPS + token:  SCION_GIT_REMOTE=https://github.com/you/your-agent.git
#                    GITHUB_TOKEN=ghp_...
SCION_GIT_AUTHOR=scion <agent@your-host>
```

`scion publish commit "<message>"` commits and pushes the agent's growth;
`scion publish status` shows the pending diff. The publisher **hard-aborts if a secret
got staged**, regardless of any flag. With `SCION_CONFIRM_DANGEROUS=1` the brain confirms
with you before the push lands; with `SCION_ALLOW_PUBLISH=0` it won't publish at all.

## 9. Operations

```bash
tail -f workspace/logs/scion.log      # follow the live log (SCION_LOG=debug for verbose)

scion doctor                          # workspace, flags, deps, subsystems, channels, start steps
scion task list                       # recent tasks + counts (--status failed / --limit N)
scion cron list                       # schedules + next fire time
scion autopilot                       # claim + print ONE task to hand-drain it yourself
```

`scion doctor` is the first thing to run on a new host: it prints the active workspace,
the `confirm_dangerous` / `allow_publish` flags and embedding backend, the optional deps
installed, the health of each subsystem (queue, knowledge base, authored tools), whether
the Telegram token and git remote are set, and the two commands to start the brain. To
hand-drain one task without the loop, run **`scion autopilot`** — it claims and prints the
next task plus the exact `scion tg send` / `scion task done` lines to finish it; do the
work, then close it. A failed task never stalls anything, and the durable queue means
nothing is lost between runs.
