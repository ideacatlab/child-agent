"""The self-tooling pipeline: author -> validate -> test -> register -> version.

The Voyager loop, made safe with SWE-agent's validate-before-apply and OpenClaw's
approval gate: the agent writes a small function; we statically screen it, run its
self-test in the sandbox, and only then promote it into ``authored_tools/`` and
hot-load it into the live registry. A verified tool is permanent capability.
"""

from __future__ import annotations

import ast
import re
import shutil
from dataclasses import dataclass, field

from scion.config import get_settings
from scion.security.policy import RISK_LEVELS
from scion.tools.registry import ToolRegistry, get_registry
from scion.tools.sandbox import run_python_snippet, static_check_source

_NAME = re.compile(r"^[a-z_][a-z0-9_]{1,48}$")
_HEADER = "from scion.tools.base import tool  # auto-added by scion\n\n"


@dataclass
class AuthorResult:
    ok: bool
    stage: str  # name | static | test | load | promoted | pending
    message: str
    tool_name: str = ""
    warnings: list[str] = field(default_factory=list)

    def render(self) -> str:
        head = ("✅ " if self.ok else "❌ ") + f"[{self.stage}] {self.message}"
        if self.warnings:
            head += "\nwarnings: " + "; ".join(self.warnings)
        return head


def _top_level_functions(src: str) -> list[str]:
    tree = ast.parse(src)
    return [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]


def build_module(name: str, code: str, risk: str) -> str:
    """Wrap raw function source into a registerable module."""
    report = static_check_source(code)
    if report.tool_funcs:
        # already @tool-decorated by the author
        return _HEADER + code.strip() + "\n"
    funcs = _top_level_functions(code)
    if not funcs:
        raise ValueError("no top-level function to expose as a tool")
    entry = name if name in funcs else funcs[0]
    decoration = f'\n\n{entry} = tool(name="{name}", risk="{risk}")({entry})\n'
    return _HEADER + code.strip() + decoration


def author_tool_pipeline(
    name: str,
    description: str,
    code: str,
    *,
    test_code: str = "",
    risk: str = "moderate",
    autoapply: bool | None = None,
) -> AuthorResult:
    s = get_settings()
    if not s.allow_self_tooling:
        return AuthorResult(False, "name", "self-tooling is disabled (SCION_ALLOW_SELF_TOOLING=0)")

    name = name.strip()
    if not _NAME.match(name):
        return AuthorResult(False, "name", "name must be a valid identifier (snake_case)")
    if risk not in RISK_LEVELS:
        return AuthorResult(False, "name", f"risk must be one of {RISK_LEVELS}")

    # 1) static screen
    report = static_check_source(code)
    if not report.ok:
        return AuthorResult(False, "static", "static checks failed: " + "; ".join(report.errors))

    # ensure description lands in the function docstring if absent (best effort)
    try:
        module_text = build_module(name, code, risk)
    except ValueError as exc:
        return AuthorResult(False, "static", str(exc))

    # 2) write a draft
    s.drafts_dir.mkdir(parents=True, exist_ok=True)
    draft = s.drafts_dir / f"{name}.py"
    draft.write_text(module_text, encoding="utf-8")

    # 3) sandboxed self-test (optional but encouraged)
    if test_code.strip():
        rc, out = run_python_snippet(code + "\n\n" + test_code, timeout=30)
        if rc != 0:
            return AuthorResult(
                False, "test", f"self-test failed (exit {rc}):\n{out}", warnings=report.warnings
            )

    # 4) confirm the wrapped module imports & yields a Tool (throwaway registry)
    try:
        probe = ToolRegistry()
        found = probe.load_path(draft, source="authored")
    except Exception as exc:
        return AuthorResult(False, "load", f"module failed to import: {exc}", warnings=report.warnings)
    if not found:
        return AuthorResult(
            False, "load", "module imported but registered no tool (is it @tool-decorated?)",
            warnings=report.warnings,
        )
    tool_name = found[0].name

    # 5) promote or hold for approval
    autoapply = s.tool_autoapply if autoapply is None else autoapply
    if autoapply:
        promote(name)
        return AuthorResult(
            True, "promoted", f"tool '{tool_name}' validated and registered live.",
            tool_name=tool_name, warnings=report.warnings,
        )
    return AuthorResult(
        True, "pending",
        f"tool '{tool_name}' validated; draft saved. Approve to activate "
        f"(SCION_TOOL_AUTOAPPLY=1, or `scion tool approve {name}`).",
        tool_name=tool_name, warnings=report.warnings,
    )


def promote(name: str, registry: ToolRegistry | None = None) -> list[str]:
    """Move a validated draft into authored_tools/ and hot-load it live."""
    s = get_settings()
    draft = s.drafts_dir / f"{name}.py"
    if not draft.exists():
        raise FileNotFoundError(f"no draft named {name}")
    s.authored_tools_dir.mkdir(parents=True, exist_ok=True)
    dest = s.authored_tools_dir / f"{name}.py"
    shutil.copy2(draft, dest)
    reg = registry or get_registry()
    tools = reg.load_path(dest, source="authored")
    return [t.name for t in tools]


def list_drafts() -> list[str]:
    s = get_settings()
    return [p.stem for p in sorted(s.drafts_dir.glob("*.py"))] if s.drafts_dir.exists() else []
