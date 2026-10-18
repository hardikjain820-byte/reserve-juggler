from __future__ import annotations
import math
from typing import Dict, List, Optional, Any, Tuple
import pandas as pd
from pydantic import BaseModel, Field

from backend.app.core.config import TreasuryConfig
from backend.app.simulation.engine import SimulationEngine
from backend.app.settlement.repo import RepoPosition
from backend.app.ledger.reconciliation import LiabilityLimitExceededError, ReconciliationError
from backend.app.ledger.journal import create_repo_sweep_txn
from backend.app.backtest.strategies import StrategyPolicy


class BacktestResult(BaseModel):
    strategy_id: str
    status: str  # 'COMPLETED', 'TERMINATED_ECONOMIC_LIMIT'
    steps_completed: int
    total_steps_planned: int
    completion_fraction: float
    termination_reason: Optional[str] = None
    
    # Financial metrics
    payout_success_steps_pct: float
    payout_success_usd_pct: float
    delayed_payout_events: int
    total_delayed_payout_usd: float
    overdraft_draws_count: int
    overdraft_peak_usd: float
    overdraft_interest_paid_usd: float
    early_redemption_penalty_usd: float
    gross_yield_usd: float
    net_yield_usd: float
    avg_cash_usd: float
    net_excess_return_vs_b1_usd: float = 0.0


def run_strategy_backtest(
    df: pd.DataFrame,
    data_hash: str,
    base_config: TreasuryConfig,
    strategy_id: str,
    horizon_steps: Optional[int] = None,
    evaluation_policy: str = "as_of_only",
) -> BacktestResult:
    """Executes a walk-forward backtest for a strategy using the exact same underlying
    double-entry ledger engine and transaction order.
    """
    cfg = base_config.model_copy(deep=True)
    
    # 1. Enforce As-Of Cutoff
    as_of_dt = pd.to_datetime(cfg.as_of_timestamp).tz_localize(None)
    if evaluation_policy == "as_of_only":
        eligible_df = df[pd.to_datetime(df["timestamp"]) <= as_of_dt].copy()
    else:
        eligible_df = df.copy()

    total_steps = len(eligible_df) if horizon_steps is None else min(len(eligible_df), horizon_steps)
    
    engine = SimulationEngine(
        config=cfg,
        dataset=eligible_df,
        data_hash=data_hash,
        run_id=f"bt_{strategy_id}_{total_steps}",
    )
    policy = StrategyPolicy(strategy_id=strategy_id, config=cfg)

    steps_done = 0
    termination_reason = None
    cash_snapshots: List[int] = []
    peak_od_cents = 0
    od_draw_count = 0
    prev_od_cents = 0

    try:
        for s_idx in range(total_steps):
            row = eligible_df.iloc[s_idx]
            ts = str(row["timestamp"])

            # 1. Accrue Overdraft Interest
            od_bal = engine.ledger.get_balance("OVERDRAFT")
            if od_bal > 0:
                od_apr = cfg.emergency_overdraft_penalty_apr_pct / 100.0
                od_interest = math.floor(od_bal * od_apr * (1.0 / 8760.0))
                if od_interest > 0:
                    from backend.app.ledger.journal import create_overdraft_interest_txn
                    txn = create_overdraft_interest_txn(engine.run_id, s_idx, od_interest, ts, engine._next_seq())
                    engine.ledger.post_transaction(txn)

            # 2. Apply Repo Maturities
            if bool(row["repo_sweep_mature"]) and engine.open_repos:
                maturing = [r for r in engine.open_repos if r.status == "OPEN"]
                for repo in maturing:
                    interest = repo.calculate_interest(cfg.repo_tenor_hours)
                    from backend.app.ledger.journal import create_repo_maturity_txn
                    txn = create_repo_maturity_txn(engine.run_id, s_idx, repo.principal_cents, interest, ts, engine._next_seq())
                    engine.ledger.post_transaction(txn)
                    repo.status = "MATURED"
                engine.open_repos = [r for r in engine.open_repos if r.status == "OPEN"]

            # 3. Apply Inflows (Deposits)
            dep_cents = int(round(float(row["deposits_usd"]) * 100))
            from backend.app.ledger.journal import create_deposit_txn
            txn_dep = create_deposit_txn(engine.run_id, s_idx, dep_cents, ts, engine._next_seq())
            engine.ledger.post_transaction(txn_dep)

            # 4. Outflow Waterfall
            # 4a. FIFO Payout Queue settlement
            cur_cash = engine.ledger.get_balance("CASH")
            if cur_cash > 0 and engine.payout_queue.total_outstanding_cents > 0:
                used, _ = engine.payout_queue.pay_fifo(cur_cash)
                if used > 0:
                    from backend.app.ledger.journal import create_queued_payout_paid_txn
                    txn_q = create_queued_payout_paid_txn(engine.run_id, s_idx, used, ts, engine._next_seq())
                    engine.ledger.post_transaction(txn_q)

            # 4b. Current Obligation
            wd_cents = int(round(float(row["withdrawals_usd"]) * 100))
            engine.total_withdrawals_requested_cents += wd_cents
            rem_obl = wd_cents

            # Pay from Cash
            cash_avail = engine.ledger.get_balance("CASH")
            pay_c = min(cash_avail, rem_obl)
            if pay_c > 0:
                from backend.app.ledger.journal import create_immediate_withdrawal_txn
                txn_w = create_immediate_withdrawal_txn(engine.run_id, s_idx, pay_c, ts, engine._next_seq())
                engine.ledger.post_transaction(txn_w)
                rem_obl -= pay_c
                engine.total_withdrawals_paid_cents += pay_c

            # Early Repo Redemption
            if rem_obl > 0 and engine.open_repos:
                for repo in list(engine.open_repos):
                    if rem_obl <= 0:
                        break
                    if repo.status != "OPEN":
                        continue
                    red = repo.calculate_early_redemption()
                    from backend.app.ledger.journal import create_repo_early_redemption_txn, create_immediate_withdrawal_txn
                    txn_red = create_repo_early_redemption_txn(engine.run_id, s_idx, red["principal_cents"], red["haircut_cents"], ts, engine._next_seq())
                    engine.ledger.post_transaction(txn_red)
                    repo.status = "EARLY_REDEEMED"
                    
                    p_repo = min(red["net_proceeds_cents"], rem_obl)
                    txn_pw = create_immediate_withdrawal_txn(engine.run_id, s_idx, p_repo, ts, engine._next_seq())
                    engine.ledger.post_transaction(txn_pw)
                    rem_obl -= p_repo
                    engine.total_withdrawals_paid_cents += p_repo

                engine.open_repos = [r for r in engine.open_repos if r.status == "OPEN"]

            # Overdraft
            if rem_obl > 0:
                od_lim = int(cfg.overdraft_limit_usd * 100)
                cur_od = engine.ledger.get_balance("OVERDRAFT")
                room = max(0, od_lim - cur_od)
                draw = min(rem_obl, room)
                if draw > 0:
                    from backend.app.ledger.journal import create_overdraft_draw_txn, create_immediate_withdrawal_txn
                    txn_od = create_overdraft_draw_txn(engine.run_id, s_idx, draw, ts, engine._next_seq())
                    engine.ledger.post_transaction(txn_od)
                    txn_p = create_immediate_withdrawal_txn(engine.run_id, s_idx, draw, ts, engine._next_seq())
                    engine.ledger.post_transaction(txn_p)
                    rem_obl -= draw
                    engine.total_withdrawals_paid_cents += draw
                    od_draw_count += 1

            # Payout Queue
            if rem_obl > 0:
                engine.payout_failure_events += 1
                qid = f"queue_{s_idx}_{engine._next_seq()}"
                engine.payout_queue.enqueue(qid, s_idx, rem_obl)
                from backend.app.ledger.journal import create_queue_transfer_txn
                txn_qt = create_queue_transfer_txn(engine.run_id, s_idx, rem_obl, ts, engine._next_seq())
                engine.ledger.post_transaction(txn_qt)

            # Repay Overdraft
            scash = engine.ledger.get_balance("CASH")
            cod = engine.ledger.get_balance("OVERDRAFT")
            if scash > 0 and cod > 0:
                repay = min(scash, cod)
                from backend.app.ledger.journal import create_overdraft_repay_txn
                txn_rp = create_overdraft_repay_txn(engine.run_id, s_idx, repay, ts, engine._next_seq())
                engine.ledger.post_transaction(txn_rp)

            # Track Overdraft Peak
            now_od = engine.ledger.get_balance("OVERDRAFT")
            peak_od_cents = max(peak_od_cents, now_od)

            # 5. Sweep Decision
            decision = policy.decide_sweep(engine, row, s_idx)
            if decision["decision"] == "SWEEP_EXECUTED":
                swp_amt = decision["amount_cents"]
                txn_swp = create_repo_sweep_txn(engine.run_id, s_idx, swp_amt, ts, engine._next_seq())
                engine.ledger.post_transaction(txn_swp)

                # B4 uses fixed 5.00% APY vault, other strategies use CSV repo APY
                rate = 5.00 if strategy_id == "B4_CHALLENGE" else float(row["tier1_repo_rate_apy"])
                pos = RepoPosition(
                    position_id=f"pos_{strategy_id}_{s_idx}",
                    opened_step=s_idx,
                    opened_ts=ts,
                    principal_cents=swp_amt,
                    rate_apy_pct=rate,
                    maturity_step=s_idx + cfg.repo_tenor_hours,
                    haircut_pct=float(row["tier1_early_redemption_haircut_pct"]),
                )
                engine.open_repos.append(pos)

            # Reconcile Ledger at Every Step!
            engine.ledger.reconcile()

            cash_snapshots.append(engine.ledger.get_balance("CASH"))
            steps_done += 1

    except LiabilityLimitExceededError as e:
        termination_reason = f"LIABILITY_LIMIT_EXCEEDED: {str(e)}"
    except ReconciliationError as e:
        termination_reason = f"RECONCILIATION_FAILED: {str(e)}"

    status = "COMPLETED" if steps_done == total_steps else "TERMINATED_ECONOMIC_LIMIT"

    # Compute Final Performance Metrics
    total_req = engine.total_withdrawals_requested_cents
    total_paid = engine.total_withdrawals_paid_cents
    usd_success = (total_paid / total_req * 100.0) if total_req > 0 else 100.0
    steps_success = ((steps_done - engine.payout_failure_events) / steps_done * 100.0) if steps_done > 0 else 100.0

    gross_yield = engine.ledger.get_balance("REPO_INTEREST")
    od_interest = engine.ledger.get_balance("OD_INTEREST")
    red_cost = engine.ledger.get_balance("EARLY_REDEMPTION_COST")
    net_yield = gross_yield - od_interest - red_cost

    avg_cash = sum(cash_snapshots) / len(cash_snapshots) if cash_snapshots else 0.0

    return BacktestResult(
        strategy_id=strategy_id,
        status=status,
        steps_completed=steps_done,
        total_steps_planned=total_steps,
        completion_fraction=round(steps_done / total_steps, 4) if total_steps > 0 else 0.0,
        termination_reason=termination_reason,
        payout_success_steps_pct=round(steps_success, 4),
        payout_success_usd_pct=round(usd_success, 4),
        delayed_payout_events=engine.payout_failure_events,
        total_delayed_payout_usd=engine.payout_queue.total_outstanding_cents / 100.0,
        overdraft_draws_count=od_draw_count,
        overdraft_peak_usd=peak_od_cents / 100.0,
        overdraft_interest_paid_usd=od_interest / 100.0,
        early_redemption_penalty_usd=red_cost / 100.0,
        gross_yield_usd=gross_yield / 100.0,
        net_yield_usd=net_yield / 100.0,
        avg_cash_usd=avg_cash / 100.0,
    )
