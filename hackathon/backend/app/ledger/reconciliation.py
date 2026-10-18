from __future__ import annotations
from typing import Dict, List
from backend.app.ledger.models import AccountType, ACCOUNT_TYPES, LedgerTxn, LedgerEntry


class ReconciliationError(Exception):
    pass


class LiabilityLimitExceededError(ReconciliationError):
    pass


class GeneralLedger:
    def __init__(self, run_id: str):
        self.run_id = run_id
        # Balances stored with natural signs:
        # ASSETS: debit > credit => positive
        # LIABILITIES: credit > debit => positive
        # EQUITY: credit > debit => positive
        # INCOME: credit > debit => positive
        # EXPENSE: debit > credit => positive
        self.balances: Dict[str, int] = {acc: 0 for acc in ACCOUNT_TYPES}
        self.total_debits_posted: int = 0
        self.total_credits_posted: int = 0
        self.transactions: List[LedgerTxn] = []

    def get_balance(self, account: str) -> int:
        if account not in self.balances:
            raise ValueError(f"Unknown account: {account}")
        return self.balances[account]

    def post_transaction(self, txn: LedgerTxn) -> None:
        txn.validate_balanced()
        for entry in txn.entries:
            acc_type = ACCOUNT_TYPES[entry.account]
            if acc_type == AccountType.ASSET or acc_type == AccountType.EXPENSE:
                self.balances[entry.account] += (entry.debit_cents - entry.credit_cents)
            else:  # LIABILITY, EQUITY, INCOME
                self.balances[entry.account] += (entry.credit_cents - entry.debit_cents)

            self.total_debits_posted += entry.debit_cents
            self.total_credits_posted += entry.credit_cents

        self.transactions.append(txn)

    def reconcile(self) -> Dict[str, int]:
        # Invariant 1: Trial Balance (cumulative debits == cumulative credits)
        if self.total_debits_posted != self.total_credits_posted:
            raise ReconciliationError(
                f"Trial balance failure: total debits {self.total_debits_posted} != total credits {self.total_credits_posted}"
            )

        # Invariant 2: Balance Sheet
        total_assets = sum(
            self.balances[acc]
            for acc, t in ACCOUNT_TYPES.items()
            if t == AccountType.ASSET
        )
        total_liabilities = sum(
            self.balances[acc]
            for acc, t in ACCOUNT_TYPES.items()
            if t == AccountType.LIABILITY
        )
        total_equity = sum(
            self.balances[acc]
            for acc, t in ACCOUNT_TYPES.items()
            if t == AccountType.EQUITY
        )
        total_income = sum(
            self.balances[acc]
            for acc, t in ACCOUNT_TYPES.items()
            if t == AccountType.INCOME
        )
        total_expenses = sum(
            self.balances[acc]
            for acc, t in ACCOUNT_TYPES.items()
            if t == AccountType.EXPENSE
        )

        net_pnl = total_income - total_expenses
        total_liabilities_equity = total_liabilities + total_equity + net_pnl

        if total_assets != total_liabilities_equity:
            raise ReconciliationError(
                f"Balance sheet failure: Assets ({total_assets}) != Liabilities+Equity+P&L ({total_liabilities_equity}). "
                f"Diff: {total_assets - total_liabilities_equity}"
            )

        # Invariant 3: Cash cannot be negative
        if self.balances["CASH"] < 0:
            raise ReconciliationError(f"Negative cash balance: {self.balances['CASH']}")

        # Invariant 4: Customer deposits liability limit
        if self.balances["CUSTOMER_DEPOSITS"] < 0:
            raise LiabilityLimitExceededError(
                f"Customer deposit liability exhausted: {self.balances['CUSTOMER_DEPOSITS']}"
            )

        return {
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "total_equity": total_equity,
            "net_pnl": net_pnl,
            "cash_cents": self.balances["CASH"],
            "repo_cents": self.balances["REPO"],
            "overdraft_cents": self.balances["OVERDRAFT"],
            "payout_queue_cents": self.balances["PAYOUT_QUEUE"],
        }
