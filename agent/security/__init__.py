"""Security helpers: secret masking + a leak detector.

Used to keep credentials out of anything published or logged, and to back the
self-publish secret-staging guard.
"""

from agent.security.secrets import SecretRegistry, get_secret_registry, looks_like_secret

__all__ = ["SecretRegistry", "get_secret_registry", "looks_like_secret"]
