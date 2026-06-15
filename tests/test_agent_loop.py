from scion.agent.loop import AgentLoop
from scion.agent.session import Session
from scion.llm.base import LLMResponse
from scion.memory.store import MemoryStore
from scion.skills.loader import SkillLibrary
from scion.tools.base import build_schema
from scion.tools.base import Tool
from scion.tools.registry import ToolRegistry


class FakeLLM:
    """Returns a tool_use on the first turn, then ends the turn."""

    def __init__(self):
        self.calls = 0
        self.seen_systems = []

    def complete(self, *, system, messages, tools=None, stream_cb=None, max_tokens=None):
        self.calls += 1
        self.seen_systems.append(system)
        if self.calls == 1:
            content = [{"type": "tool_use", "id": "t1", "name": "echo", "input": {"text": "hi"}}]
            return LLMResponse(
                text="", content=content,
                tool_uses=[{"id": "t1", "name": "echo", "input": {"text": "hi"}}],
                stop_reason="tool_use",
            )
        if stream_cb:
            stream_cb("done")
        return LLMResponse(text="done", content=[{"type": "text", "text": "done"}],
                           tool_uses=[], stop_reason="end_turn")

    def simple(self, prompt, *, system=None, max_tokens=1024):
        return "ok"


def _echo_tool(captured):
    def echo(text: str) -> str:
        "Echo the text back."
        captured.append(text)
        return "echoed:" + text

    schema, desc = build_schema(echo)
    return Tool(name="echo", description=desc, func=echo, schema=schema, risk="safe")


def test_agent_loop_executes_tool(settings):
    captured: list[str] = []
    reg = ToolRegistry()
    reg.register(_echo_tool(captured))
    fake = FakeLLM()
    loop = AgentLoop(
        settings=settings,
        llm=fake,
        registry=reg,
        memory=MemoryStore(settings),
        skills=SkillLibrary([]),
    )
    final = loop.run("please echo hi", session=Session.new("test"), autonomous=True)
    assert final == "done"
    assert captured == ["hi"]
    assert fake.calls == 2
    # the system prompt advertised the tool and the constitution
    assert "echo" in fake.seen_systems[0]
    assert "OPERATING PRINCIPLES" in fake.seen_systems[0]
