# scion 🌱

**A self-improving generalist Claude agent harness.** A *base* — a no-scope agent
that builds its own tools, ingests knowledge, remembers across runs, talks to you
on Telegram, and publishes its own improvements back to GitHub. Fork it and grow a
specialist (a marketer, an SRE, a researcher, a sales assistant) that gets better
from the feedback of the people who use it.

> *scion* (n.): a descendant of a notable line — and a living shoot cut for
> grafting, so a new plant grows from an established root. Both meanings are the
> point: this is a child of Claude that grows new capabilities onto a stable core.

The whole core runs on the **Python standard library**. The only hard dependency
is the LLM SDK (`anthropic`). RAG, web access, and richer embeddings are optional
extras that degrade gracefully — so it runs anywhere, immediately.

---

## Why this exists

Most agent frameworks make you wire up an agent. scion ships the *whole loop*
already assembled and opinionated, with the pieces a long-lived, unattended,
self-improving agent actually needs:

- **A durable task queue** so nothing is lost across crashes or restarts.
- **Self-authored tools** — the agent writes a Python function, it's validated +
  sandbox-tested + registered live + version-controlled. Capability compounds.
- **Markdown-native memory + Letta-style core-memory blocks** the agent edits.
- **Zero-dependency RAG** (hybrid dense+BM25) for "ingest 200 PDFs and become a
  marketer", pluggable up to real embeddings.
- **Telegram** as a first-class channel, with streaming replies.
- **GitHub self-publish** with a hard secret-staging guard.
- **Cron + a worker + a supervisor** so it runs hands-off.
- **Risk-scored, confirmable tools + secret masking** so autonomy stays safe.

It deliberately inherits the battle-tested core of a real deployed agent
(`ali-fleet-recovery`) and grafts on the best ideas from OpenClaw, Hermes Agent,
Nanobot, Vellum, Voyager, Letta, OpenHands, SWE-agent, smolagents, gptme,
LlamaIndex, and Haystack. See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the full
inheritance map and the design rationale.

---

## Quickstart

```bash
# 1. install (core is tiny; add extras for PDFs/web/better embeddings)
python -m venv .venv && source .venv/bin/activate
pip install -e ".[recommended]"        # or just ".", or ".[all]"

# 2. configure
cp .env.example .env
$EDITOR .env                            # set ANTHROPIC_API_KEY

# 3. sanity check
scion doctor

# 4. talk to it
scion chat
```

Then try the things that make it more than a chatbot:

```bash
# give it documents and ask about them
scion rag ingest ./my_docs --collection clientA
scion run "Using the clientA knowledge base, summarize their refund policy."

# let it build itself a tool (turn on auto-apply to skip the approval gate)
SCION_TOOL_AUTOAPPLY=1 scion run "You lack a tool to compute business days between
two dates. Author one, test it, then tell me the business days from 2026-06-01 to
2026-06-15."

# run it unattended (worker + scheduler + Telegram bot, with restart-on-crash)
scion serve
```

---

## The mental model

```
 you ──(Telegram / CLI)──►  task queue (durable SQLite)
                                  │   a worker drains it
                                  ▼
        AgentLoop( Claude, Tools, Memory, RAG, Skills )
                                  │
   ┌──────────┬──────────┬───────┴────┬───────────┬───────────────┐
   ▼          ▼          ▼            ▼           ▼               ▼
 tools     memory      skills        rag      self-tooling     publish
(hot-load) (MEMORY.md  (SKILL.md    (hybrid   (author→verify→  (commit+push,
 + risk)    + blocks)   on demand)   search)   register→ship)   secret-guarded)
```

- **The agent loop** is a manual Claude tool-use loop (streaming, adaptive
  thinking, prompt-cached) — *not* the SDK's auto-runner, because scion needs
  tools that hot-load mid-session, risky tools gated behind confirmation, and an
  append-only event log for replay.
- **Everything is a tool**, including memory edits, RAG queries, delegating to a
  subagent, authoring a new tool, and publishing to git.
- **Autonomy** comes from the queue + worker + cron; the agent acts without a
  human present, and the safety policy decides what it may do unattended.

---

## What it can do out of the box

33 built-in tools across: files (`read_file`, `write_file`, `edit_file`, `grep`,
`find_files`, `list_dir`), execution (`run_shell`, `run_python`), web (`web_fetch`,
`web_search`), memory (`remember`, `search_memory`, `core_memory_append`, …), RAG
(`rag_ingest`, `rag_search`, `rag_stats`), knowledge (`note_knowledge`,
`list_knowledge`), tasks (`enqueue_task`, `list_tasks`), skills (`author_skill`,
`read_skill`), delegation (`spawn_subagent`, `send_update`), **self-tooling**
(`author_tool`, `inspect_tool`, `list_authored_tools`), and **self-publish**
(`publish_changes`, `git_status`).

---

## Make it a specialist (the fork story)

This repo is a **template**. To grow a specialist:

1. **Fork / "Use this template"** on GitHub.
2. Edit `workspace/SOUL.md` (who the agent is) and add domain **skills** under
   `skills/<name>/SKILL.md` (an example, `competitor-research`, is included).
3. Seed its knowledge: `scion rag ingest ./domain_docs`.
4. Deploy it (`scion serve`), point your users at the Telegram bot, and let it
   **author tools, write skills, and record knowledge** as it learns — then
   `publish_changes` so the improvements persist in *its* repo.

The agent that ships is not the agent you'll have in a month. That's the design.

---

## Safety model (read this before going autonomous)

- Every tool has a **risk level**: `safe` (auto), `moderate` (auto, reversible),
  `dangerous` (gated). `publish_changes` is the canonical dangerous tool.
- In interactive use, dangerous tools **ask** (y/n on the CLI). Unattended with
  `SCION_REQUIRE_CONFIRMATION=1` (default), dangerous tools that can't ask are
  **denied**. Set `SCION_REQUIRE_CONFIRMATION=0` only when you trust the setup.
- **Secrets are masked** out of all tool output and logs, and the git publisher
  **hard-aborts** if any secret-like file or value is staged.
- Self-authored tools are **statically screened + sandbox-tested** before they can
  run, and **held for approval** unless `SCION_TOOL_AUTOAPPLY=1`.
- `run_shell` / `run_python` use subprocess timeouts + POSIX rlimits. For real
  isolation set `SCION_SANDBOX_DOCKER_IMAGE` to route execution through Docker.

---

## Command reference

| Command | What it does |
|---|---|
| `scion doctor` | Check config, deps, API key, subsystems |
| `scion chat` | Interactive REPL with streaming |
| `scion run "<prompt>" [--autonomous] [--yes]` | One-shot agent run |
| `scion task add\|list\|work` | Enqueue / inspect / drain the task queue |
| `scion tool list\|show\|approve` | Inspect tools; approve an authored draft |
| `scion skill list\|show` | List / read skills |
| `scion rag ingest\|search\|stats` | Build & query the knowledge base |
| `scion memory show\|search` | Inspect memory |
| `scion cron list\|add-interval\|add-daily\|remove` | Scheduled jobs |
| `scion telegram` | Run the Telegram bot (inline streaming replies) |
| `scion serve` | Run the autonomy stack (worker + scheduler + bot) |
| `scion publish "<msg>"` | Commit + push the agent's changes (guarded) |

Full guides live in [`docs/`](docs/): self-improvement, creating tools, RAG,
Telegram, and deployment.

---

## Project layout

```
scion/            the package (stdlib-first core)
  agent/          the loop, events, prompts, session, runtime context
  llm/            Claude client (streaming, adaptive thinking, caching)
  tools/          Tool + registry + sandbox + authoring + builtins/
  memory/         markdown files + Letta-style blocks
  rag/            loaders → chunkers → embeddings → store → hybrid retrieve
  queue/          durable SQLite task queue
  scheduler/      worker, cron, supervisor
  channels/       CLI + Telegram (urllib, zero-dep)
  security/       secret masking + risk/confirmation policy
  publish/        git self-publish (secret-guarded)
authored_tools/   tools the agent wrote (version-controlled)
knowledge/        the self-rendering knowledge registry (version-controlled)
skills/           SKILL.md playbooks (version-controlled)
workspace/        private runtime state (gitignored): dbs, memory, sessions, logs
```

MIT licensed. Built to be forked.
