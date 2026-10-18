from __future__ import annotations
import os
from typing import Dict, Any, Optional, List, Tuple
from fastapi import FastAPI, HTTPException, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import asyncio
import json

from backend.app.core.config import TreasuryConfig
from backend.app.ingestion.validator import ingest_and_validate_dataset
from backend.app.simulation.engine import SimulationEngine
from backend.app.forecast.models import evaluate_forecasts


DATASET_PATH = "data/treasury_4tier_dataset.csv"
EXECUTION_MODE = "SIMULATION"

app = FastAPI(
    title="Reserve Juggler — Autonomous Treasury Engine",
    description="Simulation-only institutional treasury and liquidity optimization engine",
    version="1.3",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global engine state for simulation
config = TreasuryConfig.load("config/treasury.yaml")
dataset_df, quality_report = ingest_and_validate_dataset(DATASET_PATH, as_of_str=config.as_of_timestamp)
active_engine: Optional[SimulationEngine] = SimulationEngine(
    config=config,
    dataset=dataset_df,
    data_hash=quality_report["data_hash"],
    run_id="run_live_01",
)
processed_idempotency_keys: Dict[str, Any] = {}


@app.get("/health")
def get_health():
    return {
        "status": "HEALTHY",
        "mode": EXECUTION_MODE,
        "dataset_loaded": dataset_df is not None,
        "rows": len(dataset_df) if dataset_df is not None else 0,
        "run_id": active_engine.run_id if active_engine else None,
    }


@app.get("/api/v1/config")
def get_config():
    return config.model_dump()


@app.put("/api/v1/config")
def update_config(new_conf: Dict[str, Any]):
    global config, active_engine
    try:
        config = TreasuryConfig(**new_conf)
        # Re-initialize engine with updated config
        active_engine = SimulationEngine(
            config=config,
            dataset=dataset_df,
            data_hash=quality_report["data_hash"],
            run_id="run_live_01",
        )
        return {"status": "UPDATED", "config": config.model_dump()}
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"CONFIG_INVALID: {str(e)}")


@app.get("/api/v1/data/quality")
def get_data_quality():
    return quality_report


class RunCreateRequest(BaseModel):
    step_minutes: int = 60
    seed: int = 42
    start_idx: int = 0
    strategy: str = "B3_DYNAMIC"


@app.post("/api/v1/sim/runs")
def create_run(req: RunCreateRequest):
    global active_engine
    run_id = f"run_{req.strategy}_{req.step_minutes}m"
    active_engine = SimulationEngine(
        config=config,
        dataset=dataset_df,
        data_hash=quality_report["data_hash"],
        run_id=run_id,
    )
    return {"run_id": run_id, "status": "INITIALIZED", "start_idx": req.start_idx}


@app.post("/api/v1/sim/runs/{run_id}/step")
def step_simulation(run_id: str, idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    global active_engine
    if not active_engine or active_engine.run_id != run_id:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")

    if idempotency_key and idempotency_key in processed_idempotency_keys:
        return processed_idempotency_keys[idempotency_key]

    step_result = active_engine.step()

    if idempotency_key:
        processed_idempotency_keys[idempotency_key] = step_result

    return step_result


@app.get("/api/v1/kpis")
def get_kpis(run_id: str = Query("run_live_01")):
    if not active_engine or active_engine.run_id != run_id:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")

    recon = active_engine.ledger.reconcile()
    reserves = active_engine.calculate_reserves(active_engine.current_step)
    
    total_req = active_engine.total_withdrawals_requested_cents
    total_paid = active_engine.total_withdrawals_paid_cents
    payout_success_pct = (total_paid / total_req * 100.0) if total_req > 0 else 100.0

    return {
        "step": active_engine.current_step,
        "cash_cents": str(recon["cash_cents"]),
        "repo_cents": str(recon["repo_cents"]),
        "overdraft_cents": str(recon["overdraft_cents"]),
        "payout_queue_cents": str(recon["payout_queue_cents"]),
        "r_total_cents": str(reserves["r_total_cents"]),
        "headroom_cents": str(reserves["headroom_cents"]),
        "sweepable_surplus_cents": str(reserves["sweepable_surplus_cents"]),
        "cumulative_net_pnl_cents": str(recon["net_pnl"]),
        "payout_success": {
            "success_rate_pct": round(payout_success_pct, 4),
            "failed_events": active_engine.payout_failure_events,
        },
        "open_repos": len(active_engine.open_repos),
    }


@app.get("/api/v1/reserve")
def get_reserve(run_id: str = Query("run_live_01")):
    if not active_engine or active_engine.run_id != run_id:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")

    res = active_engine.calculate_reserves(active_engine.current_step)
    return {k: str(v) for k, v in res.items()}


@app.get("/api/v1/forecast")
def get_forecast(run_id: str = Query("run_live_01"), horizon: int = 24):
    if not active_engine or active_engine.run_id != run_id:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")

    as_of = max(24, active_engine.current_step)
    horizons = [1, 6, 12, horizon]
    dep_forecasts = evaluate_forecasts(dataset_df, as_of_index=as_of, target_col="deposits_usd", horizons=horizons)
    wd_forecasts = evaluate_forecasts(dataset_df, as_of_index=as_of, target_col="withdrawals_usd", horizons=horizons)

    return {
        "as_of_step": as_of,
        "deposits": [f.model_dump() for f in dep_forecasts],
        "withdrawals": [f.model_dump() for f in wd_forecasts],
    }


class ManualSweepPreviewRequest(BaseModel):
    tier: int = 1
    amount_cents: str


@app.post("/api/v1/treasury/sweeps/preview")
def preview_sweep(req: ManualSweepPreviewRequest):
    if not active_engine:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")

    amount = int(req.amount_cents)
    reserves = active_engine.calculate_reserves(active_engine.current_step)
    surplus = reserves["sweepable_surplus_cents"]
    cash = active_engine.ledger.get_balance("CASH")
    od = active_engine.ledger.get_balance("OVERDRAFT")
    queue = active_engine.payout_queue.total_outstanding_cents

    reasons = []
    if od > 0:
        reasons.append("OD_OUTSTANDING")
    if queue > 0:
        reasons.append("PAYOUT_QUEUE_OUTSTANDING")
    if amount > surplus:
        reasons.append("SWEEP_EXCEEDS_SURPLUS")
    if amount < int(config.repo_min_sweep_usd * 100):
        reasons.append("BELOW_MIN")

    valid = len(reasons) == 0

    return {
        "valid": valid,
        "reason_codes": reasons,
        "requested_cents": str(amount),
        "sweepable_surplus_cents": str(surplus),
        "before": {"cash_cents": str(cash)},
        "after": {"cash_cents": str(cash - amount if valid else cash)},
        "headroom_after_cents": str(cash - amount - reserves["r_total_cents"] if valid else cash - reserves["r_total_cents"]),
    }


@app.get("/api/v1/audit/verify")
def verify_audit_chain(run_id: str = Query("run_live_01")):
    if not active_engine or active_engine.run_id != run_id:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")

    valid, checked, err = active_engine.audit.verify()
    return {
        "valid": valid,
        "checked_records": checked,
        "error": err,
    }


@app.get("/api/v1/treasury/decisions")
def get_decisions(run_id: str = Query("run_live_01"), limit: int = 50):
    if not active_engine or active_engine.run_id != run_id:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")

    # Return newest audit records first
    records = list(reversed(active_engine.audit.records))[:limit]
    return [
        {
            "seq": r.seq,
            "step_index": r.step_index,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "reason": r.reason,
            "payload": r.payload,
            "record_hash": r.record_hash[:16] + "...",
            "prev_hash": r.prev_hash[:16] + "...",
        }
        for r in records
    ]


class ExecuteSweepRequest(BaseModel):
    tier: int = 1
    amount_cents: str
    confirm: bool = True


@app.post("/api/v1/treasury/sweeps")
def execute_sweep(req: ExecuteSweepRequest, idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    global active_engine
    if not active_engine:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
    if not req.confirm:
        raise HTTPException(status_code=400, detail="CONFIRMATION_REQUIRED")

    amount = int(req.amount_cents)
    reserves = active_engine.calculate_reserves(active_engine.current_step)
    surplus = reserves["sweepable_surplus_cents"]
    od = active_engine.ledger.get_balance("OVERDRAFT")
    queue = active_engine.payout_queue.total_outstanding_cents
    min_sweep = int(config.repo_min_sweep_usd * 100)

    if od > 0:
        raise HTTPException(status_code=409, detail="OD_OUTSTANDING")
    if queue > 0:
        raise HTTPException(status_code=409, detail="PAYOUT_QUEUE_OUTSTANDING")
    if amount > surplus:
        raise HTTPException(status_code=422, detail="SWEEP_EXCEEDS_SURPLUS")
    if amount < min_sweep:
        raise HTTPException(status_code=422, detail="BELOW_MIN")

    # Execute
    ts = str(dataset_df.iloc[active_engine.current_step]["timestamp"])
    from backend.app.ledger.journal import create_repo_sweep_txn
    from backend.app.settlement.repo import RepoPosition

    txn = create_repo_sweep_txn(active_engine.run_id, active_engine.current_step, amount, ts, active_engine._next_seq())
    before = dict(active_engine.ledger.balances)
    active_engine.ledger.post_transaction(txn)

    pos_id = f"manual_repo_{active_engine.current_step}_{active_engine._next_seq()}"
    new_repo = RepoPosition(
        position_id=pos_id,
        opened_step=active_engine.current_step,
        opened_ts=ts,
        principal_cents=amount,
        rate_apy_pct=float(dataset_df.iloc[active_engine.current_step]["tier1_repo_rate_apy"]),
        maturity_step=active_engine.current_step + config.repo_tenor_hours,
        haircut_pct=float(dataset_df.iloc[active_engine.current_step]["tier1_early_redemption_haircut_pct"]),
    )
    active_engine.open_repos.append(new_repo)

    rec = active_engine.audit.append_record(
        active_engine.current_step, "MANUAL_SWEEP_EXECUTED", "LEDGER_TXN", txn.txn_id,
        {"amount_cents": amount, "tier": req.tier}, before, dict(active_engine.ledger.balances), "MANUAL_TREASURER_SWEEP"
    )

    return {
        "status": "EXECUTED",
        "txn_id": txn.txn_id,
        "amount_cents": str(amount),
        "audit_seq": rec.seq,
    }


@app.post("/api/v1/sim/runs/{run_id}/reset")
def reset_simulation(run_id: str):
    global active_engine
    active_engine = SimulationEngine(
        config=config,
        dataset=dataset_df,
        data_hash=quality_report["data_hash"],
        run_id=run_id,
    )
    return {"status": "RESET", "run_id": run_id, "step": 0}


class BacktestRunRequest(BaseModel):
    horizon_steps: int = 168
    strategies: List[str] = ["B0_CASH", "B1_FIXED", "B2_CONSERVATIVE", "B3_DYNAMIC", "B4_CHALLENGE"]
    evaluation_policy: str = "as_of_only"


@app.post("/api/v1/backtests")
def run_backtest_endpoint(req: BacktestRunRequest):
    from backend.app.backtest.runner import run_strategy_backtest
    results = []
    for strat in req.strategies:
        res = run_strategy_backtest(
            df=dataset_df,
            data_hash=quality_report["data_hash"],
            base_config=config,
            strategy_id=strat,
            horizon_steps=req.horizon_steps,
            evaluation_policy=req.evaluation_policy,
        )
        results.append(res.model_dump())
    return {"results": results, "horizon_steps": req.horizon_steps}


@app.get("/api/v1/stress/scenarios")
def get_stress_scenarios():
    return [
        {"id": "OUTFLOW_MULT", "name": "3x Outflow Multiplier", "params": {"multiplier": 3.0, "duration_hours": 6}},
        {"id": "WITHDRAWAL_SPIKE", "name": "$150M Withdrawal Spike", "params": {"amount_usd": 150_000_000.0, "duration_hours": 1}},
        {"id": "DELAYED_DEPOSITS", "name": "Delayed Deposits (6h)", "params": {"delay_hours": 6, "duration_hours": 6}},
        {"id": "REPO_UNAVAILABLE", "name": "Repo Lockout (48h)", "params": {"duration_hours": 48}},
        {"id": "LIQUIDATION_DELAY", "name": "+48h Liquidation Lag", "params": {"duration_hours": 48}},
        {"id": "BOND_SHOCK", "name": "+150bp Bond Yield Shock", "params": {"yield_shock_bp": 150.0, "duration_hours": 4}},
        {"id": "EQUITY_CRASH", "name": "-25% Equity Crash", "params": {"equity_crash_pct": -25.0, "duration_hours": 24}},
        {"id": "CORRELATED_RUN", "name": "Correlated Run (Outflows + Market Crash)", "params": {"duration_hours": 12}},
        {"id": "OVERDRAFT_RESTRICTED", "name": "Overdraft Restricted (0.25x limit)", "params": {"od_limit_mult": 0.25, "duration_hours": 24}},
        {"id": "COMBINED_WORST", "name": "Combined Worst-Case Drill", "params": {"duration_hours": 24}},
    ]


class StressRunRequest(BaseModel):
    scenario_id: str
    start_step: int = 17
    duration_hours: int = 12


@app.post("/api/v1/stress/events")
def run_stress_endpoint(req: StressRunRequest):
    from backend.app.stress.engine import StressScenarioParams, run_stress_scenario
    params = StressScenarioParams(scenario_id=req.scenario_id, start_step=req.start_step, duration_hours=req.duration_hours)
    rep = run_stress_scenario(
        base_df=dataset_df,
        data_hash=quality_report["data_hash"],
        base_config=config,
        params=params,
        horizon_steps=48,
    )
    return rep.model_dump()


# Mount frontend static files if directory exists
from fastapi.staticfiles import StaticFiles
if os.path.exists("frontend"):
    app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")

