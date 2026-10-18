"""Automated tests for Stale-Data Fail-Safe, Kill Switch, and Exception handling."""

from datetime import datetime, timedelta
import pytest

from reserve_juggler.config import CONFIG, to_cents
from reserve_juggler.engine import TreasuryEngine
from reserve_juggler.forecaster import Forecaster, StaleDataException
from reserve_juggler.models import EngineMode, FlowBucket, LedgerAccount


def test_stale_data_exception_raised():
    """Verify that a time gap > 30 minutes raises StaleDataException."""
    forecaster = Forecaster()
    t0 = datetime(2026, 10, 1, 10, 0, 0)
    bucket0 = FlowBucket(
        bucket_index=0,
        timestamp=t0,
        inflow_cents=to_cents(5_000_000.0),
        outflow_cents=to_cents(5_000_000.0),
    )
    forecaster.update_actuals(bucket0)

    # Next bucket arrives 45 minutes later (> 30 min threshold)
    t1 = t0 + timedelta(minutes=45)
    bucket1 = FlowBucket(
        bucket_index=1,
        timestamp=t1,
        inflow_cents=to_cents(5_000_000.0),
        outflow_cents=to_cents(5_000_000.0),
    )

    with pytest.raises(StaleDataException):
        forecaster.update_actuals(bucket1)


def test_engine_failsafe_halts_sweeps():
    """Verify that when engine enters FAILSAFE mode, sweeps are completely stopped (never fail open)."""
    engine = TreasuryEngine()
    engine.set_mode(EngineMode.FAILSAFE, reason="Telemetry heartbeat lost.")

    t0 = datetime(2026, 10, 1, 12, 0, 0)
    bucket = FlowBucket(
        bucket_index=1,
        timestamp=t0,
        inflow_cents=to_cents(10_000_000.0),  # large inflow
        outflow_cents=to_cents(1_000_000.0),
    )

    initial_vault = engine.ledger.get_balance(LedgerAccount.YIELD_VAULT)
    initial_cash = engine.ledger.get_balance(LedgerAccount.CASH_BUFFER)

    audit_rec = engine.step(bucket)

    assert audit_rec.decision == "FAILSAFE_HOLD"
    assert audit_rec.sweep_amount_cents == 0
    # Vault balance must not have increased (no new money swept to vault)
    assert engine.ledger.get_balance(LedgerAccount.YIELD_VAULT) <= initial_vault
    # All excess cash held in cash buffer
    assert engine.ledger.get_balance(LedgerAccount.CASH_BUFFER) > initial_cash


def test_kill_switch_blocks_sweeps():
    """Verify that activating kill switch stops sweeps immediately."""
    engine = TreasuryEngine()
    engine.trigger_kill_switch()
    assert engine.mode == EngineMode.KILLED

    t0 = datetime(2026, 10, 1, 12, 0, 0)
    bucket = FlowBucket(
        bucket_index=1,
        timestamp=t0,
        inflow_cents=to_cents(8_000_000.0),
        outflow_cents=to_cents(2_000_000.0),
    )

    audit_rec = engine.step(bucket)
    assert audit_rec.decision == "KILLED_HOLD"
    assert audit_rec.sweep_amount_cents == 0
