# Deployment — running scion unattended

Running scion as a long-lived, hands-off agent: the autonomy stack, the safety flags
that decide what it may do without you, where its state lives, supervision, and
recurring work. Read the
[Safety model](../README.md#safety-model-read-this-before-going-autonomous) first —
autonomy is opt-in and the defaults are conservative on purpose.

## 1. The autonomy stack — `scion serve`

`scion serve` runs the whole hands-off loop in one process:

- the **queue worker** — claims tasks off the durable SQLite queue and runs the agent on each,
- the **cron scheduler** — fires interval/daily jobs that drop tasks on the queue,
- the **Telegram bot** — accepts messages and streams replies (only if a token is set).

Each component runs under a **restart-on-crash supervisor** with capped exponential
backoff (2s → 60s): if one throws it is logged and restarted while the others keep running.

```bash
scion serve                       # worker + scheduler + bot (if TELEGRAM_BOT_TOKEN set)
```

**Headless (no Telegram).** If `TELEGRAM_BOT_TOKEN` is empty the bot is skipped and the
**worker runs in the foreground** with the scheduler behind it — the normal shape for a
backend node. The agent still drains the queue and runs cron jobs; task results are just
stored on the queue record instead of sent anywhere.

**Flags** (each turns one component off):

| Flag | Effect |
|---|---|
| `--no-bot` | Never start the Telegram bot, even with a token. The worker takes the foreground. |
| `--no-worker` | Don't drain the queue. Bot/scheduler still run, but tasks pile up unprocessed. |
| `--no-scheduler` | Don't run cron. Worker + bot still run; scheduled jobs won't fire. |

```bash
scion serve --no-bot                 # headless worker + scheduler (backend node)
scion serve --no-bot --no-scheduler  # pure queue drainer
scion serve --no-worker              # bot + scheduler only (another host drains the queue)
```

Durability is layered: the supervisor restarts a crashed *component*,
`scripts/run-serve.sh` (§4) restarts a crashed `scion serve` *process*, and the worker
re-queues any task orphaned mid-run (a stuck-task sweep runs every ~60s).

## 2. Autonomy & safety flags

Four environment variables decide what the agent may do with no human present. They map
onto a coarse **risk policy**: `safe` runs, `moderate` runs (reversible/loggable),
`dangerous` is **gated**.

| Var | Default | Meaning |
|---|---|---|
| `SCION_AUTONOMOUS` | `0` | Let the worker drain the queue and act without a human in the loop. |
| `SCION_REQUIRE_CONFIRMATION` | `1` | Gate DANGEROUS tools behind an approval step. |
| `SCION_ALLOW_SELF_TOOLING` | `1` | Allow the agent to author + register brand-new tools at runtime. |
| `SCION_TOOL_AUTOAPPLY` | `0` | Auto-activate authored tools that pass static + sandbox checks (else `scion tool approve`). |

**The crucial detail for unattended use:** the worker has **no interactive surface** to
ask for approval (cron tasks have no channel; the Telegram channel streams but cannot
confirm). So under the policy:

- `run_shell`, `run_python`, file edits and other **MODERATE** tools **always run** —
  confirmation does *not* gate them. This is why the Docker sandbox (§6) is the real
  boundary once you grant autonomy with shell access.
- `publish_changes` and other **DANGEROUS** tools are **denied** while
  `SCION_REQUIRE_CONFIRMATION=1`, and **allowed** when it is `0`.

**Cautious** — autonomous, but cannot publish or self-activate tools unattended:

```bash
SCION_AUTONOMOUS=1
SCION_REQUIRE_CONFIRMATION=1     # DANGEROUS tools (publish) denied with no human to ask
SCION_ALLOW_SELF_TOOLING=1
SCION_TOOL_AUTOAPPLY=0           # authored tools wait for `scion tool approve <name>`
SCION_SANDBOX_DOCKER_IMAGE=python:3.12-slim
```

**Trusted autonomous** — fully hands-off, including self-publish and live self-tooling:

```bash
SCION_AUTONOMOUS=1
SCION_REQUIRE_CONFIRMATION=0     # DANGEROUS tools run without asking — see §7
SCION_ALLOW_SELF_TOOLING=1
SCION_TOOL_AUTOAPPLY=1           # validated authored tools go live automatically
SCION_SANDBOX_DOCKER_IMAGE=python:3.12-slim   # strongly recommended at this trust level
```

Even in the trusted profile the **secret-staging guard** (§7) and the static + sandbox
screening of authored tools still apply — they are not governed by these flags.

## 3. State & persistence

Everything the running agent writes lives under **`workspace/`** — gitignored,
machine-local, and the one thing you must back up:

```
workspace/
  queue.db        durable task queue (chat + cron tasks, status, results)
  vectors.db      RAG vector store
  scheduler.db    cron jobs
  SOUL.md USER.md MEMORY.md   identity + user profile + long-term memory
  memory/         core-memory blocks
  sessions/       per-session transcripts
  events/         append-only event log (for replay)
  tool_drafts/    authored tools awaiting approval (when AUTOAPPLY=0)
  logs/scion.log  rolling log
```

Relocate the whole tree with **`SCION_WORKSPACE`** (absolute path, or `~`) — e.g. onto a
backed-up volume: `SCION_WORKSPACE=/var/lib/scion/workspace`.

**Back this directory up.** It is the agent's brain, queue, and audit trail. A periodic
snapshot is enough; for a consistent SQLite copy, take it while the service is stopped:

```bash
systemctl stop scion
tar czf /backups/scion-workspace-$(date +%F).tgz -C /var/lib/scion workspace
systemctl start scion
```

By contrast **`authored_tools/`, `knowledge/`, and `skills/`** live at the repo root and
are **version-controlled** — the agent's durable, shareable growth. Persist them with
`scion publish` (§7) or ordinary git, *not* the workspace backup.

## 4. Run it as a service

`scripts/run-serve.sh` wraps `scion serve` in its own restart loop and `cd`s to the repo
root. Point a process manager at it.

```ini
# /etc/systemd/system/scion.service
[Unit]
Description=scion autonomy stack (worker + scheduler + Telegram bot)
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
User=scion
WorkingDirectory=/opt/scion
EnvironmentFile=/opt/scion/.env
Environment=PATH=/opt/scion/.venv/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/opt/scion/scripts/run-serve.sh
Restart=always
RestartSec=5
KillSignal=SIGINT          # scion shuts down cleanly on the Ctrl-C path
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now scion
journalctl -u scion -f      # systemd's view; app logs also go to workspace/logs/scion.log
```

Notes: point `WorkingDirectory` at the repo root and put the venv's `bin/` on `PATH` so the
bare `scion` in `run-serve.sh` resolves (adjust `/opt/scion`). scion also loads `.env`
itself from the project root, so `EnvironmentFile` is belt-and-braces — keep `.env` to plain
`KEY=value` lines (no trailing `#` comments), which systemd parses literally. Drop
`docker.service` from `After=` if you aren't using the sandbox.

Quick alternative: `nohup ./scripts/run-serve.sh >/dev/null 2>&1 &` — logs still land in
`workspace/logs/scion.log`; prefer systemd where restart-on-reboot matters.

## 5. Scheduling recurring work

Cron jobs persist in `scheduler.db`. Each firing **drops a task on the durable queue**,
and the worker runs it exactly like any chat request (in autonomous mode) — so scheduled
work inherits the same queue, recovery, and safety policy.

```bash
scion cron add-interval <name> <30m|2h|1d> "<task>"   # every N seconds/minutes/hours/days
scion cron add-daily    <name> <HH:MM>     "<task>"   # once a day at local HH:MM
scion cron list                                       # jobs + next fire time
scion cron remove <name>                              # delete a job
```

Intervals accept `s`/`m`/`h`/`d` suffixes (or bare seconds). Re-adding an existing
`<name>` updates it. The scheduler checks for due jobs every ~30s and de-duplicates each
firing, so a job never double-queues for the same tick.

```bash
# nightly memory consolidation
scion cron add-daily memory-consolidation 04:00 \
  "Review today's sessions and new MEMORY.md entries; merge duplicates, prune stale notes,
   and tidy the core memory blocks."

# hourly inbox sweep
scion cron add-interval inbox-check 1h \
  "Check the shared inbox and summarize anything that needs my attention."

# nightly self-publish (only acts unattended if SCION_REQUIRE_CONFIRMATION=0 — §7)
scion cron add-daily nightly-publish 02:30 \
  "If you authored tools or recorded knowledge today, publish_changes with a concise message."
```

## 6. Real sandboxing for execution

By default `run_shell`/`run_python` are subprocesses with timeouts and POSIX resource
caps — a *convenience* boundary, not a security one. Because execution tools are MODERATE
and run **without** confirmation (§2), containerize them before granting autonomy with
shell access.

Set `SCION_SANDBOX_DOCKER_IMAGE` and the agent's shell commands route through
`docker run --rm` against that image, with the working directory bind-mounted at `/work`
and **networking off by default**:

```bash
SCION_SANDBOX_DOCKER_IMAGE=python:3.12-slim
SCION_SANDBOX_NET=none      # default; set e.g. "bridge" only if the agent needs egress
```

Notes: this containerizes `run_shell` (the broad code-as-action surface) — to run Python in
the sandbox, have the agent invoke it via the shell (`python3 - <<'EOF' …`) rather than the
bare `run_python` snippet tool, which still runs in a local subprocess. The service account
needs permission to run containers (the `docker` group) and `docker` on `PATH`. Keep
`SCION_SANDBOX_NET=none` unless a task needs egress. This is the recommended hardening
before flipping `SCION_AUTONOMOUS=1` on any machine you care about.

## 7. Self-publish in production

To let the agent push its own improvements (authored tools + knowledge), configure a
remote:

```bash
SCION_GIT_REMOTE=git@github.com:you/your-agent.git   # SSH remote recommended
# or HTTPS + token:  SCION_GIT_REMOTE=https://github.com/you/your-agent.git
#                    GITHUB_TOKEN=ghp_...
SCION_GIT_AUTHOR=scion <agent@your-host>
```

An **SSH deploy key** is cleanest on a server (no token in the environment).
`scion publish "<msg>"` commits and pushes; the agent does the same via `publish_changes`.

`publish_changes` is **DANGEROUS-risk**. In `scion serve` there is no one to approve it, so
under the default `SCION_REQUIRE_CONFIRMATION=1` it is **denied**. For fully-unattended
publishing you must set `SCION_REQUIRE_CONFIRMATION=0`.

> **Risk:** this also un-gates *every other* dangerous tool for the unattended worker — the
> agent can push to your remote (and take other outward, hard-to-reverse actions) on its
> own. Only do this on a setup you trust, ideally with the Docker sandbox (§6) in place.

The **secret-staging guard** still protects you regardless: the publisher hard-aborts the
commit if any secret-like file or value is staged, and secrets are masked from tool output
and logs.

## 8. Operations

```bash
tail -f workspace/logs/scion.log      # follow the live log (SCION_LOG=debug for verbose)

scion task list                       # recent tasks + counts
scion task list --status failed       # filter by status
scion task list --limit 50

scion doctor                          # config, API key, deps, subsystems, channels
scion task work --once                # drain ONE task in the foreground (no serve stack) — for debugging

scion cron list                       # schedules + next fire time
scion tool list                       # registered + authored tools
```

`scion doctor` is the first thing to run on a new host: it prints the active workspace, the
autonomy/confirmation/self-tooling flags, whether the API key and Telegram token are set, and
which optional dependencies are installed. A failed task never stalls the worker or loses
data from the durable queue — `scion task list --status failed` shows what to retry.
