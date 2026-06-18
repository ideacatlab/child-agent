# Self-improvement

There is no training loop and no API to tune. The brains are `claude` processes on a
subscription. So getting better means writing **durable artifacts into the repo** —
each verified and version-controlled — at whatever level the limitation lives:

| you keep doing… | leave behind… | where |
|---|---|---|
| a fiddly computation | a **tool script** | `authored_tools/` |
| a repeatable procedure | a **skill** | `skills/<name>/SKILL.md` |
| a recurring *kind* of work | a **new agent role** | `agents/<role>/AGENT.md` |
| hitting a structural wall | a **core rewrite** | `agent/`, the CLI |
| a durable fact / lesson | **memory** | `workspace/MEMORY.md` |
| a finding worth sharing | the **knowledge registry** | `knowledge/REGISTRY.md` |

A committed capability is permanent; capability compounds across cycles and across
forks. The deepest difference from a "tools-only" agent: **the core is not off-limits.**
When the system itself is the bottleneck, you rewrite the system.

---

## 1. Tools — a recurring computation

When you find yourself doing the same thing twice, make it a tool. The workshop is three
commands (`agent/tools/authoring.py`):

```bash
agent tool new <name> --description "…"   # scaffold a draft (workspace/tool_drafts/)
agent tool validate <name>                # static screen + a --help smoke run
agent tool approve <name>                 # promote the validated draft -> authored_tools/
agent tool list                           # what's available (+ pending drafts)
```

The scaffold ships deliberately broken (`run()` raises, `main()` prints `TODO`), so an
un-implemented draft can't pass validation. Implement a small argparse CLI — keep
`run()` doing the real work (importable, composable), have `main()` parse args and
print — then validate (syntax + structure + a 20s `--help` run) and approve. Only a
script that loads and runs `--help` lands in the committed folder; from then on any cycle
just runs it via bash. (Worked example: `docs/creating-tools.md`.)

---

## 2. Skills — a repeatable procedure

Where a tool is executable capability, a **skill** is durable know-how — a Markdown
playbook. Write `skills/<name>/SKILL.md` with YAML frontmatter (`name`, `description`)
and a body; it shows up in `agent skill list` and you read it back with `agent skill show
<name>`. Skills are committed and travel with a fork.

---

## 3. Agents — a recurring kind of work

When you keep dispatching the same *kind* of task, give it a specialist. `agent fleet new
<role>` scaffolds `agents/<role>/AGENT.md`; edit the charter (frontmatter tunes model /
tools / permission mode, the body becomes its system prompt), then dispatch:

```bash
agent fleet new researcher --description "Deep web + KB research."
$EDITOR agents/researcher/AGENT.md
agent fleet run researcher "Profile competitor X"
```

**Improving an existing agent is usually just editing its charter.** The supervisor does
exactly this, data-driven: `agent fleet metrics` shows which agents underperform, `agent
fleet supervise` spawns the supervisor to rewrite their charters/tools/skills. See
`docs/fleet.md`.

---

## 4. The core — a structural wall

Nothing here is fixed. If the limitation is in *how the runtime works* — the CLI, the
fleet runner, the queue, the daemon, this very doc — fix that, don't just work around it
once. Self-rewrite is **unrestricted**; git is the safety net:

```bash
agent evolve checkpoint "before reworking the runner"   # commit current state
# ... edit anything under agent/ with your native tools ...
pytest -q && ruff check agent tests                      # verify
agent evolve diff                                        # review the change
agent publish commit "fleet: stream worker output to logs"   # keep it (secret-guarded)
# if it made things worse:
agent evolve revert                                      # back to the last checkpoint
```

`agent evolve log` shows the checkpoint/commit history. `.env` and secrets are
`.gitignore`d, so a checkpoint never stages them. There are no gates — the runtime is
trusted to rewrite its own core and recover.

---

## 5. Knowledge and memory

**Knowledge** is shareable, structured findings; **memory** is your private working
recall.

```bash
agent know note "<title>" "<detail>" --status open   # open | in-progress | resolved | note
agent memory remember "<fact>"                        # durable fact -> workspace/MEMORY.md
agent memory journal "<note>"                         # episodic note of this cycle
```

Every `know note` saves `knowledge/registry.json` *and* re-renders a human-readable
`knowledge/REGISTRY.md`. On an idle cycle, **consolidate**: read `agent memory recent`,
pull out the few lessons worth keeping, `agent memory remember` them. Recall first
(`agent memory search`, `agent rag search`) before non-trivial work; don't re-save what
the repo or chat already records.

---

## 6. Publishing your growth

When you've added or changed tools, skills, agents, knowledge, or core code worth
keeping, ship it:

```bash
agent publish commit "add researcher agent + competitor-research skill"
agent publish status
```

`publish commit` stages the working tree, commits with a `Co-Authored-By` trailer, and
pushes to `origin` when `AGENT_GIT_REMOTE` is set. Before any commit it runs a
**secret-staging hard-abort guard** (`agent/publish/git_publish.py`): if a staged
filename matches a secret pattern (`.env`, `secrets/`, `*.token`, `*.key`, cookies) **or**
any added line looks like a secret value (`sk-…`, `ghp_…`, `xox[baprs]-…`, `AKIA…`, a
PRIVATE KEY block), it runs `git reset` and aborts — the commit never happens.

Two policy switches (shown in `agent doctor`):
- **`AGENT_CONFIRM_DANGEROUS=1`** (default) — confirm with the operator before the push
  lands.
- **`AGENT_ALLOW_PUBLISH=0`** — takes publishing off the table entirely.

---

## 7. Editing your own instructions

The deepest self-edit is your own contract. `MASTER_PROMPT.md` (the cycle you run),
`workspace/IDENTITY.md` (who you are), and every `agents/<role>/AGENT.md` are just files
— refine them to change standing behavior, then publish. Specializing a fork is exactly
this: set `AGENT_NAME`, rewrite `IDENTITY.md`, add domain agents/skills/tools, ingest the
role's documents (`agent rag ingest`), and commit. The you of next month should be
sharper than the you of today — that is the whole point.
