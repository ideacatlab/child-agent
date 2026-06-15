# scion — Architecture & Design Rationale

scion is a generalist, self-improving Claude agent harness, written stdlib-first,
meant to be **forked into specialists**. This document explains how it's built,
*why* each piece is shaped the way it is, and exactly **what was inherited from
where** — both from the deployed agent it descends from (`ali-fleet-recovery`)
and from a survey of open-source harnesses (OpenClaw, Hermes Agent, Nanobot,
Vellum, Voyager, Letta, OpenHands, SWE-agent, LangGraph, CrewAI, smolagents,
gptme, LlamaIndex, Haystack).

---

## 1. Design principles

1. **Stdlib-first core.** The only hard dependency is `anthropic`. Queue, memory,
   RAG, skills, security, publish, and the Telegram client are pure standard
   library. Everything else (PDF/HTML loaders, real embeddings, numpy) is an
   optional extra imported lazily. The agent runs the moment you have an API key.
2. **Everything is a tool.** Memory edits, RAG queries, subagent delegation,
   authoring a new tool, publishing to git — all flow through one tool path with
   one risk policy and one audit log. New capability is *data you drop in*, not a
   core-code change.
3. **The agent owns its own growth.** Self-authored tools, self-written skills,
   and a self-rendering knowledge registry are first-class. Learning lives in the
   externalized, version-controlled library — not in weights.
4. **Autonomy with a safety rail.** A durable queue + worker + cron make it run
   unattended; a risk/confirmation policy + secret masking + a validate-before-
   persist gate keep that autonomy from being reckless.
5. **Built to be forked.** Persona (`SOUL.md`), skills, knowledge, and authored
   tools are the seams a specialist customizes; the engine underneath is stable.

---

## 2. Request lifecycle

```
   Telegram / CLI / cron / the agent itself
                  │  enqueue (idempotent)
                  ▼
        ┌──────────────────────┐
        │  TaskQueue (SQLite)  │   pending → working → done | failed | obsolete
        └──────────┬───────────┘
                   │ worker claims one
                   ▼
   ┌───────────────────────────────────────────────┐
   │ AgentLoop.run()                               │
   │  1. build_system_prompt (SOUL + constitution  │
   │     + tool list + skills index + memory)      │  ← cached prefix
   │  2. llm.complete(stream) ──► Claude           │
   │  3. for each tool_use:                        │
   │       policy.decide(risk) → allow|ask|deny    │
   │       run tool (sandboxed) → mask secrets     │
   │       append tool_result                      │
   │  4. loop until end_turn (≤ max_iterations)    │
   │  5. persist session + append-only event log   │
   └───────────────────────────────────────────────┘
                   │ result
                   ▼
        reply on the originating channel
```

Every step appends to a JSONL **event log** (`workspace/events/<session>.jsonl`)
— the trace and recovery substrate (OpenHands' event-sourcing, in miniature).

---

## 3. Subsystems

### Agent loop — `scion/agent/`
A **manual** Claude tool-use loop (`loop.py`), deliberately not the SDK's
auto-runner, so it can: hot-load tools mid-session, gate risky tools behind a
human, stream to a channel, log every event, and handle `pause_turn`. Uses
adaptive thinking + the `effort` control + prompt caching on the system prefix.
`prompts.py` assembles a stable, cache-friendly system prompt (identity +
operating "constitution" + tool list + skill index + memory). `session.py`
persists the transcript as JSON-safe dicts (thinking blocks preserved unchanged
for replay). `runtime.py` is a contextvars ambient context so tools can reach the
active channel.

### LLM layer — `scion/llm/`
A small `LLMClient` interface with an Anthropic implementation
(`anthropic_client.py`): streaming via `messages.stream`, `thinking={"type":
"adaptive"}`, `output_config={"effort": …}`, and `cache_control` on the system
prompt. Responses are normalized to plain dicts (`block_to_dict`) so the
transcript is JSON and round-trips across turns. A provider registry
(`registry.py`) keeps it swappable.

### Tools — `scion/tools/`
`base.py` derives a JSON schema from a function's **type hints + docstring**
(`@tool`); `registry.py` discovers built-ins at import time and **hot-loads
authored tools by path**; `sandbox.py` runs shell/Python in a subprocess with
timeouts + rlimits (or Docker) and statically screens authored code;
`authoring.py` is the self-tooling pipeline; `builtins/` holds the 33 shipped
tools.

### Memory — `scion/memory/`
File-native (`SOUL.md`, `USER.md`, `MEMORY.md`, daily journals) **plus** Letta-
style core-memory **blocks** rendered into the prompt every turn under a char
budget and edited by tools. Search is a dependency-free ranked keyword scan;
`consolidate()` is the "dreaming" promotion of episodic notes into durable memory.

### RAG — `scion/rag/`
`loaders → chunkers → embeddings → store → retrieve`. The default embedder is a
**feature-hashing bag-of-words** (zero deps) fused with **BM25** via reciprocal-
rank fusion, so retrieval works out of the box; flip `SCION_EMBEDDING_BACKEND` to
`sentence-transformers` / `voyage` / `openai` for semantic search. Ingestion is
**content-hash-dedup'd and upserting** — re-ingesting a folder only re-embeds
what changed.

> Note: Anthropic has **no embeddings endpoint**, which is *why* the default is
> local. Voyage is Anthropic's recommended embeddings partner for a hosted
> upgrade.

### Task queue — `scion/queue/`
Durable SQLite (`task_queue.py`): idempotent insert keyed on
`(source, external_id)`, a `pending → working → done | failed | obsolete`
lifecycle, atomic `claim_next`, retry, stuck-task requeue, and a conservative GC
that never deletes real work.

### Autonomy — `scion/scheduler/`
`worker.py` drains the queue by running the agent on each task and replying;
`cron.py` is a persisted interval/daily scheduler that drops tasks on the queue;
`supervisor.py` runs worker + scheduler + Telegram bot with restart-on-crash.

### Channels — `scion/channels/`
A `Channel` protocol with a CLI implementation and a `urllib`-only **Telegram**
client + bot: long-poll, `chat_id` auto-capture into `.env`, allow-list, and
replies that **stream into one message** with a throttled edit.

### Security — `scion/security/`
`secrets.py` (a `SecretRegistry` that masks credential values everywhere) and
`policy.py` (risk levels + an `allow|ask|deny` confirmation policy).

### Self-publish — `scion/publish/`
`git_publish.py`: stage → **hard-abort if any secret is staged** → commit with a
co-author trailer → push. The mechanism that makes "continuously self-update via
GitHub" safe and auditable.

---

## 4. The self-improvement loop (the crown jewel)

When the agent lacks a reusable capability, it calls `author_tool` with a small
Python function. The pipeline (`scion/tools/authoring.py`) is **verified-before-
persisted** (Voyager's governing rule), hardened with SWE-agent's validate-before-
apply and OpenClaw's approval gate:

```
author → static screen (AST) → sandbox self-test → import probe
       → promote to authored_tools/ + hot-load live   (if auto-apply)
       → else hold as a draft for `scion tool approve`  (default)
       → publish_changes → committed, version-controlled capability
```

Because authored tools are a **portable folder** loaded by path and committed to
git, capability accumulates without fine-tuning and without catastrophic
forgetting. The same shape applies to `author_skill` (durable playbooks) and
`note_knowledge` (the self-rendering registry).

---

## 5. Inheritance map — what came from where

### From `ali-fleet-recovery` (the deployed ancestor we descend from)
| Inherited | Generalized into |
|---|---|
| `reqqueue.py` durable SQLite queue (idempotent insert, conservative GC) | `scion/queue/task_queue.py` |
| `telegram.py` / `sentinel-bot.py` urllib bot (long-poll, chat-id capture, allow-list, markdown fallback) | `scion/channels/telegram.py` |
| `sync.sh` self-publish with secret-staging hard-abort + co-author trailer | `scion/publish/git_publish.py` |
| `podgaps.py` self-rendering JSON→Markdown knowledge registry | `scion/tools/builtins/knowledge.py` |
| `aliconf.py` `.env` loader with `set_env_var` write-back + read-only guardrails | `scion/config.py` + `scion/security/` |
| supervisor restart-on-crash loops | `scion/scheduler/supervisor.py` |
| "answer deterministically, else enqueue for the LLM" bridge | the worker draining the queue |
| **Left behind:** all iOS/pod fleet-recovery domain logic (WDA, usbmuxd, ledger, etc.) | — |

The one gap ali-fleet-recovery had — *no scheduler auto-invokes the LLM; a human
launched Claude Code out-of-band* — is closed here by the built-in worker + cron.

### From the open-source harness survey
| Pattern | Source | Where in scion |
|---|---|---|
| Verified-before-persisted self-authored **skill/tool library**; retrieve→author→test→register | **Voyager** | `tools/authoring.py` |
| Skill **Workshop** proposal/approval gate; file-first Markdown state (`SOUL`/`MEMORY`) | **OpenClaw** | authoring gate; `memory/` |
| Import-time **self-registering tool registry**; named risk; **skills as Markdown** | **Hermes Agent** | `tools/registry.py`, `skills/` |
| Durable **SQLite task board** instead of in-process swarms; cron/heartbeat | **Hermes / OpenClaw** | `queue/`, `scheduler/` |
| **MCP** as a cross-boundary tool contract (recommended next step, see §7) | **Nanobot** | extension point |
| Hybrid-retrieval contract (query + weights + metadata filters); evals mindset | **Vellum** | `rag/retrieve.py` |
| Two-tier memory + **self-editing core-memory blocks** + DB-audited edits | **Letta / MemGPT** | `memory/blocks.py` |
| Event-sourced loop; **risk-score → confirm → secret-mask**; Workspace/Docker sandbox | **OpenHands** | `agent/events.py`, `security/`, `tools/sandbox.py` |
| ACI discipline: **windowed file reads, validate-before-apply edits, capped output** | **SWE-agent** | `tools/builtins/files.py`, `sandbox.py` |
| Durable, resumable state; bounded loop with a circuit-breaker | **LangGraph** | `session.py`, `loop.py` (`max_tool_iterations`) |
| **Code-as-action** + **schema-from-signature** tools | **smolagents** | `tools/builtins/shell.py`, `tools/base.py` |
| Single self-describing **ToolSpec** dataclass; append-only JSONL transcript | **gptme** | `tools/base.py`, `agent/events.py` |
| **Hash-cached, dedup/upsert** ingestion; structure-aware chunking | **LlamaIndex** | `rag/pipeline.py`, `rag/chunkers.py` |
| Hybrid dense+BM25 fused with **reciprocal-rank fusion** | **Haystack** | `rag/retrieve.py` |
| Subagent **delegation as a tool** | **CrewAI / OpenHands** | `tools/builtins/agent_tools.py` |

---

## 6. Key decisions & trade-offs

- **Manual loop over the SDK tool-runner.** Costs us a little code; buys hot-load,
  per-tool confirmation, streaming, and the event log. Non-negotiable for a
  self-modifying, unattended agent.
- **Hashing+BM25 default for RAG.** Not semantic, but zero-setup and genuinely
  useful for lexical recall; the moment you want semantics it's one env var.
- **Authored tools live in `authored_tools/`, loaded by path** (not inside the
  installed package). Keeps them committable and inspectable without polluting
  site-packages, and makes "the repo *is* the skill library" literal.
- **Confirmation over Telegram is disabled by default.** Re-entrant inline
  approval inside the long-poll loop is fiddly; rather than ship something
  fragile, dangerous tools are denied unattended unless you opt into
  `SCION_REQUIRE_CONFIRMATION=0`. Inline-button approval is a clean extension.
- **In-process exec is a convenience, not a sandbox.** We say so loudly and give a
  one-env-var Docker path, mirroring smolagents' honesty.

---

## 7. Extension points (where to grow next)

- **MCP** (Model Context Protocol): adopt it as the *external* tool-interop layer
  (consume third-party MCP servers; optionally expose scion's tools as one) while
  keeping the in-process Python registry as the primary, self-authorable surface —
  the HKUDS/Nanobot split. The provider/registry seams are already in place.
- **Real sandboxing:** wire `SCION_SANDBOX_DOCKER_IMAGE` into a per-session
  container with a persistent shell (OpenHands' action-execution server).
- **Inline Telegram confirmation:** route `policy.ASK` through callback buttons.
- **Evals:** add a `scion eval` that scores tools/skills against a test suite
  (Vellum's reward signal) to drive the self-improvement loop with real metrics.
- **Compaction:** the loop has a `trim()` placeholder; swap in server-side
  compaction (`compact-2026-01-12`) for very long sessions.

---

## 8. Pitfalls designed against

- **Unbounded loops / goal drift** → `max_tool_iterations` circuit-breaker;
  machine-checkable done (the model returns the result, not a promise).
- **A rotting tool library** → verified-before-persisted; drafts held for approval;
  every tool version-controlled and revertible.
- **Secret leakage** → masking in tool output + logs, and a publish guard that
  aborts on staged secrets.
- **Stateless, unrecoverable agents** → append-only event log + persisted sessions
  + durable queue + stuck-task requeue.
- **Mistaking the interpreter for a sandbox** → documented Docker path; rlimits +
  timeouts as the floor, not the ceiling.
