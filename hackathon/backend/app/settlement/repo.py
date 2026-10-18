from __future__ import annotations
import math
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class RepoPosition(BaseModel):
    position_id: str
    opened_step: int
    opened_ts: str
    principal_cents: int
    rate_apy_pct: float
    maturity_step: int
    haircut_pct: float = 0.5
    status: str = "OPEN"  # 'OPEN', 'MATURED', 'EARLY_REDEEMED'

    def calculate_interest(self, hours_held: int) -> int:
        """Calculates integer cents interest using FIXED_365_8760 convention."""
        # floor_cents(principal_cents * rate * hours / 8760)
        rate = self.rate_apy_pct / 100.0
        interest = math.floor(self.principal_cents * rate * hours_held / 8760.0)
        return int(interest)

    def calculate_early_redemption(self) -> Dict[str, int]:
        """Calculates haircut and net proceeds for early redemption. Interest is forfeited."""
        haircut = math.floor(self.principal_cents * (self.haircut_pct / 100.0))
        net_proceeds = self.principal_cents - haircut
        return {
            "principal_cents": self.principal_cents,
            "haircut_cents": int(haircut),
            "net_proceeds_cents": int(net_proceeds),
        }
