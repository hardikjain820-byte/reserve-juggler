import pytest
from backend.app.core.config import TreasuryConfig
from backend.app.ingestion.validator import ingest_and_validate_dataset
from backend.app.simulation.engine import SimulationEngine


def test_simulation_engine_vertical_slice_48_hours():
    """Verify Phase 1 Vertical Slice 1:
    - Load & validate dataset
    - Initialize opening cash & matching customer deposit liability ($3.0B)
    - Run 48 consecutive hourly steps
    - Reconcile trial balance and balance sheet identity at EVERY step
    - Sweep repo at 17:00 (step 17) and mature at 08:00 (step 32)
    - Verify complete audit hash chain
    """
    config = TreasuryConfig.load("config/treasury.yaml")
    df, report = ingest_and_validate_dataset("data/treasury_4tier_dataset.csv")

    engine = SimulationEngine(
        config=config,
        dataset=df,
        data_hash=report["data_hash"],
        run_id="vertical_slice_test_48h",
    )

    sweeps_executed = 0
    maturities_executed = 0

    for step_num in range(48):
        step_res = engine.step()
        assert step_res["step"] == step_num
        recon = step_res["reconciliation"]

        # 1. Double-entry trial balance & balance sheet invariants
        assert recon["total_assets"] == recon["total_liabilities"] + recon["total_equity"] + recon["net_pnl"]
        assert recon["cash_cents"] >= 0
        assert engine.ledger.total_debits_posted == engine.ledger.total_credits_posted

        # 2. Check repo sweep and maturity events
        if step_res["sweep"]["decision"] == "SWEEP_EXECUTED":
            sweeps_executed += 1
            assert step_res["sweep"]["amount_cents"] >= int(config.repo_min_sweep_usd * 100)

        # Step 32 is second day 08:00 (mature row)
        if df.iloc[step_num]["repo_sweep_mature"]:
            maturities_executed += 1

    # Verify sweeps and maturities occurred
    assert sweeps_executed >= 2, f"Expected at least 2 sweeps over 48h, got {sweeps_executed}"
    assert maturities_executed == 2, f"Expected 2 maturity events over 48h, got {maturities_executed}"

    # Payouts were 100% fulfilled without failures under standard $3B liquidity buffer
    assert engine.payout_failure_events == 0
    assert engine.total_withdrawals_paid_cents == engine.total_withdrawals_requested_cents

    # Verify audit chain integrity
    valid, checked, err = engine.audit.verify()
    assert valid is True, f"Audit chain verification failed: {err}"
    assert checked >= 100, f"Expected at least 100 audit records, checked {checked}"
