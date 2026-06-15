"""The tool system.

A *tool* is the unit of capability and the unit of registration. One
self-describing object bundles the callable, its JSON schema (derived from the
function signature + docstring), a coarse risk level, and provenance. New
capability arrives by *dropping in a tool* — including tools the agent writes for
itself at runtime (see :mod:`scion.tools.builtins.tool_author`).

Design lineage: gptme's single ``ToolSpec`` dataclass, smolagents' schema-from-
signature, Hermes' import-time self-registering registry, OpenHands' typed tool
contract resolved by a runtime registry.
"""

from scion.tools.base import Tool, ToolError, tool
from scion.tools.registry import ToolRegistry, get_registry

__all__ = ["Tool", "ToolError", "tool", "ToolRegistry", "get_registry"]
