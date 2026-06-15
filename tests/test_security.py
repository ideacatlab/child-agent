from scion.security.policy import DANGEROUS, MODERATE, SAFE, Decision, RiskPolicy
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


def test_policy_decisions():
    interactive = RiskPolicy(autonomous=False, require_confirmation=True, can_ask=True)
    assert interactive.decide(SAFE) is Decision.ALLOW
    assert interactive.decide(MODERATE) is Decision.ALLOW
    assert interactive.decide(DANGEROUS) is Decision.ASK

    headless = RiskPolicy(autonomous=True, require_confirmation=True, can_ask=False)
    assert headless.decide(DANGEROUS) is Decision.DENY

    trusting = RiskPolicy(autonomous=True, require_confirmation=False, can_ask=False)
    assert trusting.decide(DANGEROUS) is Decision.ALLOW
