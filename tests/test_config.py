from scion.config import load_env, set_env_var


def test_settings_paths(settings):
    assert settings.workspace.name == "ws"
    assert settings.queue_db.parent == settings.workspace
    assert settings.authored_tools_dir.name == "authored_tools"
    assert settings.model  # non-empty default


def test_env_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    set_env_var("FOO_BAR", "123", root=tmp_path)
    import os

    assert os.environ["FOO_BAR"] == "123"
    # update existing key in place
    set_env_var("FOO_BAR", "456", root=tmp_path)
    text = (tmp_path / ".env").read_text()
    assert "FOO_BAR=456" in text and "FOO_BAR=123" not in text


def test_load_env_setdefault(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("ALREADY=fromenv\nNEWKEY=fromfile\n")
    monkeypatch.setenv("ALREADY", "real")
    load_env(tmp_path)
    import os

    assert os.environ["ALREADY"] == "real"  # env wins
    assert os.environ["NEWKEY"] == "fromfile"
