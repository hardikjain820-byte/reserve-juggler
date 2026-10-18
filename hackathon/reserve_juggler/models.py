"""Data models, schemas, and enums for Reserve Juggler."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class LedgerAccount(str, Enum):
    # Assets
    CASH_BUFFER = "1010_CASH_BUFFER"
    YIELD_VAULT = "1020_YIELD_VAULT"
    ACCRUED_YIELD_RECEIVABLE = "1030_ACCRUED_YIELD_RECEIVABLE"
    
    # Liabilities
    CUSTOMER_DEPOSITS = "2010_CUSTOMER_DEPOSITS"
    EMERGENCY_OVERDRAFT_LOAN = "2020_EMERGENCY_OVERDRAFT_LOAN"
    
    # Equity
    INITIAL_EQUITY = "3010_INITIAL_EQUITY"
    
    # Income & Expense
    YIELD_INCOME = "4010_YIELD_INCOME"
    EARLY_WITHDRAWAL_PENALTY_EXPENSE = "5010_EARLY_WITHDRAWAL_PENALTY_EXPENSE"
    LOAN_INTEREST_EXPENSE = "5020_LOAN_INTEREST_EXPENSE"
    LOAN_FEE_EXPENSE = "5030_LOAN_FEE_EXPENSE"


class EngineMode(str, Enum):
    NORMAL = "NORMAL"
    PAUSED = "PAUSED"
    FAILSAFE = "FAILSAFE"
    KILLED = "KILLED"


@dataclass
class JournalEntry:
    entry_id: str
    timestamp: datetime
    description: str
    debits: Dict[LedgerAccount, int]  # Account -> Amount in integer cents
    credits: Dict[LedgerAccount, int]  # Account -> Amount in integer cents

    def validate(self) -> None:
        total_debits = sum(self.debits.values())
        total_credits = sum(self.credits.values())
        if total_debits != total_credits:
            raise ValueError(
                f"Double-entry violation in entry {self.entry_id}: "
                f"Debits={total_debits} cents != Credits={total_credits} cents"
            )


@dataclass
class VaultTranche:
    tranche_id: str
    principal_cents: int
    start_bucket: int
    mature_bucket: int
    accrued_yield_cents: int = 0
    status: str = "ACTIVE"  # ACTIVE, MATURED, BROKEN_EARLY


@dataclass
class FlowBucket:
    bucket_index: int
    timestamp: datetime
    inflow_cents: int
    outflow_cents: int
    scheduled_type: Optional[str] = None
    is_shock: bool = False

    @property
    def net_cents(self) -> int:
        return self.inflow_cents - self.outflow_cents


@dataclass
class ForecastHorizonStep:
    step: int  # 1 to 96
    bucket_index: int
    inflow_p50: int
    inflow_p95: int
    inflow_p99: int
    inflow_p999: int
    outflow_p50: int
    outflow_p95: int
    outflow_p99: int
    outflow_p999: int
    is_scheduled_override: bool = False


@dataclass
class AuditRecord:
    cycle_index: int
    timestamp: str
    cash_before_cents: int
    vault_before_cents: int
    forecast_p999_max_deficit_cents: int
    required_cushion_cents: int
    headroom_cents: int
    decision: str  # SWEEP, HOLD, FAILSAFE_HOLD, KILLED, MANUAL_SWEEP, EMERGENCY_RELEASE
    sweep_amount_cents: int
    reason: str
    prev_hash: str
    record_hash: str


# Pydantic schemas for REST API & WebSocket / UI
class TelemetryDTO(BaseModel):
    cycle_index: int
    timestamp: str
    mode: str
    cash_buffer_usd: float
    yield_vault_usd: float
    required_cushion_usd: float
    headroom_usd: float
    current_wape: float
    emergency_draws: int
    emergency_loan_balance_usd: float
    early_withdrawal_penalties_usd: float
    net_yield_earned_usd: float
    baseline_yield_earned_usd: float
    yield_alpha_usd: float
    payout_success_rate: float
    last_inflow_usd: float
    last_outflow_usd: float
    recent_audit: List[dict] = Field(default_factory=list)
    forecast_fan: List[dict] = Field(default_factory=list)


class ControlActionRequest(BaseModel):
    action: str  # pause, resume, kill, reset_kill, manual_sweep, set_buffer_addon
    amount_usd: Optional[float] = None
