"""Automated tests for Sweep Engine idempotency, minimum threshold, and tranche management."""

from datetime import datetime
import pytest

from reserve_juggler.config import CONFIG, to_cents
from reserve_juggler.ledger import DoubleEntryLedger
from reserve_juggler.models import EngineMode, LedgerAccount
from reserve_juggler.sweep_engine import SweepEngine


def test_sweep_idempotency():
    """Verify that retrying a sweep with the same idempotency key never double-sweeps."""
    ledger = DoubleEntryLedger()
    # Initial balance: $10M cash, $10M vault
    ledger.record_initial_capital(to_cents(10_000_000.0), to_cents(10_000_000.0))
    sweep_engine = SweepEngine(ledger)

    required_buffer = to_cents(4_000_000.0)
    cycle = 1
    key = "SWEEP-TEST-001"

    # First call: should execute sweep
    decision1 = sweep_engine.execute_cycle_sweep(
        cycle_index=cycle,
        required_buffer_cents=required_buffer,
        idempotency_key=key,
    )
    assert decision1.action_taken == "SWEEP"
    assert decision1.sweep_amount_cents > 0
    cash_after_sweep1 = ledger.get_balance(LedgerAccount.CASH_BUFFER)
    vault_after_sweep1 = ledger.get_balance(LedgerAccount.YIELD_VAULT)
    num_tranches1 = len(sweep_engine.active_tranches)

    # Second call (retry with same key): must be idempotent!
    decision2 = sweep_engine.execute_cycle_sweep(
        cycle_index=cycle,
        required_buffer_cents=required_buffer,
        idempotency_key=key,
    )
    assert decision2.sweep_amount_cents == decision1.sweep_amount_cents
    assert ledger.get_balance(LedgerAccount.CASH_BUFFER) == cash_after_sweep1
    assert ledger.get_balance(LedgerAccount.YIELD_VAULT) == vault_after_sweep1
    assert len(sweep_engine.active_tranches) == num_tranches1


def test_sweep_below_minimum_threshold_skipped():
    """Verify that potential sweeps below configurable minimum are skipped."""
    ledger = DoubleEntryLedger()
    # Cash is only $10,000 above required buffer + margin
    cash = to_cents(5_000_000.0)
    req_buffer = to_cents(4_900_000.0)  # margin is $100k -> excess is $0
    ledger.record_initial_capital(cash, to_cents(10_000_000.0))
    sweep_engine = SweepEngine(ledger)

    decision = sweep_engine.execute_cycle_sweep(
        cycle_index=1,
        required_buffer_cents=req_buffer,
    )
    assert decision.sweep_amount_cents == 0
    assert "HOLD" in decision.action_taken


def test_sweep_never_touches_cash_below_required_buffer():
    """Verify that sweep never leaves cash below required buffer."""
    ledger = DoubleEntryLedger()
    ledger.record_initial_capital(to_cents(6_000_000.0), to_cents(10_000_000.0))
    sweep_engine = SweepEngine(ledger)

    req_buffer = to_cents(4_500_000.0)
    decision = sweep_engine.execute_cycle_sweep(
        cycle_index=1,
        required_buffer_cents=req_buffer,
    )

    remaining_cash = ledger.get_balance(LedgerAccount.CASH_BUFFER)
    assert remaining_cash >= req_buffer


def test_vault_tranche_maturation_yield():
    """Verify that vault tranches mature after horizon and credit 5% APY yield."""
    ledger = DoubleEntryLedger()
    ledger.record_initial_capital(to_cents(10_000_000.0), 0)
    sweep_engine = SweepEngine(ledger)

    # Sweep at cycle 0
    decision = sweep_engine.execute_cycle_sweep(
        cycle_index=0,
        required_buffer_cents=to_cents(2_000_000.0),
    )
    swept_principal = decision.sweep_amount_cents
    assert swept_principal > 0

    # Fast forward before maturity: no maturity
    matured = sweep_engine.process_tranche_maturities(current_bucket=CONFIG.VAULT_TRANCHE_HORIZON_BUCKETS - 5)
    assert len(matured) == 0

    # Fast forward to maturity at horizon
    matured = sweep_engine.process_tranche_maturities(current_bucket=CONFIG.VAULT_TRANCHE_HORIZON_BUCKETS)
    assert len(matured) == 1
    assert matured[0].accrued_yield_cents > 0
    # Ledger should have recorded yield income
    assert ledger.get_balance(LedgerAccount.YIELD_INCOME) > 0
