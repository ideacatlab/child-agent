from scion.tools.authoring import author_tool_pipeline, build_module
from scion.tools.sandbox import run_python_snippet, static_check_source

GOOD = (
    "def slugify(text: str) -> str:\n"
    '    "Turn text into a url slug."\n'
    "    import re\n"
    '    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")\n'
)


def test_static_check_pass_and_fail():
    ok = static_check_source(GOOD)
    assert ok.ok and "slugify" in ok.func_names
    bad = static_check_source("def broken(:\n    pass")
    assert not bad.ok and bad.errors


def test_build_module_decorates():
    mod = build_module("slugify", GOOD, "safe")
    assert "from scion.tools.base import tool" in mod
    assert 'tool(name="slugify"' in mod


def test_sandbox_runs_python():
    rc, out = run_python_snippet("print(6*7)")
    assert rc == 0 and "42" in out


def test_author_pipeline_pending(settings):
    res = author_tool_pipeline(
        "slugify",
        "make a url slug",
        GOOD,
        test_code='assert slugify("Hello World!") == "hello-world"',
        risk="safe",
        autoapply=False,
    )
    assert res.ok, res.message
    assert res.stage == "pending"
    assert res.tool_name == "slugify"
    assert (settings.drafts_dir / "slugify.py").exists()


def test_author_pipeline_rejects_bad(settings):
    res = author_tool_pipeline("oops", "bad", "def f(:\n pass", autoapply=False)
    assert not res.ok and res.stage == "static"


def test_author_pipeline_failing_test(settings):
    res = author_tool_pipeline(
        "adder",
        "adds",
        "def adder(a: int, b: int) -> int:\n    'add'\n    return a + b\n",
        test_code="assert adder(1, 1) == 3",  # wrong on purpose
        autoapply=False,
    )
    assert not res.ok and res.stage == "test"
