# Creating tools

A guide for a **human developer** hand-writing tools for scion. (The agent also
writes its own tools — see [`authored_tools/README.md`](../authored_tools/README.md)
for that draft/approve flow. You, writing by hand, skip the drafts: you drop a
finished, decorated `.py` straight into the tree.)

The whole idea, borrowed from Hermes' "drop a file in, it registers itself": you
write a plain Python function with type hints and a docstring, slap `@tool` on it,
and the model can call it. No hand-written JSON schemas, ever.

## 1. The contract

A tool is **a function + type hints + a Google-style docstring + `@tool`**.

```python
from scion.security.policy import SAFE
from scion.tools.base import tool


@tool(risk=SAFE, parallel_safe=True)
def add(a: int, b: int) -> str:
    """Add two integers.

    Args:
        a: first addend.
        b: second addend.
    """
    return str(a + b)
```

`@tool` reads the function and builds a `Tool` for you (`scion/tools/base.py`):

- The **docstring summary** (everything before `Args:`) becomes the tool
  `description` the model sees. If there's no docstring, the function name is used.
- Each line under **`Args:`** (also accepts `Arguments:`, `Parameters:`, `Params:`)
  becomes that parameter's `description`. The block ends at `Returns:` / `Raises:` /
  `Yields:` / `Examples:`.
- The **JSON schema** is derived from the signature. A parameter **without a
  default** is `required`; one with a default is optional. `additionalProperties`
  is always `false`.

### Type → schema mapping

`build_schema` understands these annotations (anything else falls back to string):

| Python annotation            | JSON schema                                        |
| ---------------------------- | -------------------------------------------------- |
| `str`                        | `{"type": "string"}`                               |
| `int`                        | `{"type": "integer"}`                              |
| `float`                      | `{"type": "number"}`                               |
| `bool`                       | `{"type": "boolean"}`                              |
| `dict` / `dict[K, V]`        | `{"type": "object"}`                               |
| `list` / `list[X]`           | `{"type": "array", "items": <schema of X>}`        |
| `Optional[X]` / `X \| None`  | schema of `X` (optional if it also has a default)  |
| `Literal["a", "b"]`          | `{"type": "string", "enum": ["a", "b"]}`           |
| no hint / `Any`              | `{"type": "string"}`                               |

Notes: `Literal` enums are stringified, so `Literal[1, 2]` renders as
`["1", "2"]`. A `Union` of several real types becomes `anyOf`. Nested generics
work — `list[str]` gives an array of strings.

`@tool` decorator options:

- `risk=` — `SAFE` / `MODERATE` / `DANGEROUS` (see §3). Default `MODERATE`.
- `parallel_safe=` — `True` if the tool has no side effects / is safe to run
  concurrently with others (most read-only tools). Default `False`.
- `name=` — override the tool name (defaults to the function name).
- `tags=` — optional tuple of tags.
- Don't set `source=` by hand; the registry stamps it (`builtin` / `authored`).

## 2. Where to put a tool

Two locations, both auto-discovered by `get_registry()` in
`scion/tools/registry.py`:

**(a) Built-in** — drop a module in `scion/tools/builtins/`. Every submodule is
imported at startup and scanned for `@tool`-marked functions. Use this for core
capabilities that ship with scion.

```python
# scion/tools/builtins/math_tools.py
from scion.security.policy import SAFE
from scion.tools.base import tool


@tool(risk=SAFE, parallel_safe=True)
def square(n: int) -> str:
    """Return n squared.

    Args:
        n: the number to square.
    """
    return str(n * n)
```

**(b) Authored** — drop a `*.py` into `authored_tools/`. These are **hot-loaded by
path** (Voyager's portable-skill-folder pattern) and **version-controlled**
(`scion publish` commits the directory). Use this for project-specific or personal
tools you want tracked in git without touching the package.

```python
# authored_tools/greet.py
from scion.security.policy import SAFE
from scion.tools.base import tool


@tool(risk=SAFE, parallel_safe=True)
def greet(who: str = "world") -> str:
    """Return a friendly greeting.

    Args:
        who: name to greet.
    """
    return f"hello, {who}!"
```

Discovery details: files whose names start with `_` are skipped. Authored tools
load *after* built-ins, so an authored tool with the same `name` overrides the
built-in one. A bad file is logged and skipped — it won't crash the registry.

## 3. Risk levels

Every tool carries a coarse risk level (`scion/security/policy.py`) that drives
the confirmation policy before a call with side effects runs:

- **`SAFE`** — read-only, no side effects (read a file, search, fetch). Always
  runs automatically. Good candidates are also `parallel_safe=True`.
- **`MODERATE`** — side effects that are reversible / loggable (write a file, edit,
  queue a task, send a message). Runs automatically — they're cheap to undo.
- **`DANGEROUS`** — irreversible or high-blast-radius (delete trees, run arbitrary
  shell, push to a remote, spend money). **Gated**: when confirmation is required
  and a human is reachable, the loop pauses to ask. If there's no interactive
  surface to ask on, an unapproved dangerous call is **denied** (unless the run is
  explicitly autonomous with confirmation off).

Choosing: default to the *most restrictive* level that still fits. If a tool both
reads and writes, rate it by the write. If you're unsure whether something is
reversible, call it `DANGEROUS` — a needless confirmation is cheaper than a
surprise.

## 4. Return values and errors

- **Return a `str`** for the cleanest result — it's passed to the model verbatim.
- You may return **anything JSON-serializable** (dict, list, number, …); `Tool.run`
  coerces it with `json.dumps(..., default=str)`. `None` becomes `"(no output)"`.
- **Raise `ToolError`** for a clean, model-visible failure (bad input, missing
  file). The message is shown to the model so it can recover — prefer this over
  letting an arbitrary exception bubble up.

```python
from scion.tools.base import ToolError, tool

@tool(risk="safe")
def head(path: str) -> str:
    """Return the first line of a file.

    Args:
        path: file to read.
    """
    from pathlib import Path
    p = Path(path).expanduser()
    if not p.exists():
        raise ToolError(f"no such file: {path}")   # clean, model sees this
    return p.read_text(encoding="utf-8").splitlines()[0]
```

## 5. Reaching runtime services from inside a tool

Singletons are importable anywhere; call them lazily inside the function body
(keeps import-time cheap and avoids cycles):

- `from scion.queue.task_queue import get_queue`
- `from scion.memory.store import get_memory`
- `from scion.rag.store import get_store` / `from scion.rag.pipeline import get_pipeline`
- `from scion.tools.registry import get_registry`
- `from scion.agent.runtime import current_channel` — the surface the agent is
  currently talking on (Telegram, CLI), or `None` outside a run.

Example — message the operator mid-task (this is roughly the built-in
`send_update`):

```python
from scion.agent.runtime import current_channel

@tool(risk="moderate")
def progress(text: str) -> str:
    """Send the operator a progress update right now.

    Args:
        text: the message to deliver verbatim.
    """
    channel = current_channel()
    if channel is None:
        return "no active channel; nothing sent"
    channel.send(text)
    return "delivered"
```

## 6. Worked example, end to end

Save this as `authored_tools/word_count.py`:

```python
from pathlib import Path
from typing import Literal

from scion.security.policy import SAFE
from scion.tools.base import ToolError, tool


@tool(risk=SAFE, parallel_safe=True)
def word_count(path: str, unit: Literal["words", "lines", "chars"] = "words") -> str:
    """Count words, lines, or characters in a text file.

    Args:
        path: file to measure (relative to the working dir or absolute).
        unit: what to count — one of words, lines, chars.
    """
    p = Path(path).expanduser()
    if not p.exists():
        raise ToolError(f"no such file: {path}")
    text = p.read_text(encoding="utf-8", errors="replace")
    counts = {"words": len(text.split()), "lines": len(text.splitlines()), "chars": len(text)}
    return f"{counts[unit]} {unit} in {path}"
```

Confirm it registered:

```console
$ scion tool list
...
word_count               [safe     ] (authored) Count words, lines, or characters in a text file.
```

Inspect the auto-derived schema the model will see:

```console
$ scion tool show word_count
{
  "name": "word_count",
  "description": "Count words, lines, or characters in a text file.",
  "input_schema": {
    "type": "object",
    "properties": {
      "path": {
        "type": "string",
        "description": "file to measure (relative to the working dir or absolute)."
      },
      "unit": {
        "type": "string",
        "enum": ["words", "lines", "chars"],
        "description": "what to count — one of words, lines, chars."
      }
    },
    "required": ["path"],
    "additionalProperties": false
  }
}
```

Note how `path` (no default) landed in `required`, `unit` (a `Literal` with a
default) became an optional string enum, and both descriptions came straight from
the `Args:` block. That's the whole contract — write the function well and the
schema takes care of itself.

When your tool is ready, `scion publish "add word_count tool"` commits
`authored_tools/` so the capability is durable, reviewable, and rollback-able.
