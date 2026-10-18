"""Automated tests for Shock Scenario: 3x withdrawal surge for 2 hours."""

from datetime import datetime
import pytest

from reserve_juggler.config import CONFIG, to_cents
from reserve_juggler.engine import TreasuryEngine
from reserve_juggler.flow_simulator import FlowSimulator, ShockConfig


def test_shock_scenario_resilience():
    """Verify that a sudden 3x withdrawal surge for 2 hours is handled with 0 delayed payouts and 0 emergency loans."""
    start_time = datetime(2026, 10, 1, 0, 0, 0)
    sim = FlowSimulator(start_time=start_time, seed=123)

    # Inject 3x outflow shock at bucket 40 (10:00 AM) for 8 buckets (2 hours)
    shock_start = 40
    shock_duration = 8
    sim.add_shock(
        ShockConfig(
            start_bucket=shock_start,
            duration_buckets=shock_duration,
            outflow_multiplier=3.0,
            inflow_multiplier=1.0,
            description="3x withdrawal surge for 2 hours",
        )
    )

    engine = TreasuryEngine(start_time=start_time)
    buckets = sim.generate_series(num_buckets=96)  # 24 hours

    for b in buckets:
        engine.step(b)

    # Verification:
    # 1. Payout success rate must be 100%
    assert engine.payouts_attempted == 96
    assert engine.payouts_completed == 96
    assert engine.payouts_delayed == 0

    # 2. Emergency loan draws must be 0
    assert engine.sweep_engine.total_emergency_draws_count == 0

    # 3. Cryptographic audit chain verified
    assert engine.audit_logger.verify_chain_integrity() is True
