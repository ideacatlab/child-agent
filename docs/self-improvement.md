# Self-improvement

scion has no training loop and no API to tune. Its "brain" is a long-lived
**Claude Code** session looping over `scion autopilot` (the `/loop` skill +
`MASTER_PROMPT.md`), draining a durable queue at zero per-token cost. So getting
better can't mean changing model weights or prompts-to-an-API — it means writing
**durable artifacts into the repo**: tool scripts, skills, knowledge, and memory,
each verified and version-controlled. A committed capability is permanent;
capability compounds across cycles and across forks. This is the
ali-fleet-recovery convention generalized — *every tool is a script with a usage
docstring; the filesystem is the registry* — so a new tool isn't injected into a
running process; the next cycle simply finds the new file on disk.

---

## The premise: the session is the agent

You are *this* Claude Code session, with your own native read/write/bash/web tools
and permission model. "Improving yourself" is not a special mode — it's noticing a
gap during real work and leaving behind something the next cycle can reuse:

- a recurring fiddly computation → a **tool script** under `authored_tools/`;
- a repeatable procedure → a **skill** under `skills/`;
- a durable fact or lesson → **memory** (`workspace/MEMORY.md`);
- a finding worth sharing → the **knowledge registry** (`knowledge/REGISTRY.md`).

Then `scion publish commit "…"` ships it back to git — all plain text, reviewable,
and reversible.

---

## Authoring a tool script

When you find yourself doing the same thing twice, make it a tool. The workshop
is three commands (`scion/tools/authoring.py`):

```bash
scion tool new <name> --description "…"   # scaffold a draft
scion tool validate <name>                # static screen + a --help smoke run
scion tool approve <name>                 # promote the validated draft -> authored_tools/
scion tool list                           # what's available (+ pending drafts)
```

**Scaffold.** `scion tool new` writes a starter script to
`workspace/tool_drafts/<name>.py` (the name must be snake_case,
`^[a-z_][a-z0-9_]{1,48}$`). The template is a real CLI skeleton — a shebang, the
`--description` as the module docstring + a `Usage:` block, a `run()` for the core
logic, and a `main(argv=None) -> int` that wires up `argparse` — and it ships
deliberately broken: `run()` raises `NotImplementedError` and `main()` prints
`TODO: implement <name>`, so an un-implemented draft cannot pass validation.

**Implement.** Make it a small argparse CLI: keep `run()` doing the real work
(small and composable, so other tools can import it), have `main()` parse args and
print the result, and remove the `NotImplementedError` and `TODO: implement`
sentinels the validator looks for.

**Validate.** `scion tool validate <name>` runs the verified-before-persisted
pipeline and renders a ✅/❌ line tagged with the stage that failed
(`ValidationResult.stage`):

| stage | what runs | fails when |
|---|---|---|
| `name` | locate the draft file | no such file on disk |
| `static` | AST screen (`static_check_source`) **+ stub check** | syntax error, *or* the source still contains `NotImplementedError` / `TODO: implement` |
| `smoke` | run `python3 <path> --help` (20s cap) | `--help` exits non-zero (won't even load/parse args) |
| `ok` | — | success: "validated (syntax + structure + --help)" |

The static screen surfaces risky constructs as **warnings, not blocks** — it's a
screen, not a sandbox; the real gate is behavioral. (`validate` checks
`workspace/tool_drafts/` first, then `authored_tools/`, so you can re-screen a
promoted tool too.)

**Approve.** `scion tool approve <name>` **re-runs validation on the draft** and
refuses if it doesn't pass; on success it copies the draft to
`authored_tools/<name>.py` (version-controlled). That's the verified-before-
persisted contract: only a script that passed the screen and ran `--help` lands in
the committed folder, and from then on any cycle just runs it via bash.

---

## Worked example: `business_days`

You're asked how many business days fall between two dates and have no tool for it:

```bash
scion tool new business_days --description "Count weekdays (Mon-Fri) between two ISO dates."
```

Then implement `workspace/tool_drafts/business_days.py` (verified — this exact
script returns `10`, and `--help` exits `0`):

```python
#!/usr/bin/env python3
"""Count weekdays (Mon-Fri) between two ISO dates, start inclusive, end exclusive.

Usage:
    python authored_tools/business_days.py <start> <end>
    python authored_tools/business_days.py 2026-06-01 2026-06-15
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta


def run(start: str, end: str) -> int:
    """Count Mon-Fri days in [start, end). Small + composable; reuse from other tools."""
    cur, last = date.fromisoformat(start), date.fromisoformat(end)
    n = 0
    while cur < last:
        if cur.weekday() < 5:
            n += 1
        cur += timedelta(days=1)
    return n


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("start", help="ISO start date, inclusive")
    parser.add_argument("end", help="ISO end date, exclusive")
    args = parser.parse_args(argv)
    print(run(args.start, args.end))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Validate, approve, then call it like any other CLI:

```bash
scion tool validate business_days
#  ✅ [ok] validated (syntax + structure + --help)
scion tool approve business_days
#  promoted: .../authored_tools/business_days.py
python authored_tools/business_days.py 2026-06-01 2026-06-15
#  10
```

That `10` is now a one-line bash call for every future cycle, and `run()` is
importable so the next tool can compose on it.

---

## Skills: durable playbooks

Where a tool is executable capability, a **skill** is durable know-how — a Markdown
playbook for a recurring procedure. Write `skills/<name>/SKILL.md` with YAML
frontmatter (`name`, `description`) and a body:

```markdown
---
name: competitor-research
description: Profile a competitor from their site + filings into a one-pager.
---

1. `scion rag search` the client collection for prior context.
2. Pull the about/pricing/changelog pages; note positioning + price points.
3. …
```

It shows up in `scion skill list` and you read it back with
`scion skill show <name>`. Skills live under `skills/`, so they're committed and
travel with a fork.

---

## Knowledge and memory

**Knowledge** is shareable, structured findings; **memory** is your private working
recall.

```bash
scion know note "<title>" "<detail>" --status open   # open | in-progress | resolved | note
scion memory remember "<fact>"                        # durable fact -> workspace/MEMORY.md
scion memory journal "<note>"                         # episodic note of this cycle
```

Every `know note` saves `knowledge/registry.json` *and* re-renders a human-readable
`knowledge/REGISTRY.md` grouped by status (returning an id like `K-001`) — the
self-rendering-registry pattern, committed alongside tools and skills. On an idle
cycle, **consolidate**: read `scion memory recent`, pull out the few lessons worth
keeping, and `scion memory remember` them, so the signal survives and the journal
noise doesn't. Recall first (`scion memory search`) before non-trivial work; don't
re-save what the repo or chat already records.

---

## Publishing your growth

When you've added or changed tools, skills, or knowledge worth keeping, ship it:

```bash
scion publish commit "add business_days tool"   # stage -A, commit, push
scion publish status                            # porcelain working-tree state
```

`publish commit` stages the working tree, commits with a `Co-Authored-By` trailer,
and pushes to `origin` when `SCION_GIT_REMOTE` is set (identity from
`SCION_GIT_AUTHOR`); with no remote it keeps the commit locally.

Before any commit it runs a **secret-staging hard-abort guard**
(`scion/publish/git_publish.py`): if a staged *filename* matches a secret pattern
(`.env`, `secrets/`, `*.token`, `cookies`, `github-token`, `*.key`) **or** any
added (`+`) line in the staged diff looks like a secret value (`sk-…`, `ghp_…`,
`xox[baprs]-…`, `AKIA…`, a PRIVATE KEY block), it runs `git reset -q` and raises
`ABORT: …` — the commit never happens. Defence in depth beyond `.gitignore`.

Publishing is outward-facing, so two env switches (shown in `scion doctor`) govern
it as policy the looping agent honors:

- **`SCION_CONFIRM_DANGEROUS=1`** (default) — the master prompt has you **confirm
  with the operator first** (over Telegram) before the push lands.
- **`SCION_ALLOW_PUBLISH=0`** — takes publishing off the table entirely; the master
  switch to check before you ever reach for `scion publish`.

---

## Editing your own brain

The deepest self-edit is your own instructions. `MASTER_PROMPT.md` (the cycle you
run) and `workspace/SOUL.md` (who you are) are just files — refine them to change
your standing behavior, then publish. Specializing a fork is exactly this: rewrite
`SOUL.md`, add domain skills and tools, ingest the role's documents
(`scion rag ingest`), and commit. The you of next month should be sharper than the
you of today — that is the whole point.
