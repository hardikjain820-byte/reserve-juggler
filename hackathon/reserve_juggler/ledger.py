"""Double-entry integer minor units ledger with continuous reconciliation."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
from reserve_juggler.models import JournalEntry, LedgerAccount


@dataclass
class ReconciliationReport:
    is_balanced: bool
    total_assets_cents: int
    total_liabilities_cents: int
    total_equity_cents: int
    net_income_cents: int
    discrepancy_cents: int
    bank_cash_cents: int
    vault_cents: int
    external_bank_diff_cents: int
    external_vault_diff_cents: int


class DoubleEntryLedger:
    def __init__(self) -> None:
        self.accounts: Dict[LedgerAccount, int] = {acct: 0 for acct in LedgerAccount}
        self.journal: List[JournalEntry] = []
        self._entry_counter: int = 0

    def _next_entry_id(self) -> str:
        self._entry_counter += 1
        return f"JE-{self._entry_counter:07d}"

    def post(
        self,
        description: str,
        debits: Dict[LedgerAccount, int],
        credits: Dict[LedgerAccount, int],
        timestamp: Optional[datetime] = None,
    ) -> JournalEntry:
        """Create and post a validated double-entry journal entry."""
        if timestamp is None:
            timestamp = datetime.now()

        entry = JournalEntry(
            entry_id=self._next_entry_id(),
            timestamp=timestamp,
            description=description,
            debits=debits,
            credits=credits,
        )
        entry.validate()

        # Update account balances
        for acct, amount in debits.items():
            if amount < 0:
                raise ValueError(f"Debit amount cannot be negative: {amount}")
            if acct in (
                LedgerAccount.CASH_BUFFER,
                LedgerAccount.YIELD_VAULT,
                LedgerAccount.ACCRUED_YIELD_RECEIVABLE,
                LedgerAccount.EARLY_WITHDRAWAL_PENALTY_EXPENSE,
                LedgerAccount.LOAN_INTEREST_EXPENSE,
                LedgerAccount.LOAN_FEE_EXPENSE,
            ):
                self.accounts[acct] += amount
            else:
                self.accounts[acct] -= amount

        for acct, amount in credits.items():
            if amount < 0:
                raise ValueError(f"Credit amount cannot be negative: {amount}")
            if acct in (
                LedgerAccount.CUSTOMER_DEPOSITS,
                LedgerAccount.EMERGENCY_OVERDRAFT_LOAN,
                LedgerAccount.INITIAL_EQUITY,
                LedgerAccount.YIELD_INCOME,
            ):
                self.accounts[acct] += amount
            else:
                self.accounts[acct] -= amount

        self.journal.append(entry)
        return entry

    def get_balance(self, account: LedgerAccount) -> int:
        return self.accounts[account]

    def record_initial_capital(
        self, cash_cents: int, vault_cents: int, timestamp: Optional[datetime] = None
    ) -> JournalEntry:
        total = cash_cents + vault_cents
        return self.post(
            description="Initial capital allocation to Cash Buffer and Yield Vault",
            debits={
                LedgerAccount.CASH_BUFFER: cash_cents,
                LedgerAccount.YIELD_VAULT: vault_cents,
            },
            credits={
                LedgerAccount.INITIAL_EQUITY: total,
            },
            timestamp=timestamp,
        )

    def record_customer_deposit(
        self, amount_cents: int, timestamp: Optional[datetime] = None
    ) -> JournalEntry:
        return self.post(
            description=f"Customer deposit inflow of {amount_cents} cents",
            debits={LedgerAccount.CASH_BUFFER: amount_cents},
            credits={LedgerAccount.CUSTOMER_DEPOSITS: amount_cents},
            timestamp=timestamp,
        )

    def record_customer_withdrawal(
        self, amount_cents: int, timestamp: Optional[datetime] = None
    ) -> JournalEntry:
        return self.post(
            description=f"Customer withdrawal outflow of {amount_cents} cents",
            debits={LedgerAccount.CUSTOMER_DEPOSITS: amount_cents},
            credits={LedgerAccount.CASH_BUFFER: amount_cents},
            timestamp=timestamp,
        )

    def record_sweep_to_vault(
        self, amount_cents: int, timestamp: Optional[datetime] = None
    ) -> JournalEntry:
        return self.post(
            description=f"Automated liquidity sweep to Yield Vault: {amount_cents} cents",
            debits={LedgerAccount.YIELD_VAULT: amount_cents},
            credits={LedgerAccount.CASH_BUFFER: amount_cents},
            timestamp=timestamp,
        )

    def record_vault_yield_accrual(
        self, yield_cents: int, timestamp: Optional[datetime] = None
    ) -> Optional[JournalEntry]:
        if yield_cents <= 0:
            return None
        return self.post(
            description=f"Continuous vault yield accrual: {yield_cents} cents",
            debits={LedgerAccount.ACCRUED_YIELD_RECEIVABLE: yield_cents},
            credits={LedgerAccount.YIELD_INCOME: yield_cents},
            timestamp=timestamp,
        )

    def record_vault_maturity(
        self, principal_cents: int, yield_cents: int, timestamp: Optional[datetime] = None
    ) -> JournalEntry:
        total_payout = principal_cents + yield_cents
        accrued = self.accounts[LedgerAccount.ACCRUED_YIELD_RECEIVABLE]
        clear_accrued = min(accrued, yield_cents)
        direct_income = yield_cents - clear_accrued

        credits: Dict[LedgerAccount, int] = {LedgerAccount.YIELD_VAULT: principal_cents}
        if clear_accrued > 0:
            credits[LedgerAccount.ACCRUED_YIELD_RECEIVABLE] = clear_accrued
        if direct_income > 0:
            credits[LedgerAccount.YIELD_INCOME] = direct_income

        return self.post(
            description=f"Vault tranche maturity: {principal_cents} principal + {yield_cents} yield",
            debits={LedgerAccount.CASH_BUFFER: total_payout},
            credits=credits,
            timestamp=timestamp,
        )

    def record_vault_early_break(
        self, gross_principal_cents: int, penalty_cents: int, timestamp: Optional[datetime] = None
    ) -> JournalEntry:
        net_cash = gross_principal_cents - penalty_cents
        return self.post(
            description=f"Vault early withdrawal: break {gross_principal_cents} cents with {penalty_cents} penalty",
            debits={
                LedgerAccount.CASH_BUFFER: net_cash,
                LedgerAccount.EARLY_WITHDRAWAL_PENALTY_EXPENSE: penalty_cents,
            },
            credits={LedgerAccount.YIELD_VAULT: gross_principal_cents},
            timestamp=timestamp,
        )

    def record_emergency_loan_draw(
        self, principal_cents: int, flat_fee_cents: int, timestamp: Optional[datetime] = None
    ) -> JournalEntry:
        return self.post(
            description=f"Emergency overdraft loan draw: {principal_cents} cents (fee: {flat_fee_cents})",
            debits={
                LedgerAccount.CASH_BUFFER: principal_cents,
                LedgerAccount.LOAN_FEE_EXPENSE: flat_fee_cents,
            },
            credits={
                LedgerAccount.EMERGENCY_OVERDRAFT_LOAN: principal_cents + flat_fee_cents,
            },
            timestamp=timestamp,
        )

    def record_emergency_loan_repayment(
        self, principal_cents: int, interest_cents: int, timestamp: Optional[datetime] = None
    ) -> JournalEntry:
        total_repaid = principal_cents + interest_cents
        debits = {LedgerAccount.EMERGENCY_OVERDRAFT_LOAN: principal_cents}
        if interest_cents > 0:
            debits[LedgerAccount.LOAN_INTEREST_EXPENSE] = interest_cents
        return self.post(
            description=f"Emergency overdraft repayment: {principal_cents} principal + {interest_cents} interest",
            debits=debits,
            credits={LedgerAccount.CASH_BUFFER: total_repaid},
            timestamp=timestamp,
        )

    def reconcile(
        self, external_bank_cash_cents: int, external_vault_cents: int
    ) -> ReconciliationReport:
        """Perform full accounting cycle reconciliation."""
        assets = (
            self.accounts[LedgerAccount.CASH_BUFFER]
            + self.accounts[LedgerAccount.YIELD_VAULT]
            + self.accounts[LedgerAccount.ACCRUED_YIELD_RECEIVABLE]
        )
        liabilities = (
            self.accounts[LedgerAccount.CUSTOMER_DEPOSITS]
            + self.accounts[LedgerAccount.EMERGENCY_OVERDRAFT_LOAN]
        )
        equity = self.accounts[LedgerAccount.INITIAL_EQUITY]
        net_income = (
            self.accounts[LedgerAccount.YIELD_INCOME]
            - self.accounts[LedgerAccount.EARLY_WITHDRAWAL_PENALTY_EXPENSE]
            - self.accounts[LedgerAccount.LOAN_INTEREST_EXPENSE]
            - self.accounts[LedgerAccount.LOAN_FEE_EXPENSE]
        )

        accounting_diff = assets - (liabilities + equity + net_income)
        ext_bank_diff = self.accounts[LedgerAccount.CASH_BUFFER] - external_bank_cash_cents
        ext_vault_diff = self.accounts[LedgerAccount.YIELD_VAULT] - external_vault_cents

        is_balanced = (
            accounting_diff == 0
            and ext_bank_diff == 0
            and ext_vault_diff == 0
        )

        return ReconciliationReport(
            is_balanced=is_balanced,
            total_assets_cents=assets,
            total_liabilities_cents=liabilities,
            total_equity_cents=equity,
            net_income_cents=net_income,
            discrepancy_cents=accounting_diff,
            bank_cash_cents=self.accounts[LedgerAccount.CASH_BUFFER],
            vault_cents=self.accounts[LedgerAccount.YIELD_VAULT],
            external_bank_diff_cents=ext_bank_diff,
            external_vault_diff_cents=ext_vault_diff,
        )
