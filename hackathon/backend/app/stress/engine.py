from __future__ import annotations
import math
from typing import Dict, List, Optional, Any, Tuple
import pandas as pd
from pydantic import BaseModel, Field

from backend.app.core.config import TreasuryConfig
from backend.app.simulation.engine import SimulationEngine


class StressScenarioParams(BaseModel):
    scenario_id: str
    start_step: int = 10
    duration_hours: int = 6
    multiplier: float = 3.0
    amount_usd: float = 150_000_000.0
    delay_hours: int = 6
    yield_shock_bp: float = 150.0
    equity_crash_pct: float = -25.0
    od_limit_mult: float = 0.25


class StressReport(BaseModel):
    scenario_id: str
    start_step: int
    duration_hours: int
    min_cash_unstressed_cents: int
    min_cash_stressed_cents: int
    payout_failures_unstressed: int
    payout_failures_stressed: int
    payout_failed_usd_stressed: float
    overdraft_peak_unstressed_cents: int
    overdraft_peak_stressed_cents: int
    overdraft_interest_stressed_cents: int
    early_redemption_cost_stressed_cents: int
    net_pnl_delta_cents: int
    passed_operational_threshold: bool
    breach_cause: Optional[str] = None


def apply_stress_to_dataset(
    df: pd.DataFrame,
    params: StressScenarioParams,
    config: TreasuryConfig,
) -> Tuple[pd.DataFrame, TreasuryConfig]:
    """Applies scenario transformation on the dataset row stream and returns modified copy and config.
    The original dataset in storage is never modified.
    """
    df_stressed = df.copy()
    cfg_stressed = config.model_copy(deep=True)
    s = params.start_step
    e = s + params.duration_hours

    sid = params.scenario_id

    if sid == "OUTFLOW_MULT":
        # W <- W * multiplier
        df_stressed.loc[s:e, "withdrawals_usd"] *= params.multiplier
        df_stressed.loc[s:e, "net_flow_usd"] = df_stressed.loc[s:e, "deposits_usd"] - df_stressed.loc[s:e, "withdrawals_usd"]

    elif sid == "WITHDRAWAL_SPIKE":
        # One-off or ramp spike
        df_stressed.loc[s, "withdrawals_usd"] += params.amount_usd
        df_stressed.loc[s, "net_flow_usd"] = df_stressed.loc[s, "deposits_usd"] - df_stressed.loc[s, "withdrawals_usd"]

    elif sid == "DELAYED_DEPOSITS":
        # Shift deposits forward by delay_hours
        delay = params.delay_hours
        dep_shifted = df_stressed.loc[s:e, "deposits_usd"].copy()
        df_stressed.loc[s:e, "deposits_usd"] = 0.0
        # Re-inject at e
        target_idx = min(len(df_stressed) - 1, e)
        df_stressed.loc[target_idx, "deposits_usd"] += dep_shifted.sum()
        df_stressed["net_flow_usd"] = df_stressed["deposits_usd"] - df_stressed["withdrawals_usd"]

    elif sid == "REPO_UNAVAILABLE":
        # Window flags forced False, maturity blocked for duration
        df_stressed.loc[s:e, "repo_sweep_window_open"] = False
        df_stressed.loc[s:e, "repo_sweep_mature"] = False

    elif sid == "LIQUIDATION_DELAY":
        # Increases settlement lags in config
        cfg_stressed.bond_settlement_lag_hours += 48
        cfg_stressed.stock_settlement_lag_hours += 48

    elif sid == "BOND_SHOCK":
        # Yield increases by yield_shock_bp (+150 bp)
        shock = params.yield_shock_bp / 100.0  # +1.50%
        df_stressed.loc[s:e, "tier2_bond_yield_pct"] += shock
        dur = float(df_stressed.loc[s, "tier2_bond_mod_duration"])
        price_drop = dur * (shock / 100.0)
        df_stressed.loc[s:e, "tier2_bond_price_index"] *= (1.0 - price_drop)

    elif sid == "EQUITY_CRASH":
        # Index drops by 25% linearly over duration
        mult = 1.0 + (params.equity_crash_pct / 100.0)
        df_stressed.loc[s:e, "tier3_stock_index_price"] *= mult

    elif sid == "CORRELATED_RUN":
        # OUTFLOW_MULT 3x + EQUITY_CRASH -20% + BOND_SHOCK +100bp
        df_stressed.loc[s:e, "withdrawals_usd"] *= 3.0
        df_stressed.loc[s:e, "net_flow_usd"] = df_stressed.loc[s:e, "deposits_usd"] - df_stressed.loc[s:e, "withdrawals_usd"]
        df_stressed.loc[s:e, "tier3_stock_index_price"] *= 0.80
        df_stressed.loc[s:e, "tier2_bond_yield_pct"] += 1.00

    elif sid == "OVERDRAFT_RESTRICTED":
        # Reduce overdraft limit
        cfg_stressed.overdraft_limit_usd *= params.od_limit_mult

    elif sid == "COMBINED_WORST":
        # All above chained
        df_stressed.loc[s:e, "withdrawals_usd"] *= 3.0
        df_stressed.loc[s, "withdrawals_usd"] += 50_000_000.0
        df_stressed.loc[s:e, "repo_sweep_window_open"] = False
        df_stressed.loc[s:e, "repo_sweep_mature"] = False
        cfg_stressed.overdraft_limit_usd *= 0.25
        df_stressed.loc[s:e, "tier2_bond_yield_pct"] += 1.50
        df_stressed.loc[s:e, "tier3_stock_index_price"] *= 0.75
        df_stressed["net_flow_usd"] = df_stressed["deposits_usd"] - df_stressed["withdrawals_usd"]

    return df_stressed, cfg_stressed


def run_stress_scenario(
    base_df: pd.DataFrame,
    data_hash: str,
    base_config: TreasuryConfig,
    params: StressScenarioParams,
    horizon_steps: int = 48,
) -> StressReport:
    """Runs unstressed baseline vs stressed scenario and produces StressReport."""
    # 1. Unstressed Run
    engine_base = SimulationEngine(
        config=base_config,
        dataset=base_df,
        data_hash=data_hash,
        run_id=f"base_{params.scenario_id}",
    )
    min_cash_base = engine_base.ledger.get_balance("CASH")
    peak_od_base = 0

    for _ in range(horizon_steps):
        engine_base.step()
        c = engine_base.ledger.get_balance("CASH")
        od = engine_base.ledger.get_balance("OVERDRAFT")
        min_cash_base = min(min_cash_base, c)
        peak_od_base = max(peak_od_base, od)

    # 2. Stressed Run
    stressed_df, stressed_cfg = apply_stress_to_dataset(base_df, params, base_config)
    engine_stressed = SimulationEngine(
        config=stressed_cfg,
        dataset=stressed_df,
        data_hash=data_hash,
        run_id=f"stressed_{params.scenario_id}",
    )
    min_cash_stressed = engine_stressed.ledger.get_balance("CASH")
    peak_od_stressed = 0
    breach_cause = None

    for s_idx in range(horizon_steps):
        try:
            engine_stressed.step()
        except Exception as e:
            if breach_cause is None:
                breach_cause = f"TERMINATED_{type(e).__name__}: {str(e)}"
            break
        c = engine_stressed.ledger.get_balance("CASH")
        od = engine_stressed.ledger.get_balance("OVERDRAFT")
        min_cash_stressed = min(min_cash_stressed, c)
        peak_od_stressed = max(peak_od_stressed, od)
        if c == 0 and od > 0 and breach_cause is None:
            breach_cause = f"CASH_DEPLETED_AT_STEP_{s_idx}"
        if engine_stressed.payout_queue.total_outstanding_cents > 0 and breach_cause is None:
            breach_cause = f"OD_EXHAUSTED_PAYOUT_FAILED_AT_STEP_{s_idx}"

    net_delta = engine_stressed.ledger.get_balance("REPO_INTEREST") - (
        engine_stressed.ledger.get_balance("OD_INTEREST") + engine_stressed.ledger.get_balance("EARLY_REDEMPTION_COST")
    ) - engine_base.ledger.get_balance("REPO_INTEREST")

    failed_cents = engine_stressed.payout_queue.total_outstanding_cents

    return StressReport(
        scenario_id=params.scenario_id,
        start_step=params.start_step,
        duration_hours=params.duration_hours,
        min_cash_unstressed_cents=min_cash_base,
        min_cash_stressed_cents=min_cash_stressed,
        payout_failures_unstressed=engine_base.payout_failure_events,
        payout_failures_stressed=engine_stressed.payout_failure_events,
        payout_failed_usd_stressed=failed_cents / 100.0,
        overdraft_peak_unstressed_cents=peak_od_base,
        overdraft_peak_stressed_cents=peak_od_stressed,
        overdraft_interest_stressed_cents=engine_stressed.ledger.get_balance("OD_INTEREST"),
        early_redemption_cost_stressed_cents=engine_stressed.ledger.get_balance("EARLY_REDEMPTION_COST"),
        net_pnl_delta_cents=net_delta,
        passed_operational_threshold=(failed_cents == 0),
        breach_cause=breach_cause,
    )
