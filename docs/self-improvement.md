# Self-improvement

How scion grows new capability at runtime: it writes a small Python function,
**proves it works before it's allowed to persist**, then hot-loads it into the
live registry and version-controls it. This is the Voyager "author a skill" loop,
made safe with SWE-agent's validate-before-apply and an OpenClaw-style approval
gate. A verified tool is permanent capability — capability compounds across runs.

The same chapter covers the agent's other durable self-edits: **skills**
(reusable playbooks), the **knowledge registry** (findings it can re-read), and
**publishing** those improvements back to git.

---

## The loop: when and why the agent authors a tool

The agent reaches for `author_tool` when it notices it lacks a primitive it keeps
needing — "I have no clean way to compute business days", "I keep re-deriving this
parsing by hand". Instead of solving it ad hoc each time, it writes the function
once, validates it, and from then on calls it like any built-in.

Authoring is **not** "save some code and hope". Every candidate runs the
verified-before-persisted pipeline in `scion/tools/authoring.py`
(`author_tool_pipeline`). Each step maps to an `AuthorResult.stage`, and the
result renders with a ✅/❌ prefix and the failing stage in brackets:

| stage | what happens | fails when |
|---|---|---|
| `name` | validate the request | self-tooling disabled, bad name, or unknown risk |
| `static` | **AST screen** of the source (`static_check_source`) + wrap into a module | syntax error, or *no* function to expose as a tool |
| `test` | **sandbox self-test** — runs `code + test_code` in a fresh subprocess | the snippet exits non-zero (an `assert` tripped, an exception) |
| `load` | **import probe** — load the wrapped module in a throwaway `ToolRegistry` | module won't import, or imports but registers no `@tool` |
| `promoted` | copy the draft into `authored_tools/` and **hot-load it live** | (success, when auto-apply is on) |
| `pending` | validated, but **held as a draft** for human approval | (success, when auto-apply is off) |

A few details that matter:

- The **static screen** hard-fails only on a syntax error or a complete absence
  of function definitions. Risky constructs (`eval`, `exec`, `compile`,
  `__import__`, `rm -rf /`, `rmtree('/')`) are surfaced as **warnings, not
  blocks** — the risk/confirmation policy is the real gate for side effects, not
  this scanner. Missing docstrings also warn.
- The **self-test** runs in a subprocess with a 30s timeout and POSIX rlimits
  (CPU + address space). It's a convenience boundary, not a security one; set
  `SCION_SANDBOX_DOCKER_IMAGE` to route shell execution through a container.
- The **import probe** uses a *throwaway* registry, so a broken candidate never
  touches the live tool set. Only `promote()` loads into the real registry.
- `test_code` is optional but the pipeline only truly verifies behavior when it's
  present: **a tool that hasn't been shown to work is not persisted.**

---

## The `author_tool` tool

`scion/tools/builtins/tool_author.py`. Risk: `moderate`.

```text
author_tool(name, description, code, test_code="", risk="moderate") -> str
```

| param | meaning |
|---|---|
| `name` | snake_case tool name (`^[a-z_][a-z0-9_]{1,48}$`); the function name is fine |
| `description` | one-line summary of what the tool does |
| `code` | the function source, e.g. `def slugify(text: str) -> str: ...` |
| `test_code` | optional Python that **calls the function and `assert`s** on results |
| `risk` | `safe` \| `moderate` \| `dangerous` — be honest about side effects |

You write a plain, self-contained function **with type hints and a docstring**;
you do *not* write JSON schema. `@tool` derives everything from the signature
(`scion/tools/base.py`):

- the **function's docstring becomes the tool's description**;
- its **typed arguments become the input schema** (a Google-style `Args:` block
  fills in each parameter's description; params without a default are `required`).

If you don't decorate the function yourself, the pipeline wraps it for you —
prepending `from scion.tools.base import tool` and a
`tool(name=..., risk=...)(...)` line — so a bare `def` is enough.

`test_code` is **strongly encouraged**. It's concatenated after `code` and run in
the sandbox; if any assertion fails, authoring stops at the `test` stage and the
tool is never registered.

Companion (both `safe`, read-only):

- `list_authored_tools()` — JSON of `{live_authored, pending_drafts, total_tools}`.
- `inspect_tool(name)` — a tool's `name`, `risk`, `source`, `description`, and
  `input_schema`.

---

## The approval gate

Two environment variables (see `.env.example`) decide whether the agent can self-
tool at all, and whether validated tools go live automatically:

| env var | default | effect |
|---|---|---|
| `SCION_ALLOW_SELF_TOOLING` | `1` | master switch. If `0`, `author_tool` refuses at the `name` stage |
| `SCION_TOOL_AUTOAPPLY` | `0` | if `1`, validated tools are promoted live; if `0`, they're held as drafts for approval |

The lifecycle of an authored tool on disk:

```
workspace/tool_drafts/<name>.py   ← validated draft (gitignored workspace)
            │  promote()  (auto-apply, or `scion tool approve <name>`)
            ▼
authored_tools/<name>.py          ← live + version-controlled
```

- **Drafts** live under `workspace/tool_drafts/` — private runtime state.
- **Promotion** copies the draft into `authored_tools/` at the repo root and
  hot-loads it into the running registry **by path** (`load_path`), so it's
  callable immediately, mid-session, with no restart.
- With auto-apply off, approve a held draft from the CLI:

  ```bash
  scion tool approve <name>     # -> "activated: <name>"
  scion tool list               # all tools: name [risk] (source) summary
  scion tool show <name>        # the Anthropic tool definition as JSON
  ```

Because `authored_tools/` is tracked by git, `publish_changes` ships the agent's
new capabilities into its own repo — that's how a fork accretes a specialty.

---

## Authoring skills

`scion/tools/builtins/skill_author.py`. Risk: `moderate`.

Where a *tool* is executable capability, a **skill** is durable know-how — a
Markdown playbook for a recurring task that the agent loads on demand.

```text
author_skill(name, description, body) -> str
```

- `name` is kebab-case (`^[a-z0-9][a-z0-9\-]{1,48}$`), e.g. `competitor-research`.
- `description` is the one-liner shown in the skill index.
- `body` is the Markdown instructions.

It writes `skills/<name>/SKILL.md` with a YAML front-matter header, **refuses to
save anything that looks like a secret**, and reloads the index so the skill is
usable immediately. Read them back with `read_skill(name)` / `list_skills`
(both `safe`), or `scion skill list` / `scion skill show <name>`.

---

## Recording knowledge

`scion/tools/builtins/knowledge.py`. Risk: `moderate` (`note_knowledge`),
`safe` (`list_knowledge`).

```text
note_knowledge(title, detail, status="open") -> str   # status: open | in-progress | resolved | note
list_knowledge() -> str
```

`note_knowledge` appends a durable finding/gap/playbook note and returns its id
(`K-001`, `K-002`, …). The registry is **self-rendering**: every write saves
`knowledge/registry.json` *and* re-renders a human-readable
`knowledge/REGISTRY.md`, grouped by status — the same self-rendering-registry
pattern as ali-fleet-recovery's `podgaps.py`. It lives under `knowledge/` so
`publish` version-controls it alongside authored tools and skills.

---

## Publishing improvements

`scion/tools/builtins/publish.py` → `scion/publish/git_publish.py`.

```text
publish_changes(message) -> str        # tool, risk: DANGEROUS
git_status() -> str                    # tool, risk: safe
scion publish "<message>"              # CLI equivalent
```

`publish_changes` stages the working tree, commits with a `Co-Authored-By`
trailer, and pushes to the configured remote. It is the **canonical
DANGEROUS-risk tool**: under the safety policy
(`scion/security/policy.py`), a dangerous call **asks** for a y/n in interactive
use, and is **denied** when running unattended with `SCION_REQUIRE_CONFIRMATION=1`
(the default) and no channel to ask on. Use `--yes` / autonomy to override.

Before any commit, the publisher runs a **secret-staging hard-abort guard**
(`_guard_secrets`): if a staged *filename* matches a secret pattern (`.env`,
`secrets/`, `*.token`, `cookies`, `github-token`, `*.key`) **or** any added line
in the staged diff looks like a secret value, it runs `git reset -q` and aborts
with `ABORT: …` — the commit never happens. This is defence in depth beyond
`.gitignore`.

Pushing requires `SCION_GIT_REMOTE` (with `GITHUB_TOKEN` for an HTTPS remote);
without it the commit is kept locally. The committer identity comes from
`SCION_GIT_AUTHOR`.

---

## Worked example: authoring `business_days`

The agent is asked for business days between two dates, finds it has no such
tool, and writes one. With `SCION_TOOL_AUTOAPPLY=1` it goes live in one shot:

```text
you> business days from 2026-06-01 to 2026-06-15? you don't have a tool for it — make one.

scion> I'll author a small, tested tool for this.
       [tool call] author_tool(
         name="business_days",
         description="Count weekdays (Mon-Fri) in [start, end) for two ISO dates.",
         risk="safe",
         code='''
from datetime import date, timedelta

def business_days(start: str, end: str) -> int:
    """Count weekdays (Mon-Fri) between two ISO dates, start inclusive, end exclusive.

    Args:
        start: ISO date, e.g. "2026-06-01".
        end:   ISO date, exclusive upper bound.
    """
    cur, last = date.fromisoformat(start), date.fromisoformat(end)
    n = 0
    while cur < last:
        if cur.weekday() < 5:
            n += 1
        cur += timedelta(days=1)
    return n
''',
         test_code='''
assert business_days("2026-06-01", "2026-06-15") == 10
assert business_days("2026-06-01", "2026-06-06") == 5
''',
       )
       [tool result] ✅ [promoted] tool 'business_days' validated and registered live.

scion> Done — `business_days` passed its self-test and is registered.
       2026-06-01 → 2026-06-15 is **10** business days.
```

What happened under the hood: `static` parsed and wrapped the function →
`test` ran both `assert`s in the sandbox (both passed) → `load` confirmed the
module registers a tool → `promoted` copied the draft to
`authored_tools/business_days.py` and hot-loaded it.

With `SCION_TOOL_AUTOAPPLY=0` the final line would instead read:

```text
✅ [pending] tool 'business_days' validated; draft saved. Approve to activate
   (SCION_TOOL_AUTOAPPLY=1, or `scion tool approve business_days`).
```

…and you'd run `scion tool approve business_days` to put it live. Either way,
commit the new capability into the agent's repo with
`scion publish "add business_days tool"`.
