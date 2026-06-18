"""The tool workshop.

In the Claude-Code model a *tool* is a small, self-documenting CLI script in
``authored_tools/`` that the session runs via bash — exactly ali-fleet-recovery's
"every tool is a script with a usage docstring + argparse" convention. Claude Code
writes them itself; this module is the *discipline* around that: scaffold a
template, statically screen + smoke-test it (Voyager's verified-before-persisted),
then promote it into the version-controlled ``authored_tools/`` folder.
"""

from agent.tools.authoring import (
    list_authored,
    list_drafts,
    promote,
    scaffold,
    validate,
)

__all__ = ["scaffold", "validate", "promote", "list_authored", "list_drafts"]
