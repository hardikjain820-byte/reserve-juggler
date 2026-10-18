# Reserve Juggler ⚡
**Autonomous Real-Time Treasury & Liquidity Optimization Engine**
Mode: **SIMULATION-ONLY** (No real funds moved)

---

## Architecture & Financial Engineering

Reserve Juggler is a real-time treasury engine for a high-volume digital bank moving over $20M/hour in gross flows. It balances three continuous forces:
1. **Cash Buffer (0% yield):** Guarantees zero payout delays for customer withdrawals.
2. **Yield Vaults & Ladders (Repo / Vault / Bonds / Equities):** Maximizes yield subject to market execution windows, settlement lags (up to 48h), and early redemption haircuts.
3. **Emergency Overdraft Facility (12% APR):** Punitive borrowing facility drawn only when immediate cash and eligible liquidations fall short.

### Key Financial Controls
* **Pure Double-Entry Ledger:** All postings denominated in integer cents (`BIGINT`), with zero floating-point representation.
* **Multi-Invariant Reconciliation:** Every step atomically verifies:
  * Trial Balance: $\sum \text{Debits} = \sum \text{Credits}$
  * Balance Sheet: $\text{Assets} = \text{Liabilities} + \text{Equity} + (\text{Income} - \text{Expenses})$
  * Solvency Floor: $\text{CASH} \ge 0$
* **Delayed Payout Queue (U9):** If liquidity facilities exhaust, unpaid obligations transfer $\text{Dr}\ \text{CUSTOMER\_DEPOSITS} / \text{Cr}\ \text{PAYOUT\_QUEUE}$. Upon later settlement from cash, $\text{Dr}\ \text{PAYOUT\_QUEUE} / \text{Cr}\ \text{CASH}$ without double-debiting customer deposits.
* **Tamper-Evident SHA-256 Audit Trail:** Cryptographic hash chain over all decisions, sweeps, and ledger entries with independent verification.
* **Anti-Leakage Guard:** Feature extractor signature takes `as_of_index` and guarantees future data cannot contaminate earlier forecasts or reserve decisions.

---

## Quickstart & Launch Commands

### 1. Start the Live Engine & Institutional Dashboard
Run the combined backend and frontend server on `http://127.0.0.1:8000`:

```bash
python -m uvicorn backend.app.api.main:app --host 127.0.0.1 --port 8000
```

Open your browser to:
👉 **`http://127.0.0.1:8000`**

### 2. Run the Full Automated Test Suite (38 Tests)
Verify 100% financial correctness, ledger reconciliation, all 10 stress scenarios, and walk-forward backtests:

```bash
python -m pytest backend/tests -v
```

---

## Strategy Benchmark Comparisons (168-Hour Walk-Forward Replay)

| Strategy | Description | Status | Payout Success | Gross Yield | Net Realized Yield | Peak Overdraft | Average Idle Cash |
|---|---|---|---|---|---|---|---|
| **`B0_CASH`** | Reference (All-Cash, zero sweeps) | `COMPLETED` | 100.00% | $0.00 | **$0.00** | $0.00 | $2,992,129,318.32 |
| **`B1_FIXED`** | Fixed 10% reserve floor | `COMPLETED` | 100.00% | $1,175,716.38 | **$1,175,716.38** | $0.00 | $1,437,609,837.82 |
| **`B2_CONSERVATIVE`**| 1.25x Peak 24h Outflow Reserve | `COMPLETED` | 100.00% | $1,239,009.28 | **$1,239,009.28** | $0.00 | $1,353,970,884.99 |
| **`B3_DYNAMIC`** | Proposed ($R_{prob} + S_{add} + F_{hard}$) | `COMPLETED` | 100.00% | $914,412.44 | **$914,412.44** | $0.00 | $1,783,107,712.51 |
| **`B4_CHALLENGE`** | Benchmark: Fixed 5.00% APY Vault | `COMPLETED` | 100.00% | $1,525,074.77 | **$1,525,074.77** | $0.00 | $1,279,325,325.66 |

---

## Stress Scenarios Verified (PRD §11.2)
1. `OUTFLOW_MULT`: 3.0x outflows for 12 hours.
2. `WITHDRAWAL_SPIKE`: $150M single-hour spike.
3. `DELAYED_DEPOSITS`: 100% deposits delayed 12 hours.
4. `REPO_UNAVAILABLE`: 48-hour window lockout and blocked maturities.
5. `LIQUIDATION_DELAY`: +48-hour settlement lag.
6. `BOND_SHOCK`: +150 bp yield jump ($B \leftarrow B \times (1 - Dur \times \Delta y)$).
7. `EQUITY_CRASH`: -25% equity drawdown.
8. `CORRELATED_RUN`: Outflow spike + equity crash + bond shock simultaneously.
9. `OVERDRAFT_RESTRICTED`: Overdraft line capped at 0.25x ($25M).
10. `COMBINED_WORST`: Chained worst-case liquidity drill.
