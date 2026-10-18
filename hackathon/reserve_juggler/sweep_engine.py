"""Sweep Engine: executes idempotent sweeps, manages rolling vault tranches, and liquidity hierarchy."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import math

from reserve_juggler.config import CONFIG, to_cents
from reserve_juggler.ledger import DoubleEntryLedger
from reserve_juggler.models import EngineMode, LedgerAccount, VaultTranche


@dataclass
class SweepDecision:
    cycle_index: int
    idempotency_key: str
    cash_before_cents: int
    required_cushion_cents: int
    headroom_cents: int
    sweep_amount_cents: int
    action_taken: str  # SWEEP, HOLD, MIN_THRESHOLD_HOLD, FAILSAFE_HOLD, PAUSED_HOLD, KILLED_HOLD
    reason: str
    tranche_created_id: Optional[str] = None


class SweepEngine:
    def __init__(self, ledger: DoubleEntryLedger) -> None:
        self.ledger = ledger
        self.active_tranches: List[VaultTranche] = []
        self.all_tranches: List[VaultTranche] = []
        # Idempotency cache: idempotency_key -> SweepDecision
        self.idempotency_cache: Dict[str, SweepDecision] = {}
        self.total_early_breaks_count: int = 0
        self.total_emergency_draws_count: int = 0
        self.total_delayed_payouts_count: int = 0

    def process_tranche_maturities(
        self, current_bucket: int, timestamp: Optional[datetime] = None
    ) -> List[VaultTranche]:
        """Release maturing vault tranches into cash buffer with accrued 5% APY yield."""
        matured: List[VaultTranche] = []
        for tranche in list(self.active_tranches):
            if current_bucket >= tranche.mature_bucket and tranche.status == "ACTIVE":
                duration_buckets = max(1, tranche.mature_bucket - tranche.start_bucket)
                yield_factor = (1.0 + CONFIG.VAULT_APY) ** (
                    duration_buckets / (365.0 * CONFIG.BUCKETS_PER_DAY)
                ) - 1.0
                yield_cents = int(round(tranche.principal_cents * yield_factor))

                tranche.status = "MATURED"
                tranche.accrued_yield_cents = yield_cents
                self.active_tranches.remove(tranche)
                matured.append(tranche)

                # Record in ledger
                self.ledger.record_vault_maturity(
                    principal_cents=tranche.principal_cents,
                    yield_cents=yield_cents,
                    timestamp=timestamp,
                )
        return matured

    def execute_cycle_sweep(
        self,
        cycle_index: int,
        required_buffer_cents: int,
        engine_mode: EngineMode = EngineMode.NORMAL,
        idempotency_key: Optional[str] = None,
        manual_override_sweep_cents: Optional[int] = None,
        timestamp: Optional[datetime] = None,
    ) -> SweepDecision:
        """Evaluate and execute the sweep decision for the current 15-minute cycle."""
        key = idempotency_key or f"SWEEP-CYCLE-{cycle_index}"

        # Idempotency check: if key was already executed, return cached decision
        if key in self.idempotency_cache:
            return self.idempotency_cache[key]

        cash_now = self.ledger.get_balance(LedgerAccount.CASH_BUFFER)
        headroom = cash_now - required_buffer_cents

        # Check Fail-Safe / Kill-switch / Paused modes
        if engine_mode == EngineMode.KILLED:
            decision = SweepDecision(
                cycle_index=cycle_index,
                idempotency_key=key,
                cash_before_cents=cash_now,
                required_cushion_cents=required_buffer_cents,
                headroom_cents=headroom,
                sweep_amount_cents=0,
                action_taken="KILLED_HOLD",
                reason="Engine kill-switch is active. Sweeps blocked, holding all cash in buffer.",
            )
            self.idempotency_cache[key] = decision
            return decision

        if engine_mode == EngineMode.FAILSAFE:
            decision = SweepDecision(
                cycle_index=cycle_index,
                idempotency_key=key,
                cash_before_cents=cash_now,
                required_cushion_cents=required_buffer_cents,
                headroom_cents=headroom,
                sweep_amount_cents=0,
                action_taken="FAILSAFE_HOLD",
                reason="Fail-safe activated (stale data or forecaster error). Holding all cash.",
            )
            self.idempotency_cache[key] = decision
            return decision

        if engine_mode == EngineMode.PAUSED:
            decision = SweepDecision(
                cycle_index=cycle_index,
                idempotency_key=key,
                cash_before_cents=cash_now,
                required_cushion_cents=required_buffer_cents,
                headroom_cents=headroom,
                sweep_amount_cents=0,
                action_taken="PAUSED_HOLD",
                reason="Treasury sweeps paused by operator.",
            )
            self.idempotency_cache[key] = decision
            return decision

        # Manual override
        if manual_override_sweep_cents is not None and manual_override_sweep_cents > 0:
            sweep_amount = min(manual_override_sweep_cents, max(0, cash_now - required_buffer_cents))
            if sweep_amount > 0:
                tranche = VaultTranche(
                    tranche_id=f"TRANCHE-M-{cycle_index}",
                    principal_cents=sweep_amount,
                    start_bucket=cycle_index,
                    mature_bucket=cycle_index + CONFIG.VAULT_TRANCHE_HORIZON_BUCKETS,
                )
                self.active_tranches.append(tranche)
                self.all_tranches.append(tranche)
                self.ledger.record_sweep_to_vault(sweep_amount, timestamp=timestamp)
                decision = SweepDecision(
                    cycle_index=cycle_index,
                    idempotency_key=key,
                    cash_before_cents=cash_now,
                    required_cushion_cents=required_buffer_cents,
                    headroom_cents=headroom,
                    sweep_amount_cents=sweep_amount,
                    action_taken="MANUAL_SWEEP",
                    reason=f"Operator manual sweep override executed: {sweep_amount} cents",
                    tranche_created_id=tranche.tranche_id,
                )
                self.idempotency_cache[key] = decision
                return decision

        # Standard Sweep Rule:
        # sweep = max(0, cash_now - required_buffer - margin)
        excess_cash = cash_now - required_buffer_cents - CONFIG.safety_margin_cents
        potential_sweep = max(0, excess_cash)

        # Rule: Skip sweeps below configurable minimum
        if potential_sweep < CONFIG.min_sweep_cents:
            action = "MIN_THRESHOLD_HOLD" if potential_sweep > 0 else "HOLD"
            reason = (
                f"Potential sweep {potential_sweep} cents is below minimum {CONFIG.min_sweep_cents} cents."
                if potential_sweep > 0
                else f"Cash buffer ({cash_now} cents) is within or below required cushion + margin."
            )
            decision = SweepDecision(
                cycle_index=cycle_index,
                idempotency_key=key,
                cash_before_cents=cash_now,
                required_cushion_cents=required_buffer_cents,
                headroom_cents=headroom,
                sweep_amount_cents=0,
                action_taken=action,
                reason=reason,
            )
            self.idempotency_cache[key] = decision
            return decision

        # Rule: Never touch cash below required buffer
        sweep_amount = min(potential_sweep, max(0, cash_now - required_buffer_cents))

        # Execute sweep and create rolling vault tranche
        tranche = VaultTranche(
            tranche_id=f"TRANCHE-{cycle_index:06d}",
            principal_cents=sweep_amount,
            start_bucket=cycle_index,
            mature_bucket=cycle_index + CONFIG.VAULT_TRANCHE_HORIZON_BUCKETS,
        )
        self.active_tranches.append(tranche)
        self.all_tranches.append(tranche)
        self.ledger.record_sweep_to_vault(sweep_amount, timestamp=timestamp)

        decision = SweepDecision(
            cycle_index=cycle_index,
            idempotency_key=key,
            cash_before_cents=cash_now,
            required_cushion_cents=required_buffer_cents,
            headroom_cents=headroom,
            sweep_amount_cents=sweep_amount,
            action_taken="SWEEP",
            reason=f"Swept {sweep_amount} cents into 24h Yield Vault tranche {tranche.tranche_id}.",
            tranche_created_id=tranche.tranche_id,
        )
        self.idempotency_cache[key] = decision
        return decision

    def handle_liquidity_shortfall(
        self, shortfall_cents: int, timestamp: Optional[datetime] = None
    ) -> Tuple[int, int, str]:
        """Liquidity hierarchy when cash buffer cannot satisfy an outflow.
        
        Returns:
            (covered_cents, penalty_or_fee_cents, hierarchy_used)
        """
        if shortfall_cents <= 0:
            return 0, 0, "NONE"

        # Tier 1: Vault early withdrawal (2% penalty)
        vault_balance = self.ledger.get_balance(LedgerAccount.YIELD_VAULT)
        if vault_balance > 0:
            penalty_rate = CONFIG.VAULT_EARLY_WITHDRAWAL_PENALTY_RATE
            gross_needed = math.ceil(shortfall_cents / (1.0 - penalty_rate))
            break_amount = min(gross_needed, vault_balance)
            penalty_cents = int(round(break_amount * penalty_rate))
            net_recovered = break_amount - penalty_cents

            # Deduct from active tranches starting from most recent
            remaining_to_deduct = break_amount
            for tr in reversed(self.active_tranches):
                if remaining_to_deduct <= 0:
                    break
                deduct = min(tr.principal_cents, remaining_to_deduct)
                tr.principal_cents -= deduct
                remaining_to_deduct -= deduct
                if tr.principal_cents == 0:
                    tr.status = "BROKEN_EARLY"

            self.active_tranches = [
                t for t in self.active_tranches if t.status == "ACTIVE" and t.principal_cents > 0
            ]

            self.ledger.record_vault_early_break(
                gross_principal_cents=break_amount,
                penalty_cents=penalty_cents,
                timestamp=timestamp,
            )
            self.total_early_breaks_count += 1

            if net_recovered >= shortfall_cents:
                return net_recovered, penalty_cents, "TIER1_VAULT_EARLY_BREAK"
            shortfall_cents -= net_recovered

        # Tier 2: Emergency overdraft loan (18% APR + $500 flat fee)
        fee_cents = CONFIG.emergency_loan_flat_fee_cents
        self.ledger.record_emergency_loan_draw(
            principal_cents=shortfall_cents,
            flat_fee_cents=fee_cents,
            timestamp=timestamp,
        )
        self.total_emergency_draws_count += 1
        return shortfall_cents, fee_cents, "TIER2_EMERGENCY_OVERDRAFT_LOAN"
