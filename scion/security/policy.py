"""Risk scoring + confirmation policy.

Every tool carries a coarse risk level. Before a call with side effects runs,
the policy returns one of ``allow`` / ``ask`` / ``deny``. ``ask`` pauses the loop
for a human decision over the active channel (Telegram, CLI). This is the cheap,
legible half of the OpenHands ``SecurityAnalyzer`` + ``ConfirmationPolicy`` idea.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# risk levels (also referenced by scion.tools.base)
SAFE = "safe"
MODERATE = "moderate"
DANGEROUS = "dangerous"
RISK_LEVELS = (SAFE, MODERATE, DANGEROUS)


class Decision(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass
class RiskPolicy:
    """Maps (tool risk, settings) -> Decision.

    * ``autonomous`` worker with ``require_confirmation`` off: everything runs.
    * Interactive / confirmation-on: DANGEROUS tools ask; MODERATE runs; SAFE runs.
    * A channel that cannot ask (no interactive surface) downgrades ASK->DENY for
      DANGEROUS tools unless explicitly autonomous.
    """

    autonomous: bool = False
    require_confirmation: bool = True
    can_ask: bool = True

    def decide(self, risk: str) -> Decision:
        if risk == SAFE:
            return Decision.ALLOW
        if risk == MODERATE:
            # Moderate side effects run automatically; they're reversible/loggable.
            return Decision.ALLOW
        # DANGEROUS
        if self.autonomous and not self.require_confirmation:
            return Decision.ALLOW
        if not self.require_confirmation:
            return Decision.ALLOW
        if self.can_ask:
            return Decision.ASK
        # No human to ask and confirmation required -> refuse the dangerous action.
        return Decision.DENY
