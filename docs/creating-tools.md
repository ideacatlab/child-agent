# Creating tools

A guide for a **human developer** hand-writing a tool for scion. (The agent writes
its own tools the same way — see [`authored_tools/README.md`](../authored_tools/README.md).)

A tool here is **not** a `@tool`-decorated Python function — there is no registry, no
JSON schema, no risk level. A tool is just a **standalone CLI script**: a `.py` file with
a usage docstring and an `argparse` interface that a Claude Code session runs via bash,
e.g. `python authored_tools/word_count.py README.md --unit lines`. This is
ali-fleet-recovery's "every tool is a script with a usage docstring; the filesystem is the
registry" convention — the session discovers tools by reading the folder and runs the ones
it needs.

## 1. The contract

A tool is an executable script at `authored_tools/<name>.py` with two things:

- **(a) a module docstring** whose *first line* is the one-sentence description (it's
  what `scion tool list` shows and what the session reads to decide whether to use the
  tool) and whose body documents usage — the flags, the arguments, what it prints.
- **(b) an `argparse` CLI** wired through `main(argv=None) -> int`, returning a process
  exit code, run under `if __name__ == "__main__": raise SystemExit(main())`.

Names are lowercase **snake_case, 2–49 chars** (`^[a-z_][a-z0-9_]{1,48}$`). Files whose
names start with `_` are treated as private and skipped by discovery, so give a real
tool a real name.

That's the whole contract. No import of scion, no decorator, no schema — most tools are
plain stdlib. The session "calls" the tool by reading its docstring and shelling out:
`python authored_tools/<name>.py …`.

## 2. The workshop flow

Scaffold a draft, implement it, validate, approve:

```console
$ scion tool new word_count --description "Count words, lines, or characters in a text file."
scaffolded draft: workspace/tool_drafts/word_count.py
implement it, then: scion tool validate word_count
```

Drafts live in `workspace/tool_drafts/` (gitignored, private). The scaffold is a runnable
skeleton with the shebang, docstring, `argparse`, `run()`, `main()`, and `__main__` guard
already in place — but it deliberately ships with the two stub markers you must replace:

```python
def run():
    """Core logic. Keep it small and composable; reuse it from other tools."""
    raise NotImplementedError        # <- replace

def main(argv=None) -> int:
    ...
    print("TODO: implement word_count")   # <- replace
    return 0
```

`scion tool validate <name>` screens the draft in three stages:

1. **static** — parses the source (syntax must be valid) and requires at least one
   function definition. It also rejects a script that still contains `NotImplementedError`
   or `TODO: implement`, so an un-filled-in scaffold can never pass.
2. **smoke** — runs `python3 <script> --help` (20s budget); it must exit 0. A tool that
   can't even print its own help isn't a tool.
3. It *warns* (non-blocking) on undocumented functions and risky constructs
   (`eval`/`exec`/`compile`/`__import__`, `rm -rf /`, …) — warnings are advisory, not gates.

```console
$ scion tool validate word_count          # while still a stub
❌ [static] still a stub (implement run()/main())
```

`scion tool approve <name>` re-validates the draft and, only if it passes, promotes it from
`workspace/tool_drafts/` into the committed `authored_tools/` folder. A tool that won't
validate never becomes "real".

## 3. Worked example, end to end

Fill the draft in. Here's a complete, correct `word_count.py`:

```python
#!/usr/bin/env python3
"""Count the words, lines, or characters in a text file.

Usage:
    python authored_tools/word_count.py PATH [--unit words|lines|chars]

Prints the count to stdout (e.g. ``42 words``). Exits non-zero if PATH is
missing or unreadable.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def run(path: str, unit: str = "words") -> int:
    """Return the word/line/char count of *path*. Importable, side-effect free."""
    text = Path(path).expanduser().read_text(encoding="utf-8", errors="replace")
    return {
        "words": len(text.split()),
        "lines": len(text.splitlines()),
        "chars": len(text),
    }[unit]


def main(argv=None) -> int:
    """Parse argv, print the count to stdout, and return a process exit code."""
    parser = argparse.ArgumentParser(description="Count words, lines, or chars in a file.")
    parser.add_argument("path", help="file to measure")
    parser.add_argument("--unit", choices=["words", "lines", "chars"], default="words",
                        help="what to count (default: words)")
    args = parser.parse_args(argv)
    try:
        count = run(args.path, args.unit)
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{count} {args.unit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Validate and approve:

```console
$ scion tool validate word_count
✅ [ok] validated (syntax + structure + --help)

$ scion tool approve word_count
promoted: authored_tools/word_count.py

$ scion tool list
word_count               Count the words, lines, or characters in a text file.
```

Now any Claude Code session can run it the same way you would:

```console
$ python authored_tools/word_count.py README.md --unit lines
42 lines
```

(The draft copy stays behind in `workspace/tool_drafts/`; it's gitignored and harmless —
delete it if you like.) Finally, commit the new capability so it's durable and reviewable:
`scion publish commit "add word_count tool"`.

## 4. Conventions worth following

Mirroring ali-fleet-recovery, the tools that age well share a shape:

- **Keep a small importable `run()` core separate from `main()`.** `main` only parses argv
  and prints; `run()` does the work and returns a value. Then another tool can
  `from word_count import run` and reuse it without shelling out.
- **Print results to stdout** in a plain, greppable form. stdout is the tool's return
  value as far as the session is concerned.
- **Exit non-zero on error**, and put the reason on stderr. Don't print a friendly message
  and `return 0` when something failed — the exit code is how a caller (or a pipeline)
  knows.
- **Document usage in the docstring.** The first line sells the tool; the body is its man
  page. This is the only "schema" a tool has.
- **Keep tools composable** — small, single-purpose, stdlib-only where possible, so they
  chain in a bash pipeline and reuse each other's `run()`.

## 5. Hand-placing a script directly

You don't have to use the scaffold. Because the folder *is* the registry, you can drop a
finished `authored_tools/<name>.py` straight into the tree by hand — the contract is
identical (docstring first line = description, `argparse` + `main`, snake_case name, stays
self-documenting). You can still run `scion tool validate <name>` on it afterward
(`validate` falls back to looking in `authored_tools/` when there's no matching draft) to
confirm it screens clean, then `scion publish commit "…"` to ship it.

## 6. Tools that need scion's own infra

Most tools are plain stdlib. But a tool *may* reach into scion when it has to — two easy
options:

- **Shell out to the `scion` CLI** with `subprocess`, e.g. a tool that enriches output with
  a knowledge-base lookup can run `scion rag search "<query>" -k 3` and parse stdout. This
  keeps the tool decoupled from scion's internals.
- **Import scion modules** directly if you prefer, e.g. `from scion.rag.retrieve import
  search` or `from scion.memory.store import get_memory`. Import lazily inside the function
  so a tool that's only ever run standalone stays cheap.

Either way the tool is still just a script: a docstring, an `argparse` CLI, and a `main`
that the session runs via bash.
