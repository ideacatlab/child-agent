# Architecture & Design Rationale

This is a self-rewriting, multi-agent runtime whose brains are **`claude` processes**
on a flat subscription, *not* the Anthropic API. The package is the durable
infrastructure those processes drive. This document explains how it's built, why, and
what it descends from — the deployed agent it grew out of (`ali-fleet-recovery`) and a
survey of open-source harnesses (OpenClaw, Hermes, Nanobot, Vellum, Voyager, Letta,
OpenHands, SWE-agent, LangGraph, CrewAI, smolagents, gptme, LlamaIndex, Haystack).

It started life as a single-brain "sentinel" template (codename *scion*) and was
refactored into what's described here: **no fixed name, no fixed persona, no fixed
core.**

---

## 0. The three central decisions

1. **Subscription, not API.** It never calls an LLM API. The orchestrator is a
   long-lived Claude Code session; every worker and the supervisor is a headless
   `claude -p` process. Consequence: **zero LLM dependency** (no SDK, no key — the core
   is the standard library), and **the agent loop is not ours to write** — Claude Code
   already provides reason→act→observe, tool execution, and a permission model, for the
   orchestrator *and* every spawned worker. We provide everything *around* the loop.

2. **A fleet, not a single brain.** The single biggest limitation of the original design
   was one session doing everything in one context. Now the orchestrator **decomposes
   work and spawns role-specialized worker processes** (`agent fleet run/spawn`), each
   with its own context and charter, every run recorded. An always-on **supervisor**
   reads those records and rewrites the underperformers. This is "multi-brain on a
   subscription": the only cost is wall-clock and your plan's concurrency.

3. **Nothing is stable.** This is not a stable core you grow *around*. The runtime
   **owns and may rewrite every file**, including the CLI, the fleet runner, and this
   architecture — not just author tools beside a frozen engine. Self-rewrite is
   first-class and **unrestricted**; git history (via `agent evolve`) is the only safety
   net, by deliberate choice.

---

## 1. Design principles

1. **Stdlib-only core, no API.** Everything runs on the standard library; optional
   extras (PDF/HTML loaders, local embeddings, numpy) are lazy and degrade gracefully.
2. **Orchestrate; don't hoard context.** The brain delegates focused subtasks to
   workers and keeps its own context for planning and integration.
3. **Measure every agent.** Each worker run is a durable record (role, status, duration,
   summary). Improvement is data-driven, not vibes.
4. **The agent owns its own growth — and its own code.** Tools, skills, *agents*, and
   *the core itself* are all editable and version-controlled. Learning lives in the
   repo, not in weights.
5. **The deterministic layer never blocks on a brain.** The daemon acks instantly and
   persists everything, so nothing is lost across crashes, restarts, or a busy session.
6. **Name-agnostic, per-cohort.** Identity (`AGENT_NAME`), agents, skills, and knowledge
   are the seams a deployment customizes for the people it serves.

---

## 2. Request lifecycle

```
   Telegram message / cron firing / `agent task add`
                  │  enqueue (idempotent, keyed on source+external_id)
                  ▼
        ┌──────────────────────┐
        │  TaskQueue (SQLite)  │  pending → working → done | failed | obsolete
        └──────────┬───────────┘
                   │  the /loop orchestrator calls `agent autopilot` each cycle
                   ▼
   ┌───────────────────────────────────────────────────────────────┐
   │ ORCHESTRATOR (Claude Code session), following MASTER_PROMPT.md: │
   │   1. `agent autopilot` claims + prints the next task            │
   │   2. do it directly  ── or ──  decompose & dispatch:           │
   │         agent fleet run/spawn <role> "<subtask>"   ──► workers  │
   │      (write a new role with `agent fleet new` if missing)       │
   │   3. integrate results; verify; `agent tg send` to reply        │
   │   4. `agent task done <id> --result "…"`                        │
   │   5. improve: tools / skills / agents / core; `agent publish`   │
   └───────────────────────────────────────────────────────────────┘
            │ spawns                          ▲ improves (rewrites charters/tools/core)
            ▼                                 │
   workers: headless `claude` processes ──► fleet metrics ──► SUPERVISOR
   (agents/<role>/AGENT.md)                              (agent fleet supervise)
```

---

## 3. Subsystems

### The master prompt — `MASTER_PROMPT.md`
The orchestrator's operating contract: the cycle (`agent autopilot` → do/dispatch →
reply → close), when to do work vs. dispatch it, how to write new agents, the doctrine
that it owns and may rewrite everything, and the `agent` CLI reference. You hand it to
`/loop`. The agent may edit it to change its own standing behavior.

### The fleet — `agent/fleet/`
The multi-agent core.
- `registry.py` loads **agent-role charters** from `agents/<role>/AGENT.md` (frontmatter
  → spawn config: model, tools, permission mode; body → the worker's appended system
  prompt). Mirrors the skills loader; roles are committed and travel with a fork.
- `runner.py` spawns a worker as `claude -p "<task>" --output-format json
  --permission-mode … --append-system-prompt <charter> [--model …] [--allowedTools …]`,
  captures the JSON result, and records the run. `run_worker` is blocking; `spawn_worker`
  is detached and finalized by `reap()`. The `claude` binary is configurable
  (`AGENT_CLAUDE_BIN`) so tests inject a fake — no tokens spent in CI.
- `metrics.py` is the durable per-run store (SQLite) and the per-role aggregates +
  Markdown `digest()` the supervisor reads.
- `orchestrator.py` is deterministic dispatch glue: `dispatch` (one) and `run_parallel`
  (many, capped at `AGENT_FLEET_MAX_CONCURRENCY`). The *intelligent* decomposition stays
  with the brain.
- `supervisor.py`'s `supervise_once()` reaps finished runs, builds the digest, and
  spawns the `supervisor` role to improve the laggards.

### Self-rewrite — `agent/evolve/`
`checkpoint` / `diff` / `revert` / `log`: git-backed recovery for unrestricted
self-rewrite. No gates — the agent edits its own code with native tools; this just lets
it bookmark a good state and get back to it. `.env` and secrets are `.gitignore`d, so a
checkpoint never stages them.

### The daemon — `agent/scheduler/daemon.py` + `agent/channels/`
The always-on deterministic layer (no LLM). `channels/telegram.py` is a `urllib`-only
**receiver** that long-polls, enqueues, acks, and auto-captures the chat-id — plus a
**sender**. `scheduler/cron.py` is a persisted interval/daily scheduler. The daemon runs
them restart-on-crash and can fire periodic **supervision** (`AGENT_SUPERVISE_EVERY`) so
the fleet improves with no human session open.

### The task queue — `agent/queue/`
Durable SQLite: idempotent insert keyed on `(source, external_id)`, a `pending → working
→ done | failed | obsolete` lifecycle, atomic `claim_next`, retry, stuck-task requeue,
conservative GC. The spine of unattended autonomy. Generalized from ali's `reqqueue.py`.

### The tool workshop — `agent/tools/`
A tool is a small, self-documenting CLI **script** in `authored_tools/`. `authoring.py`
is the discipline: `scaffold` → `validate` (AST screen + `--help` smoke run) → `promote`.
Verified-before-persisted: a tool that won't even load never becomes real.

### RAG — `agent/rag/`
`loaders → chunkers → embeddings → store → retrieve`. Default embedder is a feature-
hashing bag-of-words (zero deps, zero cost) fused with BM25 via reciprocal-rank fusion;
`AGENT_EMBEDDING_BACKEND=sentence-transformers` upgrades to local semantics. Ingestion is
content-hash-dedup'd and upserting.

### Memory & knowledge — `agent/memory/`, `agent/knowledge.py`
File-native (`IDENTITY.md`, `USER.md`, `MEMORY.md`, daily journals) plus Letta-style
core-memory blocks. `IDENTITY.md` is a starting charter the runtime may rewrite, not a
fixed persona. `knowledge.py` is a committed, self-rendering JSON→Markdown registry.

### Self-publish — `agent/publish/`
`git_publish.py`: stage → **hard-abort if any secret is staged** → commit with a
co-author trailer → push. Makes "continuously self-update via GitHub" safe and auditable.

---

## 4. Inheritance map — what came from where

### From `ali-fleet-recovery` (the deployed ancestor; this *is* its model)
| Inherited | Generalized into |
|---|---|
| The deterministic bot enqueues, Claude Code drains | `scheduler/` + `channels/` + the `/loop` master prompt |
| `reqqueue.py` durable SQLite queue (idempotent insert, conservative GC) | `agent/queue/task_queue.py` |
| `sentinel-bot.py` urllib receiver (long-poll, chat-id capture, allow-list) | `agent/channels/telegram.py` |
| `sync.sh` self-publish with secret-staging hard-abort + co-author trailer | `agent/publish/git_publish.py` |
| `podgaps.py` self-rendering JSON→Markdown knowledge registry | `agent/knowledge.py` |
| `aliconf.py` `.env` loader with `set_env_var` write-back | `agent/config.py` |
| "every tool is a script + usage docstring; filesystem-as-registry" | `authored_tools/` + `agent/tools/` |
| restart-on-crash daemon loops; **no embedded LLM SDK** | `agent/scheduler/daemon.py`; the whole no-API design |

### From the open-source harness survey
| Pattern | Source | Where |
|---|---|---|
| Spawn role-specialized sub-agents; orchestrator/worker split | **CrewAI / AutoGen** | `agent/fleet/` |
| Reward signal / measure-then-improve | **Vellum / Voyager** | `agent/fleet/metrics.py` + the supervisor |
| Verified-before-persisted self-authored tools; portable skill *folder* | **Voyager** | `agent/tools/`, `authored_tools/` |
| File-first Markdown state; a workshop approval gate | **OpenClaw** | `agent/memory/`, `agent tool approve` |
| Roles/skills as Markdown with progressive disclosure | **Hermes / OpenClaw** | `agents/`, `skills/` |
| Durable SQLite work board instead of in-process swarms; cron | **Hermes / OpenClaw** | `queue/`, `scheduler/` |
| Hybrid-retrieval contract; dense+BM25 RRF; hash-cached ingestion | **Vellum / Haystack / LlamaIndex** | `agent/rag/` |
| Two-tier memory + self-editing core-memory blocks | **Letta / MemGPT** | `agent/memory/blocks.py` |
| Validate-before-apply (lint/smoke before a change lands) | **SWE-agent** | `agent/tools/authoring.validate` |
| Secret registry / masking | **OpenHands** | `agent/security/secrets.py` |

**Deliberately *not* re-implemented** (Claude Code provides them, and re-implementing
would mean calling the API): the agent loop, code-as-action execution, the tool runner
and JSON tool-schemas, and the in-session subagent mechanism — which the orchestrator
still uses for cheap ephemeral fan-out *alongside* the durable process fleet.

---

## 5. Key decisions & trade-offs

- **Process fleet over in-session-only subagents.** Real `claude` processes give each
  agent its own context, an independently editable charter, and a measurable run record
  — the substrate the supervisor needs. In-session subagents remain available for cheap
  ephemeral fan-out.
- **Unrestricted self-rewrite, git as the net.** No checkpoint/test gate is *enforced*;
  the agent is trusted to rewrite its core and recover via `agent evolve`. Chosen
  deliberately over guard rails — the point is a runtime that can become anything.
- **Name-agnostic base.** No baked-in persona; `AGENT_NAME` + `IDENTITY.md` are filled
  per deploy. The same template serves any cohort.
- **Workers autonomous by default** (`bypassPermissions`) so the fleet runs unattended;
  one env var tightens it per cohort.
- **Hashing+BM25 default for RAG.** Zero-setup, zero-cost lexical recall; one env var
  upgrades to local semantic embeddings.

---

## 6. Extension points

- **MCP**: expose the `agent` CLI as an MCP server so any brain reaches the infra through
  a standard protocol.
- **Worktree-isolated parallel workers**: `AGENT_FLEET_WORKTREE=1` exists; a merge-back
  strategy for parallel file-mutating workers is the natural next step.
- **Richer supervision**: scored runs, regression detection, A/B of charter rewrites.
- **Inline Telegram approval**: callback-button confirmation for dangerous actions.

---

## 7. Pitfalls designed against

- **Lost work** → durable queue, idempotent enqueue, stuck-task requeue; the daemon never
  blocks on a brain.
- **A runaway/forgotten background worker** → every spawn is recorded; `reap()` finalizes
  finished detached runs; `agent fleet status` surfaces them.
- **A self-rewrite that breaks the runtime** → `agent evolve checkpoint` before, `agent
  evolve revert` after; tests + ruff are one command away; git history is the floor.
- **Secret leakage** → no API key in the loop; masking in logs; a publish guard that
  aborts on staged secrets; `.env` gitignored so checkpoints never stage it.
- **Runaway cost** → there is no per-token cost; the only budget is wall-clock and your
  subscription's concurrency.
