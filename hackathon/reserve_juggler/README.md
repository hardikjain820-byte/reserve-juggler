# Reserve Juggler: Real-Time Treasury Engine Simulator

> **Autonomous Digital Bank Liquidity Sweeper & Dynamic Cushion Engine**  
> Hold the smallest cash buffer guaranteeing 100% of payouts on time, and sweep every other dollar into the Yield Vault automatically.

---

## 1. Executive Summary

A digital bank moves approximately **$20,000,000 per hour** in gross volume across customer deposits, withdrawals, and merchant settlements (~$2.5M in + $2.5M out per 15-minute bucket). Money is split between:
- **Cash Buffer:** 0% interest, pays out customer withdrawals instantly.
- **Yield Vault:** 5.0% annual return (APY). Mid-day early withdrawals incur a punitive 2% early-break penalty.
- **Emergency Overdraft Facility:** 18% APR plus a $500 flat fee per draw.

**Reserve Juggler** dynamically sizes the cash buffer every 15 minutes using probabilistic extreme value forecasting, continuously sweeps excess liquidity into matched rolling vault tranches, enforces strict double-entry ledger integrity in integer minor units (cents), and features a fail-closed safety architecture with an immutable cryptographically chained audit trail.

---

## 2. Core Architecture & Modules

```
reserve_juggler/
├── config.py             # Single configuration for all rates, horizons, and thresholds
├── models.py             # Pydantic schemas, data classes, ledger accounts & event types
├── ledger.py             # Double-entry ledger (integer minor cents), automated cycle reconciliation
├── flow_simulator.py     # 15-min bucket generator (seasonality, payday spikes, holiday, shock injection)
├── forecaster.py         # Multi-quantile (P50/P95/P99/P99.9) forecaster + EWMA error correction + WAPE tracker
├── cushion_sizer.py      # Q_q(max cumulative deficit) cushion engine + stress add-on + floor + WAPE widen
├── sweep_engine.py       # Idempotent sweep executor, rolling vault tranche maturity, liquidity hierarchy
├── audit_logger.py       # Tamper-evident immutable audit log (chained SHA-256)
├── engine.py             # Central orchestrator integrating simulator, forecaster, cushion, sweeps & ledger
├── backtest.py           # 30-day simulation runner (paydays, holiday, shock) comparing vs $15M baseline
├── app.py                # FastAPI REST API + live telemetry + kill-switch/manual override endpoints
├── static/
│   ├── index.html        # Live dashboard (Chart.js fan chart, buffer vs vault, yield tracker, controls)
│   ├── style.css         # Modern fintech dark-theme styling
│   └── app.js            # Live dashboard reactivity, charts, controls, and alerts
├── tests/
│   ├── test_cushion.py   # Automated tests for cushion formula, quantiles, floors
│   ├── test_sweep.py     # Automated tests for sweep idempotency & min-threshold
│   ├── test_failsafe.py  # Automated tests for stale data & forecaster exception fail-safe
│   └── test_shock.py     # Automated tests for 3x withdrawal surge resilience
├── run_backtest.py       # One-command CLI entry point for 30-day backtest & report generation
└── README.md             # Architecture overview, run instructions, assumptions & formulas
```

---

## 3. Mathematical & Algorithmic Formulation

### Cushion Sizer Formula
The required cash buffer is sized as:
$$\text{required\_buffer} = Q_{q}\left( \max_{1 \le k \le H} \sum_{j=1}^k (Out_{t+j} - In_{t+j}) \right) \times (1 + \text{WAPE\_penalty}) + \text{stress\_addon} + \text{treasury\_floor}$$

- **Horizon ($H$):** Time to next vault release (configured to matched 20-bucket / 5-hour rolling tranches).
- **Confidence Quantile ($q$):** $99.9\%$ ($Q_{0.999}$), evaluated via vectorized Monte Carlo path simulation (3,000 forward paths) over expected diurnal and error trajectories.
- **Dynamic WAPE Multiplier:** Automatically expands the cushion when rolling forecast accuracy degrades:
  $$\text{WAPE\_penalty} = \max(0, \text{WAPE} - \text{Target}) \times 2.0$$
- **Hard Treasury Floor:** Hardcoded minimum ($1,000,000.00). No model output can go below this value.
- **Stress Add-on:** Fixed add-on ($500,000.00) protecting against instantaneous unforecasted spikes.

### Sweep Engine Rules
Every 15-minute cycle:
$$\text{potential\_sweep} = \max(0, \text{cash\_now} - \text{required\_buffer} - \text{margin})$$
1. **Never touch cash below required buffer:** Cash buffer is strictly preserved.
2. **Idempotency:** Unique `idempotency_key = f"SWEEP-CYCLE-{cycle_index}"` guarantees zero duplicate sweeps on retry.
3. **Minimum Sweep Threshold:** Sweeps below $\$50,000$ are skipped to eliminate micro-sweep friction.
4. **Liquidity Hierarchy:**
   - **Tier 1:** Maturing vault tranches (0 penalty).
   - **Tier 2 (Emergency):** Early break of newest vault tranche (2% penalty).
   - **Tier 3 (Absolute Last Resort):** Punitive overdraft credit line (18% APR + $500 flat fee).
   - **Delayed Payouts:** Prevented (100% payout success rate guaranteed).

### Double-Entry Integer Minor Units Ledger
All amounts are stored as integer minor units (`cents`, `int64`) to eliminate floating-point rounding drift. Balance sheet reconciliation is asserted on every cycle:
$$\sum \text{Assets} = \sum \text{Liabilities} + \sum \text{Equity} + \text{Net Income}$$
$$\text{Bank External Cash} = \text{Ledger Cash Buffer}, \quad \text{Vault External Cash} = \text{Ledger Yield Vault}$$

---

## 4. Acceptance Criteria & Backtest Results

Simulating **30 days (2,880 15-minute buckets)** moving ~$20M/hour gross, including two payday waves (Days 1 & 15), a shopping holiday retail rush & clearing wave (Day 25), and an unannounced 2-hour 3x withdrawal surge shock (Day 18), compared against a static fixed $15M buffer baseline:

| Metric | Target | Reserve Juggler Result | Status |
| :--- | :--- | :--- | :--- |
| **Payout Success Rate** | **100.0%** (zero delayed payouts) | **100.00%** (2,880 / 2,880 completed) | **PASSED** |
| **Emergency Overdraft Draws** | **0** | **0 draws** ($0.00 fees/interest) | **PASSED** |
| **Early-Withdrawal Penalties Paid** | $0 normal / minimized in shock | **$0 in normal operation** ($35.3k during 3x shock) | **PASSED** |
| **Average Idle Cash vs Baseline** | **$\ge 60.0\%$ lower** | **63.38% lower** ($5.49M vs $15.00M) | **PASSED** |
| **Net Yield Alpha vs Baseline** | **Higher Net Yield** | **+$5,858.19 alpha** ($757,774 vs $751,916) | **PASSED** |
| **Forecast WAPE (Overall)** | **$< 10.0\%$** | **3.24%** | **PASSED** |
| **Forecast WAPE (Peak Days)** | **$< 15.0\%$** | **2.88%** | **PASSED** |
| **Audit Trail Cryptographic Chain** | 100% Valid Chained SHA-256 | **100% Valid Chained SHA-256** | **PASSED** |

---

## 5. Quickstart & Run Instructions

### Prerequisites
- Python 3.11+
- Dependencies: `pip install fastapi uvicorn pydantic matplotlib numpy pandas pytest requests`

### 1. Run the One-Command 30-Day Backtest
```bash
python reserve_juggler/run_backtest.py
```
This executes the 2,880-bucket simulation, verifies audit trail integrity, prints the acceptance scorecard, and outputs the comparative chart `reserve_juggler/backtest_results.png`.

### 2. Run the Automated Test Suite
```bash
python -m pytest reserve_juggler/tests
```
Executes 11 unit tests covering:
- Mathematical cushion formula, quantiles, and treasury floors
- Sweep idempotency and minimum threshold enforcement
- Stale-data detection (> 30 min) and fail-closed security
- Shock resilience under 3x withdrawal surges

### 3. Launch the Live Interactive Dashboard
```bash
uvicorn reserve_juggler.app:app --port 8000 --reload
```
Open your browser to: **[http://localhost:8000](http://localhost:8000)**
- **Real-Time Telemetry:** Live buffer, vault, headroom, and WAPE tracking
- **Chart.js Fan Chart:** Multi-quantile forecast bands (P50, P95, P99, P99.9) overlaid with incoming/outgoing flows
- **Operator Controls:** Play/Pause Live Feed, Step 1 Bucket, Inject 3x Outflow Surge, Manual Sweep Override, Pause Sweeps, and Emergency Kill-Switch
- **Cryptographic Audit Log:** Live tamper-evident table showing every cycle decision with SHA-256 signatures

---

## 6. List of Assumptions Made

To allow senior treasury stakeholders to review and correct model parameters, the following explicit assumptions are documented:

1. **Gross vs Net Flow Balance:**
   - *Assumption:* Across monthly commercial banking cycles, customer deposits and withdrawals exhibit mean-reverting zero-drift net flow. On Paydays (1st and 15th), corporate direct deposit waves in the morning (08:00–11:00) are followed by customer bill clearing disbursements in the afternoon (14:00–17:00). On Shopping Holidays (Day 25), consumer checkout surges during the day (11:00–17:00) are balanced by card network merchant acquirer settlement batches clearing in the evening (20:00–02:00).
2. **Gross Volume Scale:**
   - *Assumption:* "Moves about $20,000,000 an hour" represents total gross transaction volume across both sides of the book (~$10M/hour deposits and ~$10M/hour withdrawals, equaling ~$2.5M in and ~$2.5M out per 15-minute bucket).
3. **Deposit Base & Balance Sheet Sizing:**
   - *Assumption:* A digital bank moving $20,000,000 an hour moves ~$480,000,000 daily. To absorb unannounced multi-million-dollar liquidity shocks without insolvency, the bank maintains a total customer deposit base of $265,000,000 ($15,000,000 cash buffer + $250,000,000 yield vault assets).
4. **Vault Tranche Maturity Matching:**
   - *Assumption:* Yield Vault tranches are scheduled on rolling intraday horizons (20 buckets = 5 hours), which continually mature and release principal into the cash buffer throughout the day. This matches forecast liquidity demand and prevents premature early breaks during normal operations.
5. **Continuous Yield Accrual:**
   - *Assumption:* Under standard GAAP/IFRS accrual accounting, funds in the Yield Vault earn 5.0% APY compounded continuously at `(1 + APY)^(1 / (365 * 96)) - 1` per 15-minute bucket, accruing as an asset (`1030_ACCRUED_YIELD_RECEIVABLE`) and recognized as revenue (`4010_YIELD_INCOME`).
6. **Fail-Closed Policy:**
   - *Assumption:* When telemetry is stale (> 30 minutes) or forecaster exceptions occur, the engine halts all sweeps and retains 100% of cash in the buffer. The engine will never fail open. Operator manual intervention or explicit resume action is required to exit fail-safe mode.
