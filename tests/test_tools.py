from typing import Optional

from scion.tools.base import Tool, build_schema, tool
from scion.tools.registry import ToolRegistry


def test_build_schema_from_signature():
    def f(name: str, count: int = 3, ratio: float = 1.0, on: bool = False, tags: Optional[list] = None) -> str:
        """Do a thing.

        Args:
            name: the name.
            count: how many.
        """
        return name

    schema, desc = build_schema(f)
    assert desc == "Do a thing."
    props = schema["properties"]
    assert props["name"]["type"] == "string"
    assert "the name" in props["name"]["description"]
    assert props["count"]["type"] == "integer"
    assert props["ratio"]["type"] == "number"
    assert props["on"]["type"] == "boolean"
    assert schema["required"] == ["name"]  # only the no-default arg


def test_tool_decorator_and_run():
    @tool(risk="safe")
    def add(a: int, b: int) -> str:
        "Add two ints."
        return a + b

    t = add._scion_tool
    assert isinstance(t, Tool)
    assert t.name == "add"
    assert t.run({"a": 2, "b": 3}) == "5"  # non-str coerced
    assert t.to_anthropic()["input_schema"]["properties"]["a"]["type"] == "integer"


def test_registry_discovers_builtins(settings):
    reg = ToolRegistry()
    n = reg.discover_package("scion.tools.builtins")
    assert n > 10
    assert "read_file" in reg
    assert "author_tool" in reg
    assert "rag_search" in reg
    defs = reg.anthropic_tools()
    assert all("input_schema" in d for d in defs)


def test_registry_hot_load(settings, tmp_path):
    mod = tmp_path / "mytool.py"
    mod.write_text(
        "from scion.tools.base import tool\n"
        "@tool(risk='safe')\n"
        "def shout(text: str) -> str:\n"
        "    'Uppercase text.'\n"
        "    return text.upper()\n"
    )
    reg = ToolRegistry()
    found = reg.load_path(mod)
    assert found and found[0].name == "shout"
    assert reg.get("shout").run({"text": "hi"}) == "HI"
