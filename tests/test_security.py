from scion.security.secrets import SecretRegistry, looks_like_secret


def test_secret_masking(monkeypatch):
    monkeypatch.setenv("MY_API_KEY", "supersecretvalue123")
    reg = SecretRegistry()
    masked = reg.mask("the key is supersecretvalue123 ok")
    assert "supersecretvalue123" not in masked
    assert "<secret:MY_API_KEY>" in masked


def test_looks_like_secret():
    assert looks_like_secret("ghp_" + "a" * 36)
    assert looks_like_secret("sk-" + "x" * 40)
    assert not looks_like_secret("just some normal text")
