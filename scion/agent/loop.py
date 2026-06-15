"""The manual agentic loop: LLM ↔ tools ↔ memory ↔ channel."""

from __future__ import annotations

import json
from typing import Callable

from scion.agent.events import EventLog
from scion.agent.prompts import build_system_prompt
from scion.agent.runtime import RuntimeContext, reset_runtime, set_runtime
from scion.agent.session import Session
from scion.config import Settings, get_settings
from scion.llm.base import LLMClient
from scion.llm.registry import get_llm
from scion.logging import get_logger
from scion.memory.store import MemoryStore, get_memory
from scion.security.policy import Decision, RiskPolicy
from scion.security.secrets import get_secret_registry
from scion.skills.loader import SkillLibrary, get_skills
from scion.tools.base import ToolError
from scion.tools.registry import ToolRegistry, get_registry

log = get_logger("agent.loop")


class AgentLoop:
    def __init__(
        self,
        settings: Settings | None = None,
        llm: LLMClient | None = None,
        registry: ToolRegistry | None = None,
        memory: MemoryStore | None = None,
        skills: SkillLibrary | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.llm = llm or get_llm()
        self.registry = registry or get_registry()
        self.memory = memory or get_memory()
        self.skills = skills or get_skills()

    # ------------------------------------------------------------------ #
    def run(
        self,
        user_input: str | list,
        *,
        session: Session | None = None,
        channel=None,
        autonomous: bool | None = None,
        on_text: Callable[[str], None] | None = None,
        task_id: int | None = None,
    ) -> str:
        """Run the agent to completion on *user_input*; return the final text."""
        s = self.settings
        autonomous = s.autonomous if autonomous is None else autonomous
        session = session or Session.new()
        events = EventLog(session.id)

        system = build_system_prompt(
            s, self.memory, self.registry, self.skills, autonomous=autonomous
        )
        can_ask = bool(channel) and getattr(channel, "can_confirm", False)
        policy = RiskPolicy(
            autonomous=autonomous, require_confirmation=s.require_confirmation, can_ask=can_ask
        )
        secrets = get_secret_registry()

        token = set_runtime(RuntimeContext(channel=channel, session_id=session.id, task_id=task_id))
        try:
            session.add_user(user_input)
            events.append("user_message", text=_preview(user_input))
            final_text = ""

            for _ in range(s.max_tool_iterations):
                resp = self.llm.complete(
                    system=system,
                    messages=session.messages,
                    tools=self.registry.anthropic_tools(),
                    stream_cb=on_text,
                    max_tokens=s.max_tokens,
                )
                for b in resp.content:
                    if b.get("type") == "thinking" and b.get("thinking"):
                        events.append("thinking", text=b["thinking"][:4000])
                if resp.text:
                    events.append("assistant_message", text=resp.text, usage=resp.usage)
                    final_text = resp.text
                session.add_assistant(resp.content)

                if resp.stop_reason == "pause_turn":
                    continue  # server-side tool needs another round; resend
                if not resp.tool_uses:
                    break

                results = [
                    self._run_tool(tu, policy, channel, secrets, events)
                    for tu in resp.tool_uses
                ]
                session.add_tool_results(results)
            else:
                events.append("status", text="max_tool_iterations reached")
                final_text = final_text or "(stopped: hit the tool-iteration limit)"

            session.trim()
            session.save()
            return final_text
        except Exception as exc:  # surface, log, and re-raise to the caller
            events.append("error", text=str(exc))
            log.exception("agent loop error")
            raise
        finally:
            reset_runtime(token)

    # ------------------------------------------------------------------ #
    def _run_tool(self, tu: dict, policy: RiskPolicy, channel, secrets, events: EventLog) -> dict:
        name = tu["name"]
        tuid = tu["id"]
        args = tu.get("input", {}) or {}
        tool = self.registry.get(name)
        if tool is None:
            events.append("tool_result", name=name, ok=False, output="unknown tool")
            return _tool_result(tuid, f"Error: no tool named {name!r}.", is_error=True)

        decision = policy.decide(tool.risk)
        if decision is Decision.ASK and channel is not None:
            approved = channel.confirm(_confirm_text(name, args))
            if not approved:
                events.append("tool_denied", name=name)
                return _tool_result(tuid, f"Operator declined to run {name}.", is_error=True)
        elif decision is Decision.DENY:
            events.append("tool_denied", name=name, reason="policy")
            return _tool_result(
                tuid,
                f"Refused: {name} is high-risk and no operator is available to confirm it.",
                is_error=True,
            )

        events.append("tool_use", name=name, input=args)
        is_error = False
        try:
            output = tool.run(args)
        except ToolError as exc:
            output, is_error = f"Error: {exc}", True
        except TypeError as exc:
            output, is_error = f"Bad arguments for {name}: {exc}", True
        except Exception as exc:  # noqa: BLE001 - tools must not crash the loop
            output, is_error = f"Unhandled error in {name}: {exc}", True

        output = secrets.mask(output)[:16000]
        events.append("tool_result", name=name, ok=not is_error, output=output[:800])
        return _tool_result(tuid, output, is_error=is_error)


def _tool_result(tool_use_id: str, content: str, *, is_error: bool = False) -> dict:
    block = {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}
    if is_error:
        block["is_error"] = True
    return block


def _confirm_text(name: str, args: dict) -> str:
    try:
        rendered = json.dumps(args)[:300]
    except (TypeError, ValueError):
        rendered = str(args)[:300]
    return f"Run high-risk tool `{name}`?\nargs: {rendered}"


def _preview(content) -> str:
    if isinstance(content, str):
        return content[:500]
    return f"[{len(content)} block(s)]"
