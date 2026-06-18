"""Execution sandbox helpers + static analysis for self-authored code.

Honest about its limits: a subprocess with timeouts + POSIX rlimits is a
*convenience* boundary, not a security one (the smolagents warning). For real
isolation, point ``AGENT_SANDBOX_DOCKER_IMAGE`` at an image and commands route
through ``docker run``. Self-authored tools are statically screened before they
can be promoted (SWE-agent's validate-before-apply).
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

OUTPUT_CAP = 16000  # chars of captured output handed back to the model


def _truncate(text: str, cap: int = OUTPUT_CAP) -> str:
    if len(text) <= cap:
        return text
    head = text[: cap - 200]
    return f"{head}\n…[truncated {len(text) - cap + 200} chars]"


def _posix_limits():  # pragma: no cover - platform specific
    """preexec_fn that caps CPU seconds and address space on POSIX."""
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (30, 35))
        # 2 GiB address space
        soft = 2 * 1024 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (soft, soft))
    except Exception:
        pass


def run_command(
    command: str,
    *,
    cwd: Path | None = None,
    timeout: int = 120,
    env: dict | None = None,
) -> tuple[int, str]:
    """Run a shell command, returning ``(returncode, combined_output)``.

    Honors ``AGENT_SANDBOX_DOCKER_IMAGE`` to run inside a container.
    """
    docker_image = os.environ.get("AGENT_SANDBOX_DOCKER_IMAGE", "").strip()
    run_env = {**os.environ, **(env or {})}
    workdir = str(cwd or Path.cwd())

    if docker_image:
        argv = [
            "docker", "run", "--rm", "--network", os.environ.get("AGENT_SANDBOX_NET", "none"),
            "-v", f"{workdir}:/work", "-w", "/work", docker_image,
            "bash", "-lc", command,
        ]
        preexec = None
    else:
        argv = ["bash", "-lc", command]
        preexec = _posix_limits if os.name == "posix" else None

    try:
        proc = subprocess.run(
            argv,
            cwd=workdir if not docker_image else None,
            env=run_env,
            capture_output=True,
            text=True,
            timeout=timeout,
            preexec_fn=preexec,
        )
    except subprocess.TimeoutExpired:
        return 124, f"[timeout after {timeout}s]"
    except FileNotFoundError as exc:
        return 127, f"[command runner not found: {exc}]"

    out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
    return proc.returncode, _truncate(out.strip())


def run_python_snippet(code: str, *, cwd: Path | None = None, timeout: int = 60) -> tuple[int, str]:
    """Execute a Python snippet in a fresh subprocess; capture stdout/stderr.

    Honors ``AGENT_SANDBOX_DOCKER_IMAGE`` (routes through the same container path
    as :func:`run_command`) so shell and Python execution share one boundary.
    """
    if os.environ.get("AGENT_SANDBOX_DOCKER_IMAGE", "").strip():
        return run_command(
            "python3 - <<'__AGENT_PY__'\n" + code + "\n__AGENT_PY__",
            cwd=cwd,
            timeout=timeout,
        )
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(code)
        script = f.name
    try:
        preexec = _posix_limits if os.name == "posix" else None
        proc = subprocess.run(
            [sys.executable, script],
            cwd=str(cwd or Path.cwd()),
            capture_output=True,
            text=True,
            timeout=timeout,
            preexec_fn=preexec,
        )
        out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
        return proc.returncode, _truncate(out.strip())
    except subprocess.TimeoutExpired:
        return 124, f"[timeout after {timeout}s]"
    finally:
        try:
            os.unlink(script)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# static analysis for authored tools
# --------------------------------------------------------------------------- #
_RISKY_CALLS = {"eval", "exec", "compile", "__import__"}
_RISKY_SNIPPETS = ("rm -rf /", "rmtree('/')", 'rmtree("/")', ":(){", "shutil.rmtree('/')")


@dataclass
class StaticReport:
    ok: bool
    func_names: list[str] = field(default_factory=list)
    tool_funcs: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"ok={self.ok}", f"functions={self.func_names}"]
        if self.errors:
            parts.append("errors=" + "; ".join(self.errors))
        if self.warnings:
            parts.append("warnings=" + "; ".join(self.warnings))
        return " | ".join(parts)


def static_check_source(src: str) -> StaticReport:
    """Screen authored Python before it is allowed to become a live tool.

    Hard-fails on syntax errors or a complete absence of documented functions;
    warns (but does not block) on risky constructs — the risk/confirmation
    policy is the gate for those, not this scanner.
    """
    errors: list[str] = []
    warnings: list[str] = []
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return StaticReport(ok=False, errors=[f"SyntaxError: {exc}"])

    func_names: list[str] = []
    tool_funcs: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            func_names.append(node.name)
            if ast.get_docstring(node) is None and not node.name.startswith("_"):
                warnings.append(f"function {node.name!r} has no docstring")
            # detect @tool decoration (used to confirm it'll register)
            for dec in node.decorator_list:
                dname = _decorator_name(dec)
                if dname in ("tool", "agent.tools.tool", "base.tool"):
                    tool_funcs.append(node.name)
        if isinstance(node, ast.Call):
            cname = _call_name(node)
            if cname in _RISKY_CALLS:
                warnings.append(f"uses risky builtin {cname!r}")

    for snip in _RISKY_SNIPPETS:
        if snip in src:
            warnings.append(f"contains dangerous pattern {snip!r}")

    if not func_names:
        errors.append("no function definitions found")

    return StaticReport(
        ok=not errors,
        func_names=func_names,
        tool_funcs=tool_funcs,
        errors=errors,
        warnings=warnings,
    )


def _decorator_name(dec: ast.expr) -> str:
    if isinstance(dec, ast.Name):
        return dec.id
    if isinstance(dec, ast.Attribute):
        return dec.attr
    if isinstance(dec, ast.Call):
        return _decorator_name(dec.func)
    return ""


def _call_name(node: ast.Call) -> str:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""
