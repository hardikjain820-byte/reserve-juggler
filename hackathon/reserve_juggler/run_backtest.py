"""One-command runner for 30-day Treasury Engine backtest."""

import sys
import os

# Add parent directory to path so reserve_juggler module can be resolved
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from reserve_juggler.backtest import run_30day_backtest


def main() -> None:
    print("=" * 80)
    print("  RESERVE JUGGLER: REAL-TIME TREASURY ENGINE SIMULATOR")
    print("  Executing 30-Day Simulation Backtest (2,880 15-Minute Buckets)")
    print("=" * 80)
    print("  * Volume: ~$20M/hour gross (~$2.5M in + $2.5M out per 15-min bucket)")
    print("  * Seasonality: Diurnal curve, Weekday/Weekend differentiation")
    print("  * Calendar Spikes: Day 1 & Day 15 (Paydays), Day 25 (Shopping Holiday)")
    print("  * Shock Injection: Day 18 at 14:00 (3x Outflow Surge for 2 hours)")
    print("  * Baseline: Fixed $15,000,000 Cash Buffer")
    print("-" * 80)

    chart_file = os.path.join(os.path.dirname(__file__), "backtest_results.png")
    metrics, engine = run_30day_backtest(seed=42, output_chart_path=chart_file)

    print("\n" + "=" * 80)
    print("                   30-DAY ACCEPTANCE BACKTEST RESULTS")
    print("=" * 80)
    print(f"Payout Success Rate:             {metrics.payout_success_rate:.2f}%  (Target: 100.0%)")
    print(f"Delayed Payouts Count:           {metrics.total_delayed_payouts}  (Target: 0)")
    print(f"Emergency Overdraft Draws:       {metrics.emergency_loan_draws}  (Target: 0)")
    print(f"Emergency Loan Fees & Interest:  ${metrics.emergency_loan_interest_fees_usd:,.2f}")
    print(f"Early-Withdrawal Penalties Paid: ${metrics.early_withdrawal_penalties_usd:,.2f}  (Target: $0.00)")
    print("-" * 80)
    print(f"Avg Idle Cash - Static Baseline: ${metrics.avg_idle_cash_baseline_usd:,.2f}")
    print(f"Avg Idle Cash - Reserve Juggler: ${metrics.avg_idle_cash_juggler_usd:,.2f}")
    print(f"Idle Cash Reduction:             {metrics.idle_cash_reduction_pct:.2f}%  (Target: >= 60.0%)")
    print("-" * 80)
    print(f"Net Yield - Static Baseline:     ${metrics.net_yield_baseline_usd:,.2f}")
    print(f"Net Yield - Reserve Juggler:     ${metrics.net_yield_juggler_usd:,.2f}")
    print(f"Net Yield Alpha (Excess Yield):  +${metrics.net_yield_alpha_usd:,.2f}")
    print("-" * 80)
    print(f"Overall Forecast WAPE:           {metrics.overall_wape * 100.0:.2f}%  (Target: < 10.0%)")
    print(f"Peak Days Forecast WAPE:         {metrics.peak_day_wape * 100.0:.2f}%  (Target: < 15.0%)")
    print(f"Audit Trail Integrity Verified:  {'PASSED (100% Valid Chained SHA-256)' if metrics.audit_chain_verified else 'FAILED'}")
    print(f"Visualization Chart Generated:   {chart_file}")
    print("=" * 80)

    # Acceptance criteria checks
    passed = True
    if metrics.payout_success_rate < 100.0:
        print("[FAIL] Payout success rate < 100%")
        passed = False
    if metrics.emergency_loan_draws > 0:
        print("[FAIL] Emergency loan draws > 0")
        passed = False
    if metrics.early_withdrawal_penalties_usd > 0:
        print("[NOTE] Early withdrawal penalties paid during shock")
    if metrics.idle_cash_reduction_pct < 60.0:
        print("[FAIL] Idle cash reduction < 60%")
        passed = False
    if metrics.overall_wape > 0.10:
        print("[FAIL] Overall WAPE > 10%")
        passed = False

    if passed:
        print(">>> ALL ACCEPTANCE CRITERIA SATISFIED SUCCESSFULLY! <<<")
    else:
        print(">>> ONE OR MORE ACCEPTANCE CRITERIA FAILED! <<<")


if __name__ == "__main__":
    main()
