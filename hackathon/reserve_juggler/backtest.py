"""30-Day Simulation Backtest comparing Reserve Juggler against $15M Static Baseline."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import matplotlib.pyplot as plt
import numpy as np

from reserve_juggler.config import CONFIG, to_cents, to_usd
from reserve_juggler.engine import TreasuryEngine
from reserve_juggler.flow_simulator import FlowSimulator, ShockConfig
from reserve_juggler.models import FlowBucket


@dataclass
class BacktestMetrics:
    total_buckets: int
    days_simulated: int
    payout_success_rate: float
    total_payouts_attempted: int
    total_delayed_payouts: int
    emergency_loan_draws: int
    emergency_loan_interest_fees_usd: float
    early_withdrawal_penalties_usd: float
    avg_idle_cash_juggler_usd: float
    avg_idle_cash_baseline_usd: float
    idle_cash_reduction_pct: float
    net_yield_juggler_usd: float
    net_yield_baseline_usd: float
    net_yield_alpha_usd: float
    overall_wape: float
    peak_day_wape: float
    audit_chain_verified: bool


def run_30day_backtest(
    seed: int = 42,
    output_chart_path: str = "backtest_results.png",
) -> Tuple[BacktestMetrics, TreasuryEngine]:
    """Execute complete 30-day simulation with paydays, shopping holiday, and 3x shock."""
    start_time = datetime(2026, 10, 1, 0, 0, 0)
    num_days = 30
    total_buckets = num_days * CONFIG.BUCKETS_PER_DAY  # 2,880 buckets

    # 1. Initialize Simulator with calendar spikes
    sim = FlowSimulator(start_time=start_time, seed=seed)

    # 2. Inject unannounced 2-hour shock (3x withdrawal surge) on Day 18 at 14:00
    shock_start_bucket = 18 * CONFIG.BUCKETS_PER_DAY + 14 * CONFIG.BUCKETS_PER_HOUR  # bucket 1784
    sim.add_shock(
        ShockConfig(
            start_bucket=shock_start_bucket,
            duration_buckets=8,  # 2 hours = 8 * 15m
            outflow_multiplier=3.0,
            inflow_multiplier=1.0,
            description="Day 18 Flash Outflow Shock: 3x withdrawal surge for 2 hours",
        )
    )

    # 3. Generate all 30 days of flow buckets
    buckets = sim.generate_series(total_buckets)

    # 4. Initialize Treasury Engine
    engine = TreasuryEngine(start_time=start_time)

    # Track metrics over time
    peak_day_wapes: List[float] = []

    for idx, bucket in enumerate(buckets):
        engine.step(bucket)

        # Track WAPE on peak days: Day 1, 15 (paydays), Day 18 (shock), Day 25 (holiday)
        day_num = (idx // CONFIG.BUCKETS_PER_DAY) + 1
        if day_num in (1, 15, 18, 25) and idx % CONFIG.BUCKETS_PER_DAY == CONFIG.BUCKETS_PER_DAY - 1:
            peak_day_wapes.append(engine.forecaster.combined_wape)

    # 5. Verify Immutable Audit Chain
    chain_valid = engine.audit_logger.verify_chain_integrity()

    # 6. Compute Aggregated Metrics
    avg_idle_juggler = float(np.mean(engine.history_idle_cash)) / 100.0
    avg_idle_baseline = float(np.mean(engine.baseline.idle_cash_samples)) / 100.0
    idle_reduction = (avg_idle_baseline - avg_idle_juggler) / avg_idle_baseline * 100.0

    # Get direct accounting balances
    from reserve_juggler.models import LedgerAccount
    yield_income = engine.ledger.get_balance(LedgerAccount.YIELD_INCOME)
    penalties = engine.ledger.get_balance(LedgerAccount.EARLY_WITHDRAWAL_PENALTY_EXPENSE)
    loan_fees = engine.ledger.get_balance(LedgerAccount.LOAN_FEE_EXPENSE)
    loan_interest = engine.ledger.get_balance(LedgerAccount.LOAN_INTEREST_EXPENSE)
    net_yield_juggler_usd = to_usd(yield_income - penalties - loan_fees - loan_interest)
    net_yield_baseline_usd = to_usd(engine.baseline.cumulative_yield_cents)
    net_alpha = net_yield_juggler_usd - net_yield_baseline_usd

    payout_rate = (
        100.0
        if engine.payouts_attempted == 0
        else (engine.payouts_completed / engine.payouts_attempted) * 100.0
    )

    metrics = BacktestMetrics(
        total_buckets=total_buckets,
        days_simulated=num_days,
        payout_success_rate=payout_rate,
        total_payouts_attempted=engine.payouts_attempted,
        total_delayed_payouts=engine.payouts_delayed,
        emergency_loan_draws=engine.sweep_engine.total_emergency_draws_count,
        emergency_loan_interest_fees_usd=to_usd(loan_fees + loan_interest),
        early_withdrawal_penalties_usd=to_usd(penalties),
        avg_idle_cash_juggler_usd=avg_idle_juggler,
        avg_idle_cash_baseline_usd=avg_idle_baseline,
        idle_cash_reduction_pct=idle_reduction,
        net_yield_juggler_usd=net_yield_juggler_usd,
        net_yield_baseline_usd=net_yield_baseline_usd,
        net_yield_alpha_usd=net_alpha,
        overall_wape=round(engine.forecaster.combined_wape, 4),
        peak_day_wape=round(float(np.mean(peak_day_wapes)) if peak_day_wapes else engine.forecaster.combined_wape, 4),
        audit_chain_verified=chain_valid,
    )

    # 7. Generate High-Quality Comparative Chart
    _generate_chart(engine, buckets, output_chart_path)

    return metrics, engine


def _generate_chart(engine: TreasuryEngine, buckets: List[FlowBucket], output_path: str) -> None:
    """Plot Buffer vs Required Buffer vs Cash over time and baseline comparisons."""
    time_hours = np.arange(len(buckets)) * (CONFIG.BUCKET_MINUTES / 60.0)
    cash_usd = np.array(engine.history_cash) / 100.0 / 1e6
    req_buf_usd = np.array(engine.history_required_buffer) / 100.0 / 1e6
    baseline_cash_usd = np.array(engine.baseline.idle_cash_samples) / 100.0 / 1e6
    outflows_usd = np.array([b.outflow_cents for b in buckets]) / 100.0 / 1e6

    # Yield trajectories
    juggler_yield_usd = []
    running_yield = 0.0
    for y_alpha in engine.history_yield_alpha:
        juggler_yield_usd.append(to_usd(y_alpha))

    plt.style.use("seaborn-v0_8-darkgrid" if "seaborn-v0_8-darkgrid" in plt.style.available else "default")
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 12), sharex=True)

    # Plot 1: Cash Buffer vs Required Cushion vs Actual Outflow
    ax1.plot(time_hours, cash_usd, label="Actual Cash Buffer", color="#10B981", linewidth=1.5)
    ax1.plot(time_hours, req_buf_usd, label="Required Cushion (Q_99.9% + Addon + Floor)", color="#F59E0B", linestyle="--", linewidth=1.5)
    ax1.plot(time_hours, outflows_usd, label="15m Outflow", color="#6B7280", alpha=0.3, linewidth=0.8)
    ax1.axvline(x=18 * 24 + 14, color="#EF4444", linestyle=":", label="3x Shock Event (Day 18)")
    ax1.set_ylabel("Buffer & Outflows ($M)", fontsize=11, fontweight="bold")
    ax1.set_title("Reserve Juggler: Dynamic Cash Cushion vs Actual Outflows (30 Days)", fontsize=13, fontweight="bold")
    ax1.legend(loc="upper right", frameon=True)
    ax1.grid(True, alpha=0.3)

    # Plot 2: Idle Cash Comparison (Reserve Juggler vs $15M Fixed Baseline)
    ax2.plot(time_hours, baseline_cash_usd, label="Fixed Baseline ($15M)", color="#EF4444", linestyle="-", linewidth=1.8)
    ax2.plot(time_hours, cash_usd, label="Reserve Juggler Dynamic Cash", color="#3B82F6", linewidth=1.5)
    ax2.fill_between(time_hours, cash_usd, baseline_cash_usd, color="#3B82F6", alpha=0.15, label="Idle Cash Freed for Yield Vault")
    ax2.set_ylabel("Idle Cash ($M)", fontsize=11, fontweight="bold")
    ax2.set_title("Idle Cash Comparison (Target: >= 60% Reduction)", fontsize=13, fontweight="bold")
    ax2.legend(loc="upper right", frameon=True)
    ax2.grid(True, alpha=0.3)

    # Plot 3: Cumulative Net Yield Alpha ($)
    cumulative_juggler_yield = np.cumsum(np.array(engine.history_cash)) * 0  # placeholder to build series
    # Cumulative yield of juggler vs baseline
    # Cumulative vault balances
    j_vault = np.array(engine.history_vault) / 100.0
    b_yield = np.linspace(0, engine.baseline.cumulative_yield_cents / 100.0, len(buckets))
    # True net yield over time
    j_yield = b_yield + np.array(engine.history_yield_alpha) / 100.0

    ax3.plot(time_hours, j_yield, label="Reserve Juggler Net Yield ($)", color="#10B981", linewidth=2.0)
    ax3.plot(time_hours, b_yield, label="Static Baseline Net Yield ($)", color="#9CA3AF", linestyle="--", linewidth=1.5)
    ax3.set_xlabel("Simulation Elapsed Time (Hours)", fontsize=11, fontweight="bold")
    ax3.set_ylabel("Cumulative Yield ($)", fontsize=11, fontweight="bold")
    ax3.set_title("Cumulative Yield Earned: Dynamic Sweeping Alpha", fontsize=13, fontweight="bold")
    ax3.legend(loc="upper left", frameon=True)
    ax3.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()
