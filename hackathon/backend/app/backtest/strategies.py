from __future__ import annotations
from typing import Dict, Any, Optional
import math
import pandas as pd
from backend.app.core.config import TreasuryConfig
from backend.app.simulation.engine import SimulationEngine
from backend.app.settlement.repo import RepoPosition
from backend.app.ledger.journal import create_repo_sweep_txn


class StrategyPolicy:
    def __init__(self, strategy_id: str, config: TreasuryConfig):
        self.strategy_id = strategy_id
        self.config = config

    def decide_sweep(
        self,
        engine: SimulationEngine,
        row: pd.Series,
        step_idx: int,
    ) -> Dict[str, Any]:
        """Decides sweep amount and tier for the current step."""
        is_sweep_window = bool(row["repo_sweep_window_open"])
        if not is_sweep_window:
            return {"decision": "NO_ACTION", "amount_cents": 0, "reason": "WINDOW_CLOSED"}

        # Universal Guardrails across all strategies:
        # Never invest while overdraft or payout queue is outstanding
        if engine.ledger.get_balance("OVERDRAFT") > 0:
            return {"decision": "NO_ACTION", "amount_cents": 0, "reason": "OD_OUTSTANDING"}
        if engine.payout_queue.total_outstanding_cents > 0:
            return {"decision": "NO_ACTION", "amount_cents": 0, "reason": "PAYOUT_QUEUE_OUTSTANDING"}

        cash = engine.ledger.get_balance("CASH")
        min_sweep_cents = int(self.config.repo_min_sweep_usd * 100)

        # --- B0: Reference (All Cash) ---
        if self.strategy_id == "B0_CASH":
            return {"decision": "NO_ACTION", "amount_cents": 0, "reason": "B0_REFERENCE_ALL_CASH"}

        # --- B1: Fixed Reserve (10% of portfolio value) ---
        elif self.strategy_id == "B1_FIXED":
            total_portfolio = cash + engine.ledger.get_balance("REPO")
            reserve_floor = int(total_portfolio * 0.10)
            surplus = max(0, cash - reserve_floor)
            if surplus < min_sweep_cents:
                return {"decision": "NO_ACTION", "amount_cents": 0, "reason": "BELOW_MIN"}
            return {"decision": "SWEEP_EXECUTED", "amount_cents": surplus, "reason": "B1_FIXED_RESERVE_SURPLUS"}

        # --- B2: Conservative Liquidity-First ---
        elif self.strategy_id == "B2_CONSERVATIVE":
            # 1.25 * historical 24h peak cumulative outflow
            # In dataset, historical 24h peak cumulative outflow is ~$123.5M
            conservative_reserve = int(123_500_000_00 * 1.25)  # ~$154.38M
            surplus = max(0, cash - conservative_reserve)
            if surplus < min_sweep_cents:
                return {"decision": "NO_ACTION", "amount_cents": 0, "reason": "BELOW_MIN"}
            return {"decision": "SWEEP_EXECUTED", "amount_cents": surplus, "reason": "B2_CONSERVATIVE_SURPLUS"}

        # --- B3: Dynamic (PRD Section 6) ---
        elif self.strategy_id == "B3_DYNAMIC":
            reserves = engine.calculate_reserves(step_idx)
            surplus = reserves["sweepable_surplus_cents"]
            if surplus < min_sweep_cents:
                return {"decision": "NO_ACTION", "amount_cents": 0, "reason": "BELOW_MIN"}
            
            # 70% repo portfolio cap check
            total_portfolio = cash + engine.ledger.get_balance("REPO")
            max_repo = int(total_portfolio * (self.config.repo_max_pct_of_portfolio / 100.0))
            room = max(0, max_repo - engine.ledger.get_balance("REPO"))
            amount = min(surplus, room)

            post_cash = cash - amount
            if post_cash < reserves["f_hard_cents"]:
                amount = max(0, cash - reserves["f_hard_cents"])

            if amount < min_sweep_cents:
                return {"decision": "NO_ACTION", "amount_cents": 0, "reason": "CAP_OR_FLOOR_CONSTRAINT"}

            return {"decision": "SWEEP_EXECUTED", "amount_cents": amount, "reason": "B3_DYNAMIC_SAFE_SURPLUS"}

        # --- B4: Challenge Benchmark (5% Fixed Vault) ---
        elif self.strategy_id == "B4_CHALLENGE":
            total_portfolio = cash + engine.ledger.get_balance("REPO")
            reserve_floor = int(self.config.min_cash_floor_usd * 100)
            surplus = max(0, cash - reserve_floor)
            if surplus < min_sweep_cents:
                return {"decision": "NO_ACTION", "amount_cents": 0, "reason": "BELOW_MIN"}
            return {"decision": "SWEEP_EXECUTED", "amount_cents": surplus, "reason": "B4_VAULT_5PCT_SURPLUS"}

        return {"decision": "NO_ACTION", "amount_cents": 0, "reason": "UNKNOWN_STRATEGY"}
