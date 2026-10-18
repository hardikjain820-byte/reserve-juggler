# Reserve Juggler — Architectural & Financial Decisions (DECISIONS.md)
Mode: **SIMULATION-ONLY**

## 1. Accounting Policy & Journal Postings
* **Unit of Account:** Integer cents (`BIGINT` in DB, `int` in Python). Floats are strictly prohibited for balances and ledger transactions. Conversions from USD float to cents use `int(round(usd * 100))`.
* **Chart of Accounts:**
  * **Assets:** `CASH`, `REPO`, `BOND`, `STOCK`, `BOND_ACCRUED_INTEREST` (Natural Debit)
  * **Liabilities:** `CUSTOMER_DEPOSITS`, `OVERDRAFT`, `PAYOUT_QUEUE` (Natural Credit)
  * **Equity:** `CAPITAL` (Natural Credit)
  * **Income:** `REPO_INTEREST`, `BOND_CARRY`, `MTM_GAIN`, `EXTERNAL_FUNDING` (Natural Credit)
  * **Expenses:** `MTM_LOSS`, `EARLY_REDEMPTION_COST`, `BOND_LIQUIDATION_COST`, `STOCK_LIQUIDATION_COST`, `OD_INTEREST` (Natural Debit)
* **Reconciliation Invariants (Atomic per step):**
  1. $\sum \text{Debits} = \sum \text{Credits}$ across all ledger transactions.
  2. $\text{Total Assets} = \text{Total Liabilities} + \text{Equity} + (\text{Income} - \text{Expenses})$.
  3. $\text{CASH} \ge 0$ (negative cash is impossible; shortfalls route to overdraft or payout queue).
  4. $\text{CUSTOMER\_DEPOSITS} \ge 0$ (if exhausted by structural drain, run halts with `TERMINATED_ECONOMIC_LIMIT`).
* **Delayed Payout Queue (U9):**
  * When obligations cannot be covered by cash, liquidations, and overdraft room, the accepted unpaid amount transfers:
    `Dr CUSTOMER_DEPOSITS / Cr PAYOUT_QUEUE`. Total bank liabilities remain constant.
  * When paid later from cash (FIFO):
    `Dr PAYOUT_QUEUE / Cr CASH`.
    `CUSTOMER_DEPOSITS` is never debited a second time.

## 2. Liquidity Safety & Sweep Invariants
* **Reserve Nature:** Statistical quantiles ($Q_\alpha$) and stress add-ons ($S_{add}$) are policy safety cushions and targets. They are **not mathematical guarantees** of future liquidity. Future outflows can exceed historical distributions.
* **Deterministic Sweep Invariants:**
  1. `Overdraft == 0` (no sweeping while borrowing emergency funds).
  2. `PayoutQueue == 0` (no sweeping while customer obligations are delinquent).
  3. `Cash_Available = Cash - PayoutQueue_Due_Next_Window \ge 0`.
  4. `Sweepable_Surplus = max(0, Cash_Available - R_total)`.
  5. `Post_Sweep_Cash \ge F_hard` where $F_{hard} = \max(\text{min\_cash\_floor}, W^{\max}_{\text{train\_hourly}})$.
  6. `Liquidity-Ladder Invariant:` Cash after sweep plus unpenalized redeemable proceeds across all horizons $j \ge Q_\alpha(\text{cumulative net outflow over } j \text{ hours})$.
  7. `Portfolio Caps:` Repo $\le 70\%$, Bonds $\le 25\%$, Equities $\le 0\%$.

## 3. Backtesting & Evaluation Methodology
* **As-Of Policy:** Default evaluation uses `as_of_only` with cutoff `2026-10-17T00:00:00Z`. The 1,823 future-dated rows are strictly excluded from headline results. Opt-in `full_replay` explicitly displays "projected/synthetic replay".
* **Leakage Guard:** Feature extraction signature takes `as_of_index` and raises `LeakageError` if lookahead data is accessed.
* **Termination & Fair Comparison:** Runs stopped due to structural liquidity drain report `TERMINATED_ECONOMIC_LIMIT` with exact step, completion %, and common-horizon metrics.

## 4. 15-Minute Derived Resolution
* **Mapping:** Hourly row flows $D_t, W_t$ are partitioned into 4 quarter-hour steps $[0.25, 0.25, 0.25, 0.25]$ with cent remainder placed in the 4th step.
* **Flow & Accrual Conservation:** Sum of 4 quarter-hour steps equals hourly total to the exact cent. Interest accrues at rate $\times 0.25 / 8760$.
* **No Synthetic Noise:** No fabricated intrahour volatility. Steps are tagged `derived = True`. The hard floor $F_{hard}$ remains the full 1-hour maximum.
