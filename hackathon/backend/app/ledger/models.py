from __future__ import annotations
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
import hashlib
import json


class AccountType(str, Enum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"


ACCOUNT_TYPES: Dict[str, AccountType] = {
    # Assets
    "CASH": AccountType.ASSET,
    "REPO": AccountType.ASSET,
    "BOND": AccountType.ASSET,
    "STOCK": AccountType.ASSET,
    "BOND_ACCRUED_INTEREST": AccountType.ASSET,
    # Liabilities
    "CUSTOMER_DEPOSITS": AccountType.LIABILITY,
    "OVERDRAFT": AccountType.LIABILITY,
    "PAYOUT_QUEUE": AccountType.LIABILITY,
    # Equity
    "CAPITAL": AccountType.EQUITY,
    # Income
    "REPO_INTEREST": AccountType.INCOME,
    "BOND_CARRY": AccountType.INCOME,
    "MTM_GAIN": AccountType.INCOME,
    "EXTERNAL_FUNDING": AccountType.INCOME,
    # Expense
    "MTM_LOSS": AccountType.EXPENSE,
    "EARLY_REDEMPTION_COST": AccountType.EXPENSE,
    "BOND_LIQUIDATION_COST": AccountType.EXPENSE,
    "STOCK_LIQUIDATION_COST": AccountType.EXPENSE,
    "OD_INTEREST": AccountType.EXPENSE,
}


class LedgerEntry(BaseModel):
    account: str
    debit_cents: int = Field(ge=0, default=0)
    credit_cents: int = Field(ge=0, default=0)

    def model_post_init(self, __context):
        if (self.debit_cents == 0 and self.credit_cents == 0) or (
            self.debit_cents > 0 and self.credit_cents > 0
        ):
            raise ValueError(
                f"Entry must have exactly one positive side: debit={self.debit_cents}, credit={self.credit_cents}"
            )
        if self.account not in ACCOUNT_TYPES:
            raise ValueError(f"Unknown account: {self.account}")


class LedgerTxn(BaseModel):
    txn_id: str
    run_id: str
    step_index: int
    kind: str
    timestamp: str
    entries: List[LedgerEntry]
    memo: str = ""

    def validate_balanced(self) -> None:
        total_debit = sum(e.debit_cents for e in self.entries)
        total_credit = sum(e.credit_cents for e in self.entries)
        if total_debit != total_credit:
            raise ValueError(
                f"Unbalanced transaction {self.txn_id} ({self.kind}): total_debit={total_debit} != total_credit={total_credit}"
            )


def generate_txn_id(run_id: str, step_index: int, kind: str, seq: int) -> str:
    raw = f"{run_id}|{step_index}|{kind}|{seq}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
