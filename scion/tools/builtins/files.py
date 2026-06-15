"""File system tools: read (windowed), write, edit, list, find, grep."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from scion.security.policy import MODERATE, SAFE
from scion.tools.base import ToolError, tool

_MAX_READ = 40000


@tool(risk=SAFE, parallel_safe=True)
def read_file(path: str, offset: int = 0, limit: int = 0) -> str:
    """Read a text file. Optionally window it by line.

    Args:
        path: path to the file (relative to the working dir or absolute).
        offset: 0-based line to start from.
        limit: max lines to return (0 = to end, capped for safety).
    """
    p = Path(path).expanduser()
    if not p.exists():
        raise ToolError(f"no such file: {path}")
    if p.is_dir():
        raise ToolError(f"{path} is a directory; use list_dir")
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    end = len(lines) if limit <= 0 else min(len(lines), offset + limit)
    chunk = "\n".join(lines[offset:end])
    if len(chunk) > _MAX_READ:
        chunk = chunk[:_MAX_READ] + "\n…[truncated]"
    header = f"# {path} (lines {offset + 1}-{end} of {len(lines)})\n"
    return header + chunk


@tool(risk=MODERATE)
def write_file(path: str, content: str) -> str:
    """Create or overwrite a file with *content*.

    Args:
        path: destination path.
        content: full file content to write.
    """
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} bytes to {path}"


@tool(risk=MODERATE)
def edit_file(path: str, old: str, new: str) -> str:
    """Replace an exact substring in a file (must occur exactly once).

    Args:
        path: file to edit.
        old: exact text to find (include enough context to be unique).
        new: replacement text.
    """
    p = Path(path).expanduser()
    if not p.exists():
        raise ToolError(f"no such file: {path}")
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0:
        raise ToolError("`old` text not found; read the file first")
    if count > 1:
        raise ToolError(f"`old` text is not unique ({count} matches); add more context")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    return f"edited {path}"


@tool(risk=SAFE, parallel_safe=True)
def list_dir(path: str = ".") -> str:
    """List the entries of a directory.

    Args:
        path: directory to list (default current).
    """
    p = Path(path).expanduser()
    if not p.exists():
        raise ToolError(f"no such directory: {path}")
    entries = []
    for child in sorted(p.iterdir()):
        kind = "d" if child.is_dir() else "f"
        size = child.stat().st_size if child.is_file() else 0
        entries.append(f"{kind} {child.name}" + (f" ({size}b)" if kind == "f" else "/"))
    return "\n".join(entries) or "(empty)"


@tool(risk=SAFE, parallel_safe=True)
def find_files(pattern: str, path: str = ".") -> str:
    """Find files matching a glob pattern (recursive).

    Args:
        pattern: glob like ``*.py`` or ``**/*.md``.
        path: root to search from.
    """
    root = Path(path).expanduser()
    matches = []
    for p in root.rglob("*"):
        if p.is_file() and fnmatch.fnmatch(p.name, pattern):
            matches.append(str(p))
            if len(matches) >= 200:
                matches.append("…[200+ matches]")
                break
    return "\n".join(matches) or "(no matches)"


@tool(risk=SAFE, parallel_safe=True)
def grep(pattern: str, path: str = ".", glob: str = "*") -> str:
    """Search file contents for a regex; lists matching lines with locations.

    Args:
        pattern: a regular expression.
        path: file or directory to search.
        glob: only search files whose name matches this glob.
    """
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        raise ToolError(f"bad regex: {exc}")
    root = Path(path).expanduser()
    files = [root] if root.is_file() else [
        p for p in root.rglob("*") if p.is_file() and fnmatch.fnmatch(p.name, glob)
    ]
    hits: list[str] = []
    for f in files:
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{f}:{i}: {line.strip()[:200]}")
                    if len(hits) >= 200:
                        return "\n".join(hits) + "\n…[200+ matches]"
        except OSError:
            continue
    return "\n".join(hits) or "(no matches)"
