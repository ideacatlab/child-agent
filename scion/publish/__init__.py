"""Self-publish: commit + push the agent's own improvements to GitHub.

The mechanism that makes "continuously self-update" safe: stage changes, **hard-
abort if any secret is staged** (ali-fleet-recovery's ``sync.sh`` guard), commit
with a co-author trailer, push. Authored tools, learned skills, and the knowledge
registry become a reviewed, version-controlled, rollback-able trail.
"""

from scion.publish.git_publish import GitPublisher, get_publisher

__all__ = ["GitPublisher", "get_publisher"]
