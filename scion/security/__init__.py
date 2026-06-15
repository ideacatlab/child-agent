"""Security layer: secret masking + a risk/confirmation policy.

Two cross-cutting concerns, kept deliberately small and legible (OpenHands-style
``SecretRegistry`` + ``SecurityAnalyzer``/``ConfirmationPolicy``):

* :mod:`scion.security.secrets` injects/masks credentials so they never leak
  into logs, the transcript, or tool output the model sees.
* :mod:`scion.security.policy` scores each tool call and decides
  allow / ask / deny before anything with side effects runs.
"""

from scion.security.policy import Decision, RiskPolicy
from scion.security.secrets import SecretRegistry, get_secret_registry

__all__ = ["Decision", "RiskPolicy", "SecretRegistry", "get_secret_registry"]
