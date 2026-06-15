# scion — Architecture & Design Rationale

scion is a generalist, self-improving agent harness whose **brain is a Claude Code
session** (a flat-rate subscription), *not* the Anthropic API. It is the durable
infrastructure that session drives. This document explains how it's built, why,
and exactly **what was inherited from where** — from the deployed agent it
descends from (`ali-fleet-recovery`) and from a survey of open-source harnesses
(OpenClaw, Hermes Agent, Nanobot, Vellum, Voyager, Letta, OpenHands, SWE-agent,
LangGraph, CrewAI, smolagents, gptme, LlamaIndex, Haystack).

---

## 0. The central decision: subscription, not API

The most important architectural choice is what scion **doesn't** do: it never
calls an LLM API. Harnesses that drive the Anthropic API per-token (OpenClaw,
Hermes, et al.) are powerful but can be very expensive, and several can't run on a
Claude *subscription* at all. scion instead treats a long-lived **Claude Code**
session as the agent runtime — the same thing you'd use interactively — kept
looping by the `/loop` skill and a master prompt. Consequences that shape
everything else:

- **Zero LLM dependency.** No `anthropic` SDK, no API key. The whole core is the
  Python standard library. (This matches ali-fleet-recovery, which had *no*
  `anthropic`/`openai` import anywhere.)
- **The agent loop is not ours to write.** Claude Code already provides the
  reason→act→observe loop, tool execution, file/bash/web access, subagents, and a
  permission/sandbox model. Re-implementing those would be wasteful *and* would
  drag us back onto the API. So scion provides **everything around** the loop and
  lets Claude Code be the loop.
- **The queue is the seam.** A deterministic, no-LLM "sentinel" enqueues work; the
  Claude Code session drains it. This is exactly ali's design — except ali relied
  on a human launching Claude Code out-of-band; scion closes that with `/loop`.

---

## 1. Design principles

1. **Stdlib-only core, no API.** Everything runs on the standard library; optional
   extras (PDF/HTML loaders, local embeddings, numpy) are lazy and degrade
   gracefully.
2. **Don't rebuild the brain.** scion contributes durable infrastructure and
   self-improvement discipline; Claude Code contributes intelligence and native
   tools. The boundary between them is the `scion` CLI.
3. **The agent owns its own growth.** Self-authored tool *scripts*, self-written
   skills, and a self-rendering knowledge registry are first-class and
   version-controlled. Learning lives in the externalized library, not in weights.
4. **Deterministic layer never blocks on the brain.** The sentinel acks instantly
   and persists everything, so nothing is lost across crashes, restarts, or a busy
   session.
5. **Built to be forked.** Persona (`SOUL.md`), skills, knowledge, and authored
   tools are the seams a specialist customizes; the engine underneath is stable.

---

## 2. Request lifecycle

```
   Telegram message / cron firing / `scion task add`
                  │  enqueue (idempotent, keyed on source+external_id)
                  ▼
        ┌──────────────────────┐
        │  TaskQueue (SQLite)  │  pending → working → done | failed | obsolete
        └──────────┬───────────┘
                   │  Claude Code's /loop calls `scion autopilot` each cycle
                   ▼
   ┌──────────────────────────────────────────────────────────┐
   │ the Claude Code session (the brain), following            │
   │ MASTER_PROMPT.md:                                         │
   │   1. `scion autopilot` claims + prints the next task      │
   │   2. do it with native tools + the scion CLI; verify      │
   │   3. `scion tg send <chat> "…"` to reply                  │
   │   4. `scion task done <id> --result "…"`                  │
   │   5. as work arises: author tools, write skills,          │
   │      remember facts, `scion publish commit "…"`           │
   └──────────────────────────────────────────────────────────┘
```

---

## 3. Subsystems

### The master prompt — `MASTER_PROMPT.md`
The brain's operating contract: the cycle (`scion autopilot` → do it → reply →
close), the operating principles (act, verify, stay safe), the `scion` CLI
reference, and the self-improvement habits. The agent can edit it to improve its
own behavior. You hand it to `/loop`.

### The sentinel — `scion/scheduler/` + `scion/channels/`
The always-on deterministic layer. `channels/telegram.py` is a `urllib`-only
**receiver** that long-polls, enqueues each message, acks, and auto-captures the
chat-id into `.env` — plus a **sender** (`scion tg send`). `scheduler/cron.py` is
a persisted interval/daily scheduler that drops timed work on the queue.
`scheduler/supervisor.py` runs them with restart-on-crash. No LLM anywhere here.

### The task queue — `scion/queue/`
Durable SQLite (`task_queue.py`): idempotent insert keyed on
`(source, external_id)`, a `pending → working → done | failed | obsolete`
lifecycle, atomic `claim_next`, retry, stuck-task requeue, conservative GC. The
spine of unattended autonomy. Generalized from ali's `reqqueue.py`.

### The tool workshop — `scion/tools/`
A tool is a small, self-documenting CLI **script** in `authored_tools/` that the
session runs via bash (ali's "every tool is a script with a usage docstring" +
Voyager's portable skill folder). `authoring.py` is the discipline:
`scaffold` → `validate` (AST screen + `--help` smoke run) → `promote` into the
committed folder. `sandbox.py` provides the static screen and a Docker-routable
exec helper. Verified-before-persisted: a tool that won't even load never becomes
real.

### RAG — `scion/rag/`
`loaders → chunkers → embeddings → store → retrieve`. The default embedder is a
**feature-hashing bag-of-words** (zero deps, zero cost) fused with **BM25** via
reciprocal-rank fusion, so retrieval works out of the box; flip
`SCION_EMBEDDING_BACKEND` to `sentence-transformers` (local) for semantics.
Ingestion is content-hash-dedup'd and upserting — re-ingesting a folder only
re-embeds what changed. This is the real value-add over plain Claude Code: it
can't read 200 PDFs, but it can `scion rag search` them.

> Note: Anthropic has no embeddings endpoint, and hosted embeddings (Voyage/OpenAI)
> cost money — which is why the default is local and free.

### Memory & knowledge — `scion/memory/`, `scion/knowledge.py`
File-native (`SOUL.md`, `USER.md`, `MEMORY.md`, daily journals) plus Letta-style
core-memory **blocks**. The agent reads/writes these via `scion memory …`.
`knowledge.py` is a committed, self-rendering JSON→Markdown registry (ali's
`podgaps.py`).

### Self-publish — `scion/publish/`
`git_publish.py`: stage → **hard-abort if any secret is staged** → commit with a
co-author trailer → push. Makes "continuously self-update via GitHub" safe and
auditable. Directly from ali's `sync.sh`.

---

## 4. Inheritance map — what came from where

### From `ali-fleet-recovery` (the deployed ancestor; this *is* its model)
| Inherited | Generalized into |
|---|---|
| The **sentinel pattern**: deterministic bot enqueues, Claude Code drains | `scheduler/` + `channels/` + the `/loop` master prompt |
| `reqqueue.py` durable SQLite queue (idempotent insert, conservative GC) | `scion/queue/task_queue.py` |
| `sentinel-bot.py` urllib receiver (long-poll, chat-id capture, allow-list) | `scion/channels/telegram.py` |
| `sync.sh` self-publish with secret-staging hard-abort + co-author trailer | `scion/publish/git_publish.py` |
| `podgaps.py` self-rendering JSON→Markdown knowledge registry | `scion/knowledge.py` |
| `aliconf.py` `.env` loader with `set_env_var` write-back | `scion/config.py` |
| "every tool is a script + usage docstring; filesystem-as-registry" | `authored_tools/` + `scion/tools/` |
| supervisor restart-on-crash loops; **no embedded LLM SDK** | `scheduler/supervisor.py`; the whole no-API design |

The one gap ali had — *a human had to launch Claude Code to drain the queue* — is
closed by `/loop` + `MASTER_PROMPT.md` + `scion autopilot`.

### From the open-source harness survey
| Pattern | Source | Where in scion |
|---|---|---|
| Verified-before-persisted self-authored tools; portable skill *folder* | **Voyager** | `tools/authoring.py`, `authored_tools/` |
| File-first Markdown state (`SOUL`/`MEMORY`); a workshop approval gate | **OpenClaw** | `memory/`, `scion tool approve` |
| Skills as Markdown with progressive disclosure | **Hermes / OpenClaw** | `skills/` |
| Durable SQLite work board instead of in-process swarms; cron | **Hermes / OpenClaw** | `queue/`, `scheduler/` |
| MCP as a cross-boundary tool contract (recommended next step) | **Nanobot** | extension point (§6) |
| Hybrid-retrieval contract (query + weights + metadata) | **Vellum** | `rag/retrieve.py` |
| Two-tier memory + self-editing core-memory blocks | **Letta / MemGPT** | `memory/blocks.py` |
| Validate-before-apply (lint/smoke before a change lands) | **SWE-agent** | `tools/authoring.validate` |
| Hash-cached, dedup/upsert ingestion; structure-aware chunking | **LlamaIndex** | `rag/pipeline.py`, `rag/chunkers.py` |
| Dense+BM25 fused with reciprocal-rank fusion | **Haystack** | `rag/retrieve.py` |

**Deliberately *not* re-implemented** (Claude Code already provides them, and
re-implementing would mean calling the API): the agent loop / event-sourcing
(OpenHands), code-as-action execution (smolagents/Open Interpreter), the tool
*runner* and JSON tool-schemas, subagent delegation (CrewAI), and the
risk/confirmation engine — the latter is now the master prompt's guidance plus
Claude Code's own permission prompts.

---

## 5. Key decisions & trade-offs

- **Subscription brain over API brain.** The headline decision (§0): no per-token
  cost, runs on a flat subscription, at the price of depending on Claude Code as
  the runtime (which is exactly what you want here).
- **`/loop` over a self-scheduling prompt.** `/loop` re-invokes the master prompt
  for you, so the loop survives the model forgetting to reschedule. The master
  prompt stays simple and the cadence is the operator's to set.
- **Tools are scripts, not registered functions.** No in-process tool registry or
  API tool-schemas — a tool is a script Claude Code runs, the most robust and
  ali-faithful shape, and it keeps `authored_tools/` literally a portable library.
- **Hashing+BM25 default for RAG.** Zero-setup, zero-cost, genuinely useful for
  lexical recall; one env var upgrades to local semantic embeddings.
- **In-process exec is a convenience, not a sandbox.** Claude Code's own
  permission model is the primary control; `SCION_SANDBOX_DOCKER_IMAGE` routes the
  workshop's smoke-runs through a container when you want isolation.

---

## 6. Extension points (where to grow next)

- **MCP**: expose the `scion` CLI as an MCP server (or consume third-party ones) so
  the brain reaches the same infra through a standard protocol.
- **Inline Telegram approval**: callback-button confirmation for dangerous actions
  instead of relying on the session/operator.
- **Richer cron**: full 5-field cron expressions; a heartbeat that enqueues
  proactive "consolidate memory / check on X" tasks.
- **Eval harness**: a `scion eval` that scores authored tools/skills against a test
  suite (Vellum's reward signal) to drive self-improvement with real metrics.

---

## 7. Pitfalls designed against

- **Lost work** → durable queue, idempotent enqueue, stuck-task requeue; the
  sentinel never blocks on the brain.
- **A rotting tool library** → validate (syntax + structure + smoke) before
  promote; every tool version-controlled and revertible.
- **Secret leakage** → no API key in the loop at all; masking in logs; a publish
  guard that aborts on staged secrets.
- **Runaway cost** → there is no per-token cost to run away with; that's the point.
