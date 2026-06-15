"""The agent: the loop that turns a request into actions.

A manual agentic loop (not the SDK's auto tool-runner) because scion needs three
things the auto-runner doesn't give: tools that **hot-load mid-session**, risky
tools **gated behind human confirmation**, and an **append-only event log** for
replay and recovery. The loop is the one place that orchestrates LLM ↔ tools ↔
memory ↔ channel.
"""

from scion.agent.loop import AgentLoop
from scion.agent.session import Session

__all__ = ["AgentLoop", "Session"]
