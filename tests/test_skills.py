from agent.skills.loader import SkillLibrary, _split_frontmatter


def test_frontmatter_parse():
    meta, body = _split_frontmatter("---\nname: foo\ndescription: does foo\n---\n\nbody here")
    assert meta["name"] == "foo"
    assert meta["description"] == "does foo"
    assert body.strip() == "body here"


def test_skill_library(tmp_path):
    d = tmp_path / "research"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: research\ndescription: research a topic\n---\n\nDo the research.")
    lib = SkillLibrary([tmp_path])
    assert "research" in lib.index()
    sk = lib.get("research")
    assert sk and "Do the research." in sk.body()
