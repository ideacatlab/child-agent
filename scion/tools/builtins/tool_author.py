"""The self-improvement tool: the agent writes, validates, and registers a new
tool for itself at runtime."""

from __future__ import annotations

import json

from scion.security.policy import MODERATE, SAFE
from scion.tools.authoring import author_tool_pipeline, list_drafts
from scion.tools.base import tool
from scion.tools.registry import get_registry


@tool(risk=MODERATE)
def author_tool(
    name: str,
    description: str,
    code: str,
    test_code: str = "",
    risk: str = "moderate",
) -> str:
    """Write a brand-new tool for yourself and register it after validation.

    Provide a small, self-contained Python function with **type hints and a
    docstring** (the docstring becomes the tool's description and the args its
    schema). It is statically screened, self-tested in the sandbox, then either
    registered live (if auto-apply is on) or held as a draft for approval.

    Strongly include ``test_code`` that calls the function and ``assert``s on the
    result — a tool that hasn't been shown to work is not persisted.

    Args:
        name: snake_case tool name (also the function name is fine).
        description: one-line summary of what the tool does.
        code: the function source, e.g. ``def slugify(text: str) -> str: ...``.
        test_code: optional Python that calls the function and asserts results.
        risk: safe | moderate | dangerous — be honest about side effects.
    """
    result = author_tool_pipeline(
        name, description, code, test_code=test_code, risk=risk
    )
    return result.render()


@tool(risk=SAFE, parallel_safe=True)
def list_authored_tools() -> str:
    """List tools the agent has authored (live + pending drafts)."""
    reg = get_registry()
    authored = [t.name for t in reg.all() if t.source == "authored"]
    drafts = [d for d in list_drafts() if d not in authored]
    return json.dumps(
        {"live_authored": authored, "pending_drafts": drafts, "total_tools": len(reg)}, indent=2
    )


@tool(risk=SAFE, parallel_safe=True)
def inspect_tool(name: str) -> str:
    """Show a tool's description, risk, source, and input schema.

    Args:
        name: the tool to inspect.
    """
    t = get_registry().get(name)
    if t is None:
        return f"no such tool: {name}"
    return json.dumps(
        {
            "name": t.name,
            "risk": t.risk,
            "source": t.source,
            "description": t.description,
            "input_schema": t.schema,
        },
        indent=2,
    )
