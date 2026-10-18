"""FastAPI application for Reserve Juggler live dashboard and treasury controls."""

import asyncio
from datetime import datetime
import os
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from reserve_juggler.config import CONFIG, to_cents, to_usd
from reserve_juggler.engine import TreasuryEngine
from reserve_juggler.flow_simulator import FlowSimulator, ShockConfig
from reserve_juggler.models import ControlActionRequest, EngineMode, FlowBucket, TelemetryDTO

app = FastAPI(
    title="Reserve Juggler Treasury Engine",
    description="Real-Time Digital Bank Treasury Engine Simulator with Live Dynamic Cushion Dashboard",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global Engine & Simulator state
SIMULATOR = FlowSimulator(start_time=datetime(2026, 10, 1, 0, 0, 0), seed=42)
ENGINE = TreasuryEngine(start_time=datetime(2026, 10, 1, 0, 0, 0))

# Live background simulation task state
IS_LIVE_RUNNING = False
LIVE_TASK: Optional[asyncio.Task] = None
LIVE_SPEED_SECONDS = 0.8  # 1 bucket every 0.8s in live demo mode


async def live_simulation_loop():
    global IS_LIVE_RUNNING
    bucket_idx = ENGINE.current_cycle
    while IS_LIVE_RUNNING:
        bucket_idx += 1
        bucket = SIMULATOR.generate_bucket(bucket_idx)
        ENGINE.step(bucket)
        await asyncio.sleep(LIVE_SPEED_SECONDS)


@app.on_event("startup")
async def startup_event():
    # Warm up engine with initial 24 hours (96 buckets) of realistic history
    global SIMULATOR, ENGINE
    init_buckets = SIMULATOR.generate_series(96)
    for b in init_buckets:
        ENGINE.step(b)


@app.get("/api/telemetry", response_model=TelemetryDTO)
def get_telemetry():
    """Fetch current real-time telemetry, balances, forecast fan chart, and audit log."""
    return ENGINE.get_telemetry()


@app.post("/api/control")
def execute_control(req: ControlActionRequest):
    """Execute operator treasury actions: pause, resume, kill, reset_kill, manual_sweep, set_addon, inject_shock, live."""
    global IS_LIVE_RUNNING, LIVE_TASK

    action = req.action.lower()

    if action == "pause":
        ENGINE.pause()
        return {"status": "success", "mode": ENGINE.mode.value, "message": "Treasury sweeps paused."}

    elif action == "resume":
        ENGINE.resume()
        return {"status": "success", "mode": ENGINE.mode.value, "message": "Treasury sweeps resumed."}

    elif action == "kill":
        ENGINE.trigger_kill_switch()
        return {"status": "success", "mode": ENGINE.mode.value, "message": "Emergency Kill Switch activated! All sweeps blocked."}

    elif action == "reset_kill":
        ENGINE.reset_kill_switch()
        return {"status": "success", "mode": ENGINE.mode.value, "message": "Kill switch reset. Returned to normal mode."}

    elif action == "manual_sweep":
        if not req.amount_usd or req.amount_usd <= 0:
            raise HTTPException(status_code=400, detail="amount_usd must be greater than 0")
        ENGINE.manual_sweep(req.amount_usd)
        return {"status": "success", "message": f"Manual sweep of ${req.amount_usd:,.2f} queued for next cycle."}

    elif action == "set_addon":
        amount = req.amount_usd or 0.0
        ENGINE.set_cushion_addon(amount)
        return {"status": "success", "message": f"Manual cushion add-on set to ${amount:,.2f}."}

    elif action == "step":
        next_idx = ENGINE.current_cycle + 1
        bucket = SIMULATOR.generate_bucket(next_idx)
        audit_rec = ENGINE.step(bucket)
        return {
            "status": "success",
            "cycle": next_idx,
            "decision": audit_rec.decision,
            "sweep_usd": to_usd(audit_rec.sweep_amount_cents),
        }

    elif action == "inject_shock":
        # Inject 3x withdrawal surge for 2 hours (8 buckets) starting immediately
        start_b = ENGINE.current_cycle + 1
        shock = ShockConfig(
            start_bucket=start_b,
            duration_buckets=8,
            outflow_multiplier=3.0,
            inflow_multiplier=1.0,
            description="Operator Inject: 3x withdrawal surge for 2 hours",
        )
        SIMULATOR.add_shock(shock)
        return {"status": "success", "message": f"Injected 3x outflow surge shock starting at cycle {start_b} (2 hours)."}

    elif action == "start_live":
        if not IS_LIVE_RUNNING:
            IS_LIVE_RUNNING = True
            LIVE_TASK = asyncio.create_task(live_simulation_loop())
        return {"status": "success", "is_live": True, "message": "Live simulation playback started."}

    elif action == "stop_live":
        IS_LIVE_RUNNING = False
        if LIVE_TASK:
            LIVE_TASK.cancel()
        return {"status": "success", "is_live": False, "message": "Live simulation playback paused."}

    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {req.action}")


@app.get("/api/audit")
def get_audit_trail():
    """Retrieve full cryptographically verified audit log."""
    is_valid = ENGINE.audit_logger.verify_chain_integrity()
    return {
        "chain_integrity_valid": is_valid,
        "total_records": len(ENGINE.audit_logger.chain),
        "recent_records": [
            {
                "cycle": r.cycle_index,
                "timestamp": r.timestamp,
                "cash_before": to_usd(r.cash_before_cents),
                "vault_before": to_usd(r.vault_before_cents),
                "forecast_p999_deficit": to_usd(r.forecast_p999_max_deficit_cents),
                "required_cushion": to_usd(r.required_cushion_cents),
                "headroom": to_usd(r.headroom_cents),
                "decision": r.decision,
                "sweep_amount": to_usd(r.sweep_amount_cents),
                "reason": r.reason,
                "prev_hash": r.prev_hash,
                "record_hash": r.record_hash,
            }
            for r in ENGINE.audit_logger.get_recent(100)
        ],
    }


@app.get("/api/chart")
def get_backtest_chart():
    chart_path = os.path.join(os.path.dirname(__file__), "backtest_results.png")
    if os.path.exists(chart_path):
        return FileResponse(chart_path, media_type="image/png")
    raise HTTPException(status_code=404, detail="Chart not found. Run backtest first.")


# Mount static directory for UI assets
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", response_class=HTMLResponse)
def serve_index():
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Reserve Juggler: Dashboard UI loading...</h1>"
