from __future__ import annotations
import os
import yaml
from datetime import datetime
from pydantic import BaseModel, Field


class TreasuryConfig(BaseModel):
    # Scope & evaluation
    evaluation_policy: str = Field(default="as_of_only")
    as_of_timestamp: str = Field(default="2026-10-17T00:00:00Z")

    # U1: Opening balances & funding
    opening_cash_usd: float = Field(default=3_000_000_000.0)
    opening_customer_deposits_usd: float = Field(default=3_000_000_000.0)
    funding_mode: str = Field(default="none")

    # U2: Timezone
    timezone: str = Field(default="UTC")

    # U3: Operational cash floor
    min_cash_floor_usd: float = Field(default=25_000_000.0)

    # U4: Repo mechanics
    repo_sweep_window_hour: int = Field(default=17)
    repo_sweep_mature_hour: int = Field(default=8)
    repo_tenor_hours: int = Field(default=15)
    repo_min_sweep_usd: float = Field(default=1_000_000.0)
    repo_max_pct_of_portfolio: float = Field(default=70.0)

    # U5: Early repo redemption
    tier1_early_redemption_haircut_pct: float = Field(default=0.5)
    tier1_early_redemption_interest_forfeited: bool = Field(default=True)

    # U6: Bond mechanics
    bond_settlement_lag_hours: int = Field(default=24)
    bond_min_hold_hours: int = Field(default=24)
    bond_max_pct_of_portfolio: float = Field(default=25.0)
    tier2_bond_liquidation_haircut_pct: float = Field(default=2.0)

    # U7: Equity mechanics
    stock_settlement_lag_hours: int = Field(default=48)
    stock_min_hold_hours: int = Field(default=168)
    stock_max_pct_of_portfolio: float = Field(default=0.0)
    stock_expected_annual_return_pct: float = Field(default=0.0)
    tier3_stock_liquidation_haircut_pct: float = Field(default=15.0)

    # U8: Emergency overdraft
    overdraft_limit_usd: float = Field(default=100_000_000.0)
    emergency_overdraft_penalty_apr_pct: float = Field(default=12.0)
    overdraft_arrangement_fee_bps: float = Field(default=0.0)

    # U9: Payout failure semantics
    payout_priority: str = Field(default="FIFO")

    # U10: Intra-step ordering
    transaction_ordering: str = Field(default="inflow_before_outflow")

    # U11: Merchant / deposit credit
    inflow_credit_pct: float = Field(default=0.0)

    # U12: Day count convention
    day_count_convention: str = Field(default="FIXED_365_8760")

    # U14: Stock volatility
    stock_realized_vol_pct: float = Field(default=25.0)

    # U17: Challenge benchmark APY
    challenge_benchmark_apy_pct: float = Field(default=5.00)

    # Reserve calculation parameters
    alpha_quantile: float = Field(default=0.99)
    model_risk_margin_pct: float = Field(default=10.0)
    stress_addon_k: float = Field(default=3.0)
    bootstrap_paths: int = Field(default=2000)
    bootstrap_block_size: int = Field(default=6)

    @classmethod
    def load(cls, config_path: str = "config/treasury.yaml") -> TreasuryConfig:
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls(**data)
