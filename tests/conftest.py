import pytest

from scion.config import get_settings, reload_settings


@pytest.fixture
def settings(tmp_path, monkeypatch):
    """Isolated settings pointing at a temp workspace."""
    monkeypatch.setenv("SCION_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("SCION_ALLOW_SELF_TOOLING", "1")
    s = reload_settings()
    yield s
    get_settings.cache_clear()
