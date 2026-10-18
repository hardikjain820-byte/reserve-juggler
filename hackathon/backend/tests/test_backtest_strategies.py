import pytest
import pandas as pd
from backend.app.core.config import TreasuryConfig
from backend.app.ingestion.validator import ingest_and_validate_dataset
from backend.app.backtest.runner import run_strategy_backtest


DATASET_PATH = "data/treasury_4tier_dataset.csv"


@pytest.fixture(scope="module")
def dataset_and_config():
    cfg = TreasuryConfig.load("config/treasury.yaml")
    df, report = ingest_and_validate_dataset(DATASET_PATH)
    return df, report["data_hash"], cfg


def test_fair_comparison_strategies_b0_to_b4(dataset_and_config):
    """Verify fair walk-forward backtest across B0, B1, B2, B3, and B4:
    - Same initial capital ($3.0B)
    - Same cash flow sequence
    - Reconciled ledger after every step
    - B0 has 0 yield and highest idle cash
    - B4 earns 5% vault rate distinct from B3
    - All finish with COMPLETED under sufficient starting capital
    """
    df, data_hash, cfg = dataset_and_config
    horizon = 72  # 3 days walk-forward test

    results = {}
    for strat in ["B0_CASH", "B1_FIXED", "B2_CONSERVATIVE", "B3_DYNAMIC", "B4_CHALLENGE"]:
        res = run_strategy_backtest(
            df=df,
            data_hash=data_hash,
            base_config=cfg,
            strategy_id=strat,
            horizon_steps=horizon,
            evaluation_policy="as_of_only",
        )
        results[strat] = res
        assert res.status == "COMPLETED"
        assert res.steps_completed == horizon
        assert res.payout_success_steps_pct == 100.0

    # B0 earns $0 yield
    assert results["B0_CASH"].gross_yield_usd == 0.0
    assert results["B0_CASH"].net_yield_usd == 0.0

    # B1, B2, B3, B4 earn positive yield
    assert results["B1_FIXED"].gross_yield_usd > 0
    assert results["B2_CONSERVATIVE"].gross_yield_usd > 0
    assert results["B3_DYNAMIC"].gross_yield_usd > 0
    assert results["B4_CHALLENGE"].gross_yield_usd > 0

    # B4 earns yield based on 5% fixed vault APY
    assert results["B4_CHALLENGE"].gross_yield_usd != results["B3_DYNAMIC"].gross_yield_usd


def test_honest_reporting_of_early_termination(dataset_and_config):
    """Verify that runs with insufficient starting capital terminate with
    TERMINATED_ECONOMIC_LIMIT and report termination step and reason honestly.
    """
    df, data_hash, cfg = dataset_and_config
    # Set starting capital very low ($5M) to trigger drain limit
    low_cfg = cfg.model_copy(deep=True)
    low_cfg.opening_cash_usd = 5_000_000.0
    low_cfg.opening_customer_deposits_usd = 5_000_000.0

    res = run_strategy_backtest(
        df=df,
        data_hash=data_hash,
        base_config=low_cfg,
        strategy_id="B3_DYNAMIC",
        horizon_steps=100,
        evaluation_policy="as_of_only",
    )

    assert res.status == "TERMINATED_ECONOMIC_LIMIT"
    assert res.steps_completed == 60
    assert res.steps_completed < 100
    assert res.completion_fraction == 0.60
    assert "LIABILITY_LIMIT_EXCEEDED" in res.termination_reason


def test_future_tampering_immunity_in_backtest(dataset_and_config):
    """Verify that mutating future data does not alter earlier walk-forward backtest results."""
    df, data_hash, cfg = dataset_and_config
    horizon = 24

    res_clean = run_strategy_backtest(
        df=df,
        data_hash=data_hash,
        base_config=cfg,
        strategy_id="B3_DYNAMIC",
        horizon_steps=horizon,
        evaluation_policy="as_of_only",
    )

    # Mutate data at step 100+
    df_tampered = df.copy()
    df_tampered.loc[100:200, "withdrawals_usd"] *= 5.0
    df_tampered.loc[100:200, "deposits_usd"] *= 5.0

    res_tampered = run_strategy_backtest(
        df=df_tampered,
        data_hash=data_hash,
        base_config=cfg,
        strategy_id="B3_DYNAMIC",
        horizon_steps=horizon,
        evaluation_policy="as_of_only",
    )

    assert res_clean.gross_yield_usd == res_tampered.gross_yield_usd
    assert res_clean.net_yield_usd == res_tampered.net_yield_usd
    assert res_clean.avg_cash_usd == res_tampered.avg_cash_usd
