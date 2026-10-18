"""Unified Configuration for Reserve Juggler.

All rates, thresholds, horizons, and confidence levels are consolidated here.
"""

from dataclasses import dataclass
from typing import Final


def to_cents(usd: float) -> int:
    """Convert USD amount to integer minor units (cents)."""
    return int(round(usd * 100))


def to_usd(cents: int) -> float:
    """Convert integer minor units (cents) to USD amount."""
    return round(cents / 100.0, 2)


@dataclass(frozen=True)
class TreasuryConfig:
    # Time bucket parameters
    BUCKET_MINUTES: int = 15
    BUCKETS_PER_HOUR: int = 4
    BUCKETS_PER_DAY: int = 96
    FORECAST_HORIZON_BUCKETS: int = 20  # Matched to intraday rolling tranche horizon (5 hours)

    # Volume and Scale: ~$20,000,000 / hour gross (~$2.5M in + $2.5M out per 15-min bucket)
    GROSS_HOURLY_VOLUME_USD: float = 20_000_000.0
    BASE_BUCKET_VOLUME_USD: float = 2_500_000.0

    # Yield Vault & Penalties
    VAULT_APY: float = 0.05  # 5% annual return
    VAULT_EARLY_WITHDRAWAL_PENALTY_RATE: float = 0.02  # 2% early withdrawal penalty
    VAULT_TRANCHE_HORIZON_BUCKETS: int = 20  # 5h rolling tranches matched to forecast horizon

    # Emergency Overdraft Credit Facility
    EMERGENCY_LOAN_APR: float = 0.18  # 18% APR
    EMERGENCY_LOAN_FLAT_FEE_USD: float = 500.0

    # Risk & Cushion Parameters
    CONFIDENCE_QUANTILE: float = 0.999  # Q_99.9%
    TREASURY_FLOOR_USD: float = 1_000_000.0  # Hard floor, no model output goes below this
    STRESS_ADDON_USD: float = 500_000.0  # Stress add-on for extreme shocks
    SAFETY_MARGIN_USD: float = 100_000.0  # Buffer above required cushion before sweeping
    MIN_SWEEP_AMOUNT_USD: float = 50_000.0  # Minimum sweep size to avoid micro-sweeps

    # WAPE Accuracy Thresholds & Auto-Widening
    TARGET_WAPE_NORMAL: float = 0.10  # 10%
    TARGET_WAPE_PEAK: float = 0.15  # 15% on peak days
    WAPE_EXPANSION_FACTOR: float = 2.0  # Cushion expansion multiplier when error spikes

    # Static Baseline Comparison
    STATIC_BASELINE_BUFFER_USD: float = 15_000_000.0  # Fixed $15M buffer

    # Fail-Safe Parameters
    STALE_DATA_TIMEOUT_MINUTES: float = 30.0  # 2 buckets missing -> fail safe

    # Initial Balances for Simulation: $15M cash + $250M vault
    INITIAL_CASH_BUFFER_USD: float = 15_000_000.0
    INITIAL_VAULT_USD: float = 250_000_000.0

    @property
    def treasury_floor_cents(self) -> int:
        return to_cents(self.TREASURY_FLOOR_USD)

    @property
    def stress_addon_cents(self) -> int:
        return to_cents(self.STRESS_ADDON_USD)

    @property
    def safety_margin_cents(self) -> int:
        return to_cents(self.SAFETY_MARGIN_USD)

    @property
    def min_sweep_cents(self) -> int:
        return to_cents(self.MIN_SWEEP_AMOUNT_USD)

    @property
    def emergency_loan_flat_fee_cents(self) -> int:
        return to_cents(self.EMERGENCY_LOAN_FLAT_FEE_USD)

    @property
    def static_baseline_buffer_cents(self) -> int:
        return to_cents(self.STATIC_BASELINE_BUFFER_USD)

    @property
    def initial_cash_cents(self) -> int:
        return to_cents(self.INITIAL_CASH_BUFFER_USD)

    @property
    def initial_vault_cents(self) -> int:
        return to_cents(self.INITIAL_VAULT_USD)

    @property
    def bucket_rate_vault(self) -> float:
        """Yield vault rate per 15-minute bucket: (1 + APY)^(1/(365*96)) - 1"""
        return (1.0 + self.VAULT_APY) ** (1.0 / (365.0 * self.BUCKETS_PER_DAY)) - 1.0

    @property
    def bucket_rate_emergency_loan(self) -> float:
        """Emergency overdraft rate per 15-minute bucket: APR / (365*96)"""
        return self.EMERGENCY_LOAN_APR / (365.0 * self.BUCKETS_PER_DAY)


CONFIG: Final[TreasuryConfig] = TreasuryConfig()
