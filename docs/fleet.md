# The fleet — orchestrator, workers, supervisor

The single biggest limitation of a one-session agent is that everything happens in one
context. The fleet fixes that: the **orchestrator** (your `/loop` session) decomposes
work and spawns **worker agents** — separate `claude` processes, each with its own
context and a role charter — and an always-on **supervisor** watches how they perform
and rewrites the laggards. All on your subscription; the only cost is wall-clock and
your plan's concurrency.

---

## Roles are files: `agents/<role>/AGENT.md`

A role is a Markdown charter with simple frontmatter (how to spawn it) and a body (the
worker's appended system prompt):

```markdown
---
name: researcher
description: Deep-dives a topic across the web and the knowledge base.
model: claude-opus-4-8           # optional — omit to inherit the CLI default
tools: Read, Bash, WebSearch     # optional — maps to --allowedTools
permission_mode: bypassPermissions   # optional — defaults from config
---

You are a research worker. Given a topic, gather from the web and `agent rag search`,
verify claims, and return a tight, cited brief. Your final message IS your result.
```

Two ship with the template: **`worker`** (a focused generalist) and **`supervisor`**
(the improver). Write more as you discover missing specialists:

```bash
agent fleet new researcher --description "Deep web + KB research."
$EDITOR agents/researcher/AGENT.md
agent fleet roles
```

Because they're committed files, roles travel with a fork and are themselves rewritable
— improving an agent often just means editing its charter.

---

## Spawning workers

```bash
agent fleet run <role> "<task>"      # blocking: spawn, wait, print the result
agent fleet spawn <role> "<task>"    # detached: returns a run id immediately
agent fleet status [run_id]          # running / recent runs (reaps finished detached ones)
agent fleet logs <run_id>            # a worker's full captured output
```

Under the hood, `run` shells out to:

```
claude -p "<task>" --output-format json --permission-mode <mode> \
  --append-system-prompt "<the role charter>" --add-dir <repo> [--model …] [--allowedTools …]
```

captures the JSON result, and records the run. The `claude` binary is configurable via
`AGENT_CLAUDE_BIN` (tests point it at a fake so CI spends no tokens).

From inside the orchestrator's loop you typically call `agent fleet run` for a subtask
and read its result, or fan several out and integrate. In Python:

```python
from agent.fleet import run_parallel
results = run_parallel([
    ("researcher", "Profile competitor A"),
    ("researcher", "Profile competitor B"),
    ("writer", "Draft the intro section"),
])  # capped at AGENT_FLEET_MAX_CONCURRENCY; order preserved; failures become error records
```

### Configuration (all `AGENT_*`)

| var | default | meaning |
|---|---|---|
| `AGENT_CLAUDE_BIN` | `claude` | the CLI the runner spawns |
| `AGENT_WORKER_MODEL` | *(inherit)* | model for workers (role frontmatter overrides) |
| `AGENT_FLEET_MAX_CONCURRENCY` | `3` | max simultaneous workers in `run_parallel` |
| `AGENT_FLEET_TIMEOUT` | `1800` | per-worker hard timeout (seconds) |
| `AGENT_FLEET_PERMISSION_MODE` | `bypassPermissions` | how autonomous workers are |
| `AGENT_FLEET_WORKTREE` | `0` | isolate file-mutating workers in a git worktree |
| `AGENT_SUPERVISE_EVERY` | *(off)* | daemon supervision cadence, e.g. `30m` |

---

## Measuring and improving — the supervisor

Every run is a durable record: role, status (`ok|error|timeout`), duration, and a
one-line summary.

```bash
agent fleet metrics            # the Markdown digest (per-role success rate, failures)
agent fleet metrics worker     # JSON aggregate for one role
```

A supervision cycle turns that data into improvements:

```bash
agent fleet supervise          # one cycle, on demand
```

It reaps finished runs, builds the performance digest, and spawns the **`supervisor`**
role with it. The supervisor finds underperformers and fixes the root cause at the right
level — the agent's charter (`agents/<role>/AGENT.md`), the tools/skills it relies on,
or the **core itself** — checkpointing with `agent evolve` and verifying before it
keeps a change.

To make supervision **always-on**, set `AGENT_SUPERVISE_EVERY=30m`; the daemon fires a
cycle on that interval with no human session open.

---

## When to dispatch vs. do it yourself

- **Do it yourself** when the task is small, sequential, or needs your full context.
- **Dispatch to a worker** when it's self-contained and benefits from a fresh context or
  a specialist charter (research, a focused edit, a long grind).
- **Fan out** when subtasks are independent — `run_parallel` runs them concurrently and
  you integrate the results.
- **Write a new agent** when you keep dispatching the same *kind* of work — give it a
  charter once and reuse it.

Keep the orchestrator's context for planning and integration; push the grind to the
fleet.
