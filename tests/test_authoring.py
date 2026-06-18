from agent.tools.authoring import list_authored, promote, scaffold, validate

REAL_TOOL = '''\
#!/usr/bin/env python3
"""Add two integers.

Usage: python authored_tools/adder.py A B
"""
import argparse


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("a", type=int)
    p.add_argument("b", type=int)
    args = p.parse_args(argv)
    print(args.a + args.b)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def test_scaffold_stub_is_rejected(settings):
    path = scaffold("demo", "a demo tool")
    assert path.exists()
    res = validate(path)
    assert not res.ok  # still a stub (NotImplementedError / TODO)


def test_validate_and_promote_real_tool(settings, tmp_path):
    # isolate authored_tools/ under the temp root so we don't touch the repo
    settings.root = tmp_path / "repo"
    settings.ensure_dirs()
    draft = settings.drafts_dir / "adder.py"
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text(REAL_TOOL)

    res = validate(draft)
    assert res.ok, res.message

    dest = promote("adder")
    assert dest.exists()
    assert "adder" in [name for name, _ in list_authored()]


def test_validate_rejects_broken(settings):
    bad = settings.drafts_dir / "broken.py"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("def f(:\n    pass\n")
    res = validate(bad)
    assert not res.ok and res.stage == "static"
