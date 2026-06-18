"""Scaffold / validate / promote authored tool scripts.

A tool script lives in ``authored_tools/<name>.py``: a normal executable with a
usage docstring and an argparse CLI, runnable as ``python authored_tools/<name>.py
…``. Drafts are validated (syntax + structure + a ``--help`` smoke run) before they
are promoted into the committed folder, so a tool that hasn't been shown to load
never becomes "real".
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from agent.config import get_settings
from agent.tools.sandbox import run_command, static_check_source

_NAME = re.compile(r"^[a-z_][a-z0-9_]{1,48}$")

TEMPLATE = '''\
#!/usr/bin/env python3
"""{description}

Usage:
    python authored_tools/{name}.py [args]
"""
from __future__ import annotations

import argparse


def run():
    """Core logic. Keep it small and composable; reuse it from other tools."""
    raise NotImplementedError


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # parser.add_argument("example")
    args = parser.parse_args(argv)
    print("TODO: implement {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


@dataclass
class ValidationResult:
    ok: bool
    stage: str  # name | static | smoke | ok
    message: str
    warnings: list[str] = field(default_factory=list)

    def render(self) -> str:
        head = ("✅ " if self.ok else "❌ ") + f"[{self.stage}] {self.message}"
        if self.warnings:
            head += "\nwarnings: " + "; ".join(self.warnings)
        return head


def scaffold(name: str, description: str = "") -> Path:
    """Write a starter tool script into the drafts folder and return its path."""
    if not _NAME.match(name):
        raise ValueError("name must be snake_case, 2-49 chars")
    s = get_settings()
    s.drafts_dir.mkdir(parents=True, exist_ok=True)
    path = s.drafts_dir / f"{name}.py"
    path.write_text(TEMPLATE.format(name=name, description=description or name), encoding="utf-8")
    return path


def validate(path: Path | str) -> ValidationResult:
    """Static-screen a tool script, then smoke-run ``--help``."""
    path = Path(path)
    if not path.exists():
        return ValidationResult(False, "name", f"no such file: {path}")
    src = path.read_text(encoding="utf-8")

    report = static_check_source(src)
    if not report.ok:
        return ValidationResult(False, "static", "; ".join(report.errors))
    if "NotImplementedError" in src or "TODO: implement" in src:
        return ValidationResult(False, "static", "still a stub (implement run()/main())",
                                warnings=report.warnings)

    rc, out = run_command(f"python3 {path} --help", timeout=20)
    if rc != 0:
        return ValidationResult(False, "smoke", f"`--help` failed (exit {rc}):\n{out}",
                                warnings=report.warnings)
    return ValidationResult(True, "ok", "validated (syntax + structure + --help)",
                            warnings=report.warnings)


def promote(name: str) -> Path:
    """Move a validated draft into the committed ``authored_tools/`` folder."""
    s = get_settings()
    draft = s.drafts_dir / f"{name}.py"
    if not draft.exists():
        raise FileNotFoundError(f"no draft named {name}")
    s.authored_tools_dir.mkdir(parents=True, exist_ok=True)
    dest = s.authored_tools_dir / f"{name}.py"
    shutil.copy2(draft, dest)
    return dest


def _summary(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip().strip('"').strip("'")
            if line and not line.startswith(("#", "from", "import", '"""', "'''")):
                return line[:80]
    except OSError:
        pass
    return ""


def list_authored() -> list[tuple[str, str]]:
    s = get_settings()
    d = s.authored_tools_dir
    if not d.exists():
        return []
    return [(p.stem, _summary(p)) for p in sorted(d.glob("*.py")) if not p.name.startswith("_")]


def list_drafts() -> list[str]:
    s = get_settings()
    return [p.stem for p in sorted(s.drafts_dir.glob("*.py"))] if s.drafts_dir.exists() else []
