"""Shell + Python execution — the broad, code-as-action capability.

These run in a subprocess with timeouts and (on POSIX) resource caps. For real
isolation set ``SCION_SANDBOX_DOCKER_IMAGE`` so commands run inside a container.
"""

from __future__ import annotations

from scion.security.policy import MODERATE
from scion.tools.base import tool
from scion.tools.sandbox import run_command, run_python_snippet


@tool(risk=MODERATE)
def run_shell(command: str, timeout: int = 120) -> str:
    """Run a bash command and return its combined output.

    Use this for git, build/test runners, file wrangling — anything a shell does.
    Output is captured and truncated. Prefer dedicated file tools for plain reads.

    Args:
        command: the bash command line to execute.
        timeout: seconds before the command is killed.
    """
    rc, out = run_command(command, timeout=timeout)
    status = "ok" if rc == 0 else f"exit {rc}"
    return f"[{status}]\n{out}" if out else f"[{status}] (no output)"


@tool(risk=MODERATE)
def run_python(code: str, timeout: int = 60) -> str:
    """Execute a Python snippet in a fresh subprocess; capture stdout/stderr.

    Code-as-action: write a few lines of Python to compute, transform, or glue
    things together. ``print(...)`` what you want back.

    Args:
        code: Python source to run.
        timeout: seconds before it is killed.
    """
    rc, out = run_python_snippet(code, timeout=timeout)
    status = "ok" if rc == 0 else f"exit {rc}"
    return f"[{status}]\n{out}" if out else f"[{status}] (no output)"
