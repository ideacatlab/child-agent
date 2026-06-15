"""Self-publish tool: commit + push the agent's improvements to GitHub."""

from __future__ import annotations

from scion.security.policy import DANGEROUS, SAFE
from scion.tools.base import tool
from scion.publish.git_publish import get_publisher


@tool(risk=DANGEROUS)
def publish_changes(message: str) -> str:
    """Commit the working tree and push it to the configured GitHub remote.

    Outward-facing and hard to reverse, so this is high-risk and may require
    operator confirmation. Secrets are guarded — the commit aborts if any
    secret-like file or value is staged.

    Args:
        message: the commit message describing what changed and why.
    """
    return get_publisher().publish(message)


@tool(risk=SAFE, parallel_safe=True)
def git_status() -> str:
    """Show the working-tree status (porcelain)."""
    out = get_publisher().status()
    return out or "(clean working tree)"
