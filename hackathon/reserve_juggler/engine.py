"""Central Treasury Orchestrator for Reserve Juggler with live baseline comparison."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from reserve_juggler.audit_logger import AuditLogger
from reserve_juggler.config import CONFIG, to_cents, to_usd
from reserve_juggler.cushion_sizer import CushionSizer
from reserve_juggler.forecaster import Forecaster, StaleDataException
from reserve_juggler.ledger import DoubleEntryLedger
from reserve_juggler.models import (
    AuditRecord,
    EngineMode,
    FlowBucket,
    ForecastHorizonStep,
    LedgerAccount,
    TelemetryDTO,
    VaultTranche,
)
from reserve_juggler.sweep_engine import SweepDecision, SweepEngine


class StaticBaseline:
    """Fixed-buffer treasury strategy for benchmark comparison."""

    def __init__(
        self,
        fixed_buffer_cents: int = CONFIG.static_baseline_buffer_cents,
        initial_vault_cents: int = CONFIG.initial_vault_cents,
    ) -> None:
        self.fixed_buffer_cents = fixed_buffer_cents
        self.cash_buffer_cents: int = fixed_buffer_cents
        self.vault_cents: int = initial_vault_cents
        self.cumulative_yield_cents: int = 0
        self.emergency_draws: int = 0
        self.penalties_paid_cents: int = 0
        self.idle_cash_samples: List[int] = []

    def step(self, bucket: FlowBucket) -> None:
        # Cash moves with customer flows
        self.cash_buffer_cents += bucket.inflow_cents
        self.cash_buffer_cents -= bucket.outflow_cents

        # If cash < 0, handle emergency deficit
        if self.cash_buffer_cents < 0:
            shortfall = abs(self.cash_buffer_cents)
            if self.vault_cents > 0:
                needed = min(self.vault_cents, int(shortfall / 0.98))
                penalty = int(needed * 0.02)
                recovered = needed - penalty
                self.vault_cents -= needed
                self.penalties_paid_cents += penalty
                self.cash_buffer_cents += recovered
            if self.cash_buffer_cents < 0:
                self.emergency_draws += 1
                self.cash_buffer_cents = 0

        # Maintain fixed $15M buffer:
        # If cash < $15M, replenish buffer from available vault funds
        if self.cash_buffer_cents < self.fixed_buffer_cents:
            if self.vault_cents > 0:
                top_up = min(self.vault_cents, self.fixed_buffer_cents - self.cash_buffer_cents)
                self.vault_cents -= top_up
                self.cash_buffer_cents += top_up
        # If cash > $15M, sweep excess to vault
        elif self.cash_buffer_cents > self.fixed_buffer_cents:
            excess = self.cash_buffer_cents - self.fixed_buffer_cents
            self.vault_cents += excess
            self.cash_buffer_cents = self.fixed_buffer_cents

        # Accrue vault yield per bucket
        bucket_yield = int(round(self.vault_cents * CONFIG.bucket_rate_vault))
        self.vault_cents += bucket_yield
        self.cumulative_yield_cents += bucket_yield
        self.idle_cash_samples.append(self.cash_buffer_cents)


class TreasuryEngine:
    def __init__(
        self,
        initial_cash_cents: int = CONFIG.initial_cash_cents,
        initial_vault_cents: int = CONFIG.initial_vault_cents,
        start_time: Optional[datetime] = None,
    ) -> None:
        self.start_time = start_time or datetime(2026, 10, 1, 0, 0, 0)
        self.current_time = self.start_time
        self.current_cycle: int = 0

        # Submodules
        self.ledger = DoubleEntryLedger()
        self.ledger.record_initial_capital(initial_cash_cents, initial_vault_cents, self.start_time)

        self.forecaster = Forecaster()
        self.cushion_sizer = CushionSizer()
        self.sweep_engine = SweepEngine(self.ledger)
        self.audit_logger = AuditLogger()

        # Seed rolling 24h initial vault tranches across 96 buckets
        # This provides continuous rolling liquidity from Day 1, Minute 0
        tranche_size = initial_vault_cents // CONFIG.VAULT_TRANCHE_HORIZON_BUCKETS
        remainder = initial_vault_cents % CONFIG.VAULT_TRANCHE_HORIZON_BUCKETS

        for b in range(CONFIG.VAULT_TRANCHE_HORIZON_BUCKETS):
            size = tranche_size + (remainder if b == 0 else 0)
            tr = VaultTranche(
                tranche_id=f"TRANCHE-INIT-{b:03d}",
                principal_cents=size,
                start_bucket=b - CONFIG.VAULT_TRANCHE_HORIZON_BUCKETS,
                mature_bucket=b,
            )
            self.sweep_engine.active_tranches.append(tr)
            self.sweep_engine.all_tranches.append(tr)

        # Baseline benchmark
        self.baseline = StaticBaseline(
            fixed_buffer_cents=CONFIG.static_baseline_buffer_cents,
            initial_vault_cents=initial_vault_cents,
        )

        # Operational modes & controls
        self.mode = EngineMode.NORMAL
        self.failsafe_reason: Optional[str] = None
        self.manual_cushion_addon_cents: int = 0
        self.manual_override_sweep_cents: Optional[int] = None

        # Statistics & telemetry
        self.payouts_attempted: int = 0
        self.payouts_completed: int = 0
        self.payouts_delayed: int = 0
        self.last_forecast_steps: List[ForecastHorizonStep] = []
        self.last_required_cushion_cents: int = CONFIG.treasury_floor_cents
        self.last_bucket: Optional[FlowBucket] = None

        # Time series tracking
        self.history_cash: List[int] = []
        self.history_required_buffer: List[int] = []
        self.history_vault: List[int] = []
        self.history_idle_cash: List[int] = []
        self.history_yield_alpha: List[int] = []

    def set_mode(self, mode: EngineMode, reason: Optional[str] = None) -> None:
        self.mode = mode
        if reason:
            self.failsafe_reason = reason
        elif mode == EngineMode.NORMAL:
            self.failsafe_reason = None

    def trigger_kill_switch(self) -> None:
        self.set_mode(EngineMode.KILLED, reason="Emergency Kill Switch pressed by operator.")

    def reset_kill_switch(self) -> None:
        self.set_mode(EngineMode.NORMAL, reason=None)

    def pause(self) -> None:
        self.set_mode(EngineMode.PAUSED, reason="Treasury paused by operator.")

    def resume(self) -> None:
        self.set_mode(EngineMode.NORMAL, reason=None)

    def manual_sweep(self, amount_usd: float) -> None:
        self.manual_override_sweep_cents = to_cents(amount_usd)

    def set_cushion_addon(self, addon_usd: float) -> None:
        self.manual_cushion_addon_cents = to_cents(addon_usd)

    def step(self, bucket: FlowBucket) -> AuditRecord:
        """Process one 15-minute simulation bucket."""
        self.current_cycle = bucket.bucket_index
        self.current_time = bucket.timestamp
        self.last_bucket = bucket

        # 1. Credit Customer Deposits
        self.ledger.record_customer_deposit(bucket.inflow_cents, timestamp=self.current_time)

        # 2. Continuous yield accrual on active vault assets
        vault_now = self.ledger.get_balance(LedgerAccount.YIELD_VAULT)
        if vault_now > 0:
            bucket_yield = int(round(vault_now * CONFIG.bucket_rate_vault))
            self.ledger.record_vault_yield_accrual(bucket_yield, timestamp=self.current_time)

        # 3. Release maturing vault tranches into cash buffer
        self.sweep_engine.process_tranche_maturities(
            current_bucket=self.current_cycle, timestamp=self.current_time
        )

        # 3. Process Customer Withdrawals & Liquidity Checks
        self.payouts_attempted += 1
        cash_avail = self.ledger.get_balance(LedgerAccount.CASH_BUFFER)

        if cash_avail >= bucket.outflow_cents:
            self.ledger.record_customer_withdrawal(bucket.outflow_cents, timestamp=self.current_time)
            self.payouts_completed += 1
        else:
            shortfall = bucket.outflow_cents - cash_avail
            # Liquidity hierarchy: break vault early or draw overdraft
            recovered, penalty_or_fee, source = self.sweep_engine.handle_liquidity_shortfall(
                shortfall, timestamp=self.current_time
            )
            # Recheck cash buffer
            new_cash = self.ledger.get_balance(LedgerAccount.CASH_BUFFER)
            if new_cash >= bucket.outflow_cents:
                self.ledger.record_customer_withdrawal(bucket.outflow_cents, timestamp=self.current_time)
                self.payouts_completed += 1
            else:
                # Emergency delayed payout (uncovered deficit)
                self.payouts_delayed += 1
                self.sweep_engine.total_delayed_payouts_count += 1
                if new_cash > 0:
                    self.ledger.record_customer_withdrawal(new_cash, timestamp=self.current_time)

        # 4. Forecaster update & Fail-Safe check
        try:
            self.forecaster.update_actuals(bucket)
        except StaleDataException as e:
            self.set_mode(EngineMode.FAILSAFE, reason=str(e))
        except Exception as e:
            self.set_mode(EngineMode.FAILSAFE, reason=f"Forecaster error: {e}")

        # 5. Generate 24h Probabilistic Forecast
        try:
            self.last_forecast_steps = self.forecaster.forecast_24h(
                self.current_time, self.current_cycle
            )
        except Exception as e:
            self.set_mode(EngineMode.FAILSAFE, reason=f"Forecast generation failed: {e}")
            self.last_forecast_steps = []

        # 6. Calculate Dynamic Cushion
        is_peak = bucket.scheduled_type is not None or bucket.is_shock
        wape_mult = self.forecaster.get_wape_cushion_multiplier(is_peak_day=is_peak)

        req_buffer_cents, q_deficit_cents, _ = self.cushion_sizer.calculate_cushion(
            forecast_steps=self.last_forecast_steps,
            horizon_buckets=CONFIG.FORECAST_HORIZON_BUCKETS,
            wape_multiplier=wape_mult,
            manual_addon_cents=self.manual_cushion_addon_cents,
        )
        self.last_required_cushion_cents = req_buffer_cents

        # 7. Evaluate and Execute Sweep
        cash_pre_sweep = self.ledger.get_balance(LedgerAccount.CASH_BUFFER)
        vault_pre_sweep = self.ledger.get_balance(LedgerAccount.YIELD_VAULT)

        decision: SweepDecision = self.sweep_engine.execute_cycle_sweep(
            cycle_index=self.current_cycle,
            required_buffer_cents=req_buffer_cents,
            engine_mode=self.mode,
            manual_override_sweep_cents=self.manual_override_sweep_cents,
            timestamp=self.current_time,
        )
        self.manual_override_sweep_cents = None

        # 8. Record Immutable Audit Trail
        audit_rec = self.audit_logger.record(
            cycle_index=self.current_cycle,
            timestamp=self.current_time.isoformat(),
            cash_before_cents=cash_pre_sweep,
            vault_before_cents=vault_pre_sweep,
            forecast_p999_max_deficit_cents=q_deficit_cents,
            required_cushion_cents=req_buffer_cents,
            headroom_cents=cash_pre_sweep - req_buffer_cents,
            decision=decision.action_taken,
            sweep_amount_cents=decision.sweep_amount_cents,
            reason=decision.reason,
        )

        # 9. Verify Accounting Cycle Reconciliation
        final_cash = self.ledger.get_balance(LedgerAccount.CASH_BUFFER)
        final_vault = self.ledger.get_balance(LedgerAccount.YIELD_VAULT)
        reconciliation = self.ledger.reconcile(final_cash, final_vault)
        if not reconciliation.is_balanced:
            raise RuntimeError(
                f"Ledger reconciliation break at cycle {self.current_cycle}: "
                f"Discrepancy={reconciliation.discrepancy_cents} cents"
            )

        # 10. Step Static Baseline Benchmark
        self.baseline.step(bucket)

        # 11. Record Historical Series
        self.history_cash.append(final_cash)
        self.history_required_buffer.append(req_buffer_cents)
        self.history_vault.append(final_vault)
        self.history_idle_cash.append(final_cash)

        net_yield_cents = (
            self.ledger.get_balance(LedgerAccount.YIELD_INCOME)
            - self.ledger.get_balance(LedgerAccount.EARLY_WITHDRAWAL_PENALTY_EXPENSE)
            - self.ledger.get_balance(LedgerAccount.LOAN_FEE_EXPENSE)
            - self.ledger.get_balance(LedgerAccount.LOAN_INTEREST_EXPENSE)
        )
        self.history_yield_alpha.append(net_yield_cents - self.baseline.cumulative_yield_cents)

        return audit_rec

    def get_telemetry(self) -> TelemetryDTO:
        """Produce real-time telemetry payload for dashboard and monitoring."""
        cash_cents = self.ledger.get_balance(LedgerAccount.CASH_BUFFER)
        vault_cents = self.ledger.get_balance(LedgerAccount.YIELD_VAULT)
        emergency_loan_cents = self.ledger.get_balance(LedgerAccount.EMERGENCY_OVERDRAFT_LOAN)
        penalties_cents = self.ledger.get_balance(LedgerAccount.EARLY_WITHDRAWAL_PENALTY_EXPENSE)
        yield_income_cents = self.ledger.get_balance(LedgerAccount.YIELD_INCOME)
        loan_fees_cents = (
            self.ledger.get_balance(LedgerAccount.LOAN_FEE_EXPENSE)
            + self.ledger.get_balance(LedgerAccount.LOAN_INTEREST_EXPENSE)
        )
        net_yield_cents = yield_income_cents - penalties_cents - loan_fees_cents

        headroom_cents = cash_cents - self.last_required_cushion_cents
        payout_rate = (
            1.0 if self.payouts_attempted == 0 else self.payouts_completed / self.payouts_attempted
        )

        recent_audits = [
            {
                "cycle": r.cycle_index,
                "timestamp": r.timestamp,
                "cash": to_usd(r.cash_before_cents),
                "vault": to_usd(r.vault_before_cents),
                "cushion": to_usd(r.required_cushion_cents),
                "headroom": to_usd(r.headroom_cents),
                "decision": r.decision,
                "sweep": to_usd(r.sweep_amount_cents),
                "reason": r.reason,
                "hash": r.record_hash[:10] + "...",
            }
            for r in self.audit_logger.get_recent(15)
        ]

        fan_data = [
            {
                "step": s.step,
                "out_p50": to_usd(s.outflow_p50),
                "out_p95": to_usd(s.outflow_p95),
                "out_p99": to_usd(s.outflow_p99),
                "out_p999": to_usd(s.outflow_p999),
                "in_p50": to_usd(s.inflow_p50),
            }
            for s in self.last_forecast_steps[:24]  # Next 6 hours
        ]

        return TelemetryDTO(
            cycle_index=self.current_cycle,
            timestamp=self.current_time.strftime("%Y-%m-%d %H:%M"),
            mode=self.mode.value,
            cash_buffer_usd=to_usd(cash_cents),
            yield_vault_usd=to_usd(vault_cents),
            required_cushion_usd=to_usd(self.last_required_cushion_cents),
            headroom_usd=to_usd(headroom_cents),
            current_wape=round(self.forecaster.combined_wape, 4),
            emergency_draws=self.sweep_engine.total_emergency_draws_count,
            emergency_loan_balance_usd=to_usd(emergency_loan_cents),
            early_withdrawal_penalties_usd=to_usd(penalties_cents),
            net_yield_earned_usd=to_usd(net_yield_cents),
            baseline_yield_earned_usd=to_usd(self.baseline.cumulative_yield_cents),
            yield_alpha_usd=to_usd(net_yield_cents - self.baseline.cumulative_yield_cents),
            payout_success_rate=round(payout_rate * 100.0, 2),
            last_inflow_usd=to_usd(self.last_bucket.inflow_cents if self.last_bucket else 0),
            last_outflow_usd=to_usd(self.last_bucket.outflow_cents if self.last_bucket else 0),
            recent_audit=recent_audits,
            forecast_fan=fan_data,
        )
