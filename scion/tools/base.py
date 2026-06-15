"""The ``Tool`` object + ``@tool`` decorator + schema-from-signature.

Write a plain Python function with type hints and a docstring; ``@tool`` turns it
into a fully-described tool the model can call. No hand-written JSON schemas.

    @tool(risk="safe")
    def add(a: int, b: int) -> str:
        '''Add two integers.

        Args:
            a: first addend.
            b: second addend.
        '''
        return str(a + b)
"""

from __future__ import annotations

import inspect
import json
import typing
from dataclasses import dataclass, field
from typing import Any, Callable, get_args, get_origin

from scion.security.policy import MODERATE, RISK_LEVELS


class ToolError(Exception):
    """Raised by a tool to signal a clean, model-visible failure."""


# --------------------------------------------------------------------------- #
# type -> JSON schema
# --------------------------------------------------------------------------- #
_PRIMITIVES = {
    str: {"type": "string"},
    int: {"type": "integer"},
    float: {"type": "number"},
    bool: {"type": "boolean"},
    dict: {"type": "object"},
    list: {"type": "array"},
    type(None): {"type": "null"},
    inspect.Parameter.empty: {"type": "string"},
    Any: {"type": "string"},
}


def _schema_for(annotation: Any) -> dict:
    """Best-effort JSON-schema fragment for a Python type annotation."""
    if annotation in _PRIMITIVES:
        return dict(_PRIMITIVES[annotation])

    origin = get_origin(annotation)
    args = get_args(annotation)

    # Optional[X] / Union[...]
    if origin is typing.Union:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return _schema_for(non_none[0])  # Optional[X] -> schema of X
        return {"anyOf": [_schema_for(a) for a in non_none]}

    # Literal[...] -> enum
    if origin is typing.Literal:
        return {"type": "string", "enum": [str(a) for a in args]}

    if origin in (list, typing.List, set, frozenset, tuple):
        item = _schema_for(args[0]) if args else {"type": "string"}
        return {"type": "array", "items": item}

    if origin in (dict, typing.Dict):
        return {"type": "object"}

    # fall back to string for unknown/complex annotations
    return {"type": "string"}


def _parse_docstring(doc: str | None) -> tuple[str, dict[str, str]]:
    """Split a Google-style docstring into (summary, {param: description})."""
    if not doc:
        return "", {}
    lines = inspect.cleandoc(doc).splitlines()
    summary_lines: list[str] = []
    params: dict[str, str] = {}
    in_args = False
    current: str | None = None
    for line in lines:
        stripped = line.strip()
        low = stripped.lower()
        if low in ("args:", "arguments:", "parameters:", "params:"):
            in_args = True
            continue
        if in_args and low in ("returns:", "return:", "raises:", "yields:", "examples:", "example:"):
            in_args = False
            current = None
            continue
        if in_args and stripped:
            if ":" in stripped and not line.startswith((" " * 8, "\t\t")):
                name, _, desc = stripped.partition(":")
                current = name.strip().lstrip("*")
                params[current] = desc.strip()
            elif current:
                params[current] += " " + stripped
        elif not in_args:
            summary_lines.append(stripped)
    summary = " ".join(s for s in summary_lines if s).strip()
    return summary, params


def build_schema(func: Callable) -> tuple[dict, str]:
    """Return ``(input_schema, description)`` derived from *func*."""
    sig = inspect.signature(func)
    try:
        hints = typing.get_type_hints(func)
    except Exception:
        hints = getattr(func, "__annotations__", {})
    summary, param_docs = _parse_docstring(func.__doc__)

    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        frag = _schema_for(hints.get(name, param.annotation))
        if name in param_docs:
            frag["description"] = param_docs[name]
        properties[name] = frag
        if param.default is inspect.Parameter.empty:
            required.append(name)

    schema = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    schema["additionalProperties"] = False
    return schema, (summary or (func.__doc__ or func.__name__).strip())


# --------------------------------------------------------------------------- #
# Tool object
# --------------------------------------------------------------------------- #
@dataclass
class Tool:
    name: str
    description: str
    func: Callable[..., Any]
    schema: dict
    risk: str = MODERATE
    source: str = "builtin"  # builtin | authored | skill | mcp
    parallel_safe: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)

    def to_anthropic(self) -> dict:
        """Render as an Anthropic tool definition."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.schema,
        }

    def run(self, arguments: dict | None = None) -> str:
        """Execute the tool, coercing the result to a string for the model."""
        arguments = arguments or {}
        result = self.func(**arguments)
        if isinstance(result, str):
            return result
        if result is None:
            return "(no output)"
        try:
            return json.dumps(result, indent=2, default=str)
        except (TypeError, ValueError):
            return str(result)


def tool(
    _func: Callable | None = None,
    *,
    name: str | None = None,
    risk: str = MODERATE,
    source: str = "builtin",
    parallel_safe: bool = False,
    tags: tuple[str, ...] = (),
) -> Callable:
    """Decorator that turns a function into a :class:`Tool` and attaches it as
    ``func._scion_tool``. The registry discovers anything carrying that marker.
    """
    if risk not in RISK_LEVELS:
        raise ValueError(f"risk must be one of {RISK_LEVELS}, got {risk!r}")

    def wrap(func: Callable) -> Callable:
        schema, description = build_schema(func)
        t = Tool(
            name=name or func.__name__,
            description=description,
            func=func,
            schema=schema,
            risk=risk,
            source=source,
            parallel_safe=parallel_safe,
            tags=tags,
        )
        func._scion_tool = t  # type: ignore[attr-defined]
        return func

    return wrap(_func) if _func is not None else wrap
