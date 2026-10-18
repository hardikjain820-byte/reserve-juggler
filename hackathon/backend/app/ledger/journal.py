from __future__ import annotations
from typing import Tuple
from backend.app.ledger.models import LedgerEntry, LedgerTxn, generate_txn_id


def create_opening_txn(
    run_id: str,
    opening_cash_cents: int,
    opening_deposits_cents: int,
    ts: str,
    seq: int = 0,
) -> LedgerTxn:
    if opening_cash_cents != opening_deposits_cents:
        raise ValueError("Opening cash must equal opening customer deposits for balanced position")
    entries = [
        LedgerEntry(account="CASH", debit_cents=opening_cash_cents),
        LedgerEntry(account="CUSTOMER_DEPOSITS", credit_cents=opening_deposits_cents),
    ]
    txn = LedgerTxn(
        txn_id=generate_txn_id(run_id, 0, "OPENING", seq),
        run_id=run_id,
        step_index=0,
        kind="OPENING",
        timestamp=ts,
        entries=entries,
        memo="Initial opening balance",
    )
    txn.validate_balanced()
    return txn


def create_deposit_txn(
    run_id: str, step_index: int, amount_cents: int, ts: str, seq: int
) -> LedgerTxn:
    entries = [
        LedgerEntry(account="CASH", debit_cents=amount_cents),
        LedgerEntry(account="CUSTOMER_DEPOSITS", credit_cents=amount_cents),
    ]
    txn = LedgerTxn(
        txn_id=generate_txn_id(run_id, step_index, "DEPOSIT", seq),
        run_id=run_id,
        step_index=step_index,
        kind="DEPOSIT",
        timestamp=ts,
        entries=entries,
        memo=f"Hourly customer deposits: {amount_cents} cents",
    )
    txn.validate_balanced()
    return txn


def create_immediate_withdrawal_txn(
    run_id: str, step_index: int, amount_cents: int, ts: str, seq: int
) -> LedgerTxn:
    entries = [
        LedgerEntry(account="CUSTOMER_DEPOSITS", debit_cents=amount_cents),
        LedgerEntry(account="CASH", credit_cents=amount_cents),
    ]
    txn = LedgerTxn(
        txn_id=generate_txn_id(run_id, step_index, "WITHDRAWAL_IMMEDIATE", seq),
        run_id=run_id,
        step_index=step_index,
        kind="WITHDRAWAL_IMMEDIATE",
        timestamp=ts,
        entries=entries,
        memo=f"Immediate customer withdrawal: {amount_cents} cents",
    )
    txn.validate_balanced()
    return txn


def create_queue_transfer_txn(
    run_id: str, step_index: int, amount_cents: int, ts: str, seq: int
) -> LedgerTxn:
    # Transfer unpaid customer liability to payout queue liability
    entries = [
        LedgerEntry(account="CUSTOMER_DEPOSITS", debit_cents=amount_cents),
        LedgerEntry(account="PAYOUT_QUEUE", credit_cents=amount_cents),
    ]
    txn = LedgerTxn(
        txn_id=generate_txn_id(run_id, step_index, "QUEUE_TRANSFER", seq),
        run_id=run_id,
        step_index=step_index,
        kind="QUEUE_TRANSFER",
        timestamp=ts,
        entries=entries,
        memo=f"Transfer to delayed payout queue: {amount_cents} cents",
    )
    txn.validate_balanced()
    return txn


def create_queued_payout_paid_txn(
    run_id: str, step_index: int, amount_cents: int, ts: str, seq: int
) -> LedgerTxn:
    # Settlement of queued payout from cash
    entries = [
        LedgerEntry(account="PAYOUT_QUEUE", debit_cents=amount_cents),
        LedgerEntry(account="CASH", credit_cents=amount_cents),
    ]
    txn = LedgerTxn(
        txn_id=generate_txn_id(run_id, step_index, "QUEUE_PAID", seq),
        run_id=run_id,
        step_index=step_index,
        kind="QUEUE_PAID",
        timestamp=ts,
        entries=entries,
        memo=f"Settlement of delayed payout: {amount_cents} cents",
    )
    txn.validate_balanced()
    return txn


def create_repo_sweep_txn(
    run_id: str, step_index: int, principal_cents: int, ts: str, seq: int
) -> LedgerTxn:
    entries = [
        LedgerEntry(account="REPO", debit_cents=principal_cents),
        LedgerEntry(account="CASH", credit_cents=principal_cents),
    ]
    txn = LedgerTxn(
        txn_id=generate_txn_id(run_id, step_index, "REPO_SWEEP", seq),
        run_id=run_id,
        step_index=step_index,
        kind="REPO_SWEEP",
        timestamp=ts,
        entries=entries,
        memo=f"Repo sweep: {principal_cents} cents",
    )
    txn.validate_balanced()
    return txn


def create_repo_maturity_txn(
    run_id: str,
    step_index: int,
    principal_cents: int,
    interest_cents: int,
    ts: str,
    seq: int,
) -> LedgerTxn:
    entries = [
        LedgerEntry(account="CASH", debit_cents=principal_cents + interest_cents),
        LedgerEntry(account="REPO", credit_cents=principal_cents),
        LedgerEntry(account="REPO_INTEREST", credit_cents=interest_cents),
    ]
    txn = LedgerTxn(
        txn_id=generate_txn_id(run_id, step_index, "REPO_MATURE", seq),
        run_id=run_id,
        step_index=step_index,
        kind="REPO_MATURE",
        timestamp=ts,
        entries=entries,
        memo=f"Repo maturity: principal {principal_cents}, interest {interest_cents} cents",
    )
    txn.validate_balanced()
    return txn


def create_repo_early_redemption_txn(
    run_id: str,
    step_index: int,
    principal_cents: int,
    haircut_cents: int,
    ts: str,
    seq: int,
) -> LedgerTxn:
    cash_cents = principal_cents - haircut_cents
    entries = [
        LedgerEntry(account="CASH", debit_cents=cash_cents),
        LedgerEntry(account="EARLY_REDEMPTION_COST", debit_cents=haircut_cents),
        LedgerEntry(account="REPO", credit_cents=principal_cents),
    ]
    txn = LedgerTxn(
        txn_id=generate_txn_id(run_id, step_index, "REPO_EARLY_REDEMPTION", seq),
        run_id=run_id,
        step_index=step_index,
        kind="REPO_EARLY_REDEMPTION",
        timestamp=ts,
        entries=entries,
        memo=f"Repo early redemption: principal {principal_cents}, haircut {haircut_cents} cents",
    )
    txn.validate_balanced()
    return txn


def create_overdraft_draw_txn(
    run_id: str, step_index: int, amount_cents: int, ts: str, seq: int
) -> LedgerTxn:
    entries = [
        LedgerEntry(account="CASH", debit_cents=amount_cents),
        LedgerEntry(account="OVERDRAFT", credit_cents=amount_cents),
    ]
    txn = LedgerTxn(
        txn_id=generate_txn_id(run_id, step_index, "OVERDRAFT_DRAW", seq),
        run_id=run_id,
        step_index=step_index,
        kind="OVERDRAFT_DRAW",
        timestamp=ts,
        entries=entries,
        memo=f"Overdraft draw: {amount_cents} cents",
    )
    txn.validate_balanced()
    return txn


def create_overdraft_repay_txn(
    run_id: str, step_index: int, amount_cents: int, ts: str, seq: int
) -> LedgerTxn:
    entries = [
        LedgerEntry(account="OVERDRAFT", debit_cents=amount_cents),
        LedgerEntry(account="CASH", credit_cents=amount_cents),
    ]
    txn = LedgerTxn(
        txn_id=generate_txn_id(run_id, step_index, "OVERDRAFT_REPAY", seq),
        run_id=run_id,
        step_index=step_index,
        kind="OVERDRAFT_REPAY",
        timestamp=ts,
        entries=entries,
        memo=f"Overdraft repayment: {amount_cents} cents",
    )
    txn.validate_balanced()
    return txn


def create_overdraft_interest_txn(
    run_id: str, step_index: int, interest_cents: int, ts: str, seq: int
) -> LedgerTxn:
    entries = [
        LedgerEntry(account="OD_INTEREST", debit_cents=interest_cents),
        LedgerEntry(account="OVERDRAFT", credit_cents=interest_cents),
    ]
    txn = LedgerTxn(
        txn_id=generate_txn_id(run_id, step_index, "OD_INTEREST", seq),
        run_id=run_id,
        step_index=step_index,
        kind="OD_INTEREST",
        timestamp=ts,
        entries=entries,
        memo=f"Overdraft interest accrued: {interest_cents} cents",
    )
    txn.validate_balanced()
    return txn


def create_bond_purchase_txn(
    run_id: str, step_index: int, cost_cents: int, ts: str, seq: int
) -> LedgerTxn:
    entries = [
        LedgerEntry(account="BOND", debit_cents=cost_cents),
        LedgerEntry(account="CASH", credit_cents=cost_cents),
    ]
    txn = LedgerTxn(
        txn_id=generate_txn_id(run_id, step_index, "BOND_PURCHASE", seq),
        run_id=run_id,
        step_index=step_index,
        kind="BOND_PURCHASE",
        timestamp=ts,
        entries=entries,
        memo=f"Bond purchase cost: {cost_cents} cents",
    )
    txn.validate_balanced()
    return txn


def create_bond_carry_txn(
    run_id: str, step_index: int, carry_cents: int, ts: str, seq: int
) -> LedgerTxn:
    entries = [
        LedgerEntry(account="BOND_ACCRUED_INTEREST", debit_cents=carry_cents),
        LedgerEntry(account="BOND_CARRY", credit_cents=carry_cents),
    ]
    txn = LedgerTxn(
        txn_id=generate_txn_id(run_id, step_index, "BOND_CARRY", seq),
        run_id=run_id,
        step_index=step_index,
        kind="BOND_CARRY",
        timestamp=ts,
        entries=entries,
        memo=f"Bond carry accrued: {carry_cents} cents",
    )
    txn.validate_balanced()
    return txn


def create_bond_mtm_txn(
    run_id: str, step_index: int, diff_cents: int, ts: str, seq: int
) -> LedgerTxn:
    if diff_cents > 0:
        entries = [
            LedgerEntry(account="BOND", debit_cents=diff_cents),
            LedgerEntry(account="MTM_GAIN", credit_cents=diff_cents),
        ]
    elif diff_cents < 0:
        abs_diff = abs(diff_cents)
        entries = [
            LedgerEntry(account="MTM_LOSS", debit_cents=abs_diff),
            LedgerEntry(account="BOND", credit_cents=abs_diff),
        ]
    else:
        raise ValueError("diff_cents must be non-zero for MTM txn")

    txn = LedgerTxn(
        txn_id=generate_txn_id(run_id, step_index, "BOND_MTM", seq),
        run_id=run_id,
        step_index=step_index,
        kind="BOND_MTM",
        timestamp=ts,
        entries=entries,
        memo=f"Bond MTM adjustment: {diff_cents} cents",
    )
    txn.validate_balanced()
    return txn


def create_bond_sale_txn(
    run_id: str,
    step_index: int,
    market_value_cents: int,
    haircut_cents: int,
    ts: str,
    seq: int,
) -> LedgerTxn:
    net_cash_cents = market_value_cents - haircut_cents
    entries = [
        LedgerEntry(account="CASH", debit_cents=net_cash_cents),
        LedgerEntry(account="BOND_LIQUIDATION_COST", debit_cents=haircut_cents),
        LedgerEntry(account="BOND", credit_cents=market_value_cents),
    ]
    txn = LedgerTxn(
        txn_id=generate_txn_id(run_id, step_index, "BOND_SALE", seq),
        run_id=run_id,
        step_index=step_index,
        kind="BOND_SALE",
        timestamp=ts,
        entries=entries,
        memo=f"Bond liquidation: mkt_val {market_value_cents}, haircut {haircut_cents} cents",
    )
    txn.validate_balanced()
    return txn


def create_stock_purchase_txn(
    run_id: str, step_index: int, cost_cents: int, ts: str, seq: int
) -> LedgerTxn:
    entries = [
        LedgerEntry(account="STOCK", debit_cents=cost_cents),
        LedgerEntry(account="CASH", credit_cents=cost_cents),
    ]
    txn = LedgerTxn(
        txn_id=generate_txn_id(run_id, step_index, "STOCK_PURCHASE", seq),
        run_id=run_id,
        step_index=step_index,
        kind="STOCK_PURCHASE",
        timestamp=ts,
        entries=entries,
        memo=f"Stock purchase cost: {cost_cents} cents",
    )
    txn.validate_balanced()
    return txn


def create_stock_mtm_txn(
    run_id: str, step_index: int, diff_cents: int, ts: str, seq: int
) -> LedgerTxn:
    if diff_cents > 0:
        entries = [
            LedgerEntry(account="STOCK", debit_cents=diff_cents),
            LedgerEntry(account="MTM_GAIN", credit_cents=diff_cents),
        ]
    elif diff_cents < 0:
        abs_diff = abs(diff_cents)
        entries = [
            LedgerEntry(account="MTM_LOSS", debit_cents=abs_diff),
            LedgerEntry(account="STOCK", credit_cents=abs_diff),
        ]
    else:
        raise ValueError("diff_cents must be non-zero for MTM txn")

    txn = LedgerTxn(
        txn_id=generate_txn_id(run_id, step_index, "STOCK_MTM", seq),
        run_id=run_id,
        step_index=step_index,
        kind="STOCK_MTM",
        timestamp=ts,
        entries=entries,
        memo=f"Stock MTM adjustment: {diff_cents} cents",
    )
    txn.validate_balanced()
    return txn


def create_stock_sale_txn(
    run_id: str,
    step_index: int,
    market_value_cents: int,
    haircut_cents: int,
    ts: str,
    seq: int,
) -> LedgerTxn:
    net_cash_cents = market_value_cents - haircut_cents
    entries = [
        LedgerEntry(account="CASH", debit_cents=net_cash_cents),
        LedgerEntry(account="STOCK_LIQUIDATION_COST", debit_cents=haircut_cents),
        LedgerEntry(account="STOCK", credit_cents=market_value_cents),
    ]
    txn = LedgerTxn(
        txn_id=generate_txn_id(run_id, step_index, "STOCK_SALE", seq),
        run_id=run_id,
        step_index=step_index,
        kind="STOCK_SALE",
        timestamp=ts,
        entries=entries,
        memo=f"Stock liquidation: mkt_val {market_value_cents}, haircut {haircut_cents} cents",
    )
    txn.validate_balanced()
    return txn
