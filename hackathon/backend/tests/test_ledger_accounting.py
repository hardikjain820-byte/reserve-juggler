import pytest
from backend.app.ledger.reconciliation import GeneralLedger, ReconciliationError, LiabilityLimitExceededError
from backend.app.ledger.journal import (
    create_opening_txn,
    create_deposit_txn,
    create_immediate_withdrawal_txn,
    create_queue_transfer_txn,
    create_queued_payout_paid_txn,
    create_repo_sweep_txn,
    create_repo_maturity_txn,
    create_repo_early_redemption_txn,
    create_overdraft_draw_txn,
    create_overdraft_repay_txn,
    create_overdraft_interest_txn,
)


def test_opening_and_basic_flows():
    ledger = GeneralLedger(run_id="test_run")
    # 1. Opening balance $3B
    opening_txn = create_opening_txn("test_run", 3_000_000_000_00, 3_000_000_000_00, "2026-01-01 00:00:00", seq=1)
    ledger.post_transaction(opening_txn)
    report = ledger.reconcile()
    assert report["cash_cents"] == 3_000_000_000_00
    assert report["total_assets"] == 3_000_000_000_00
    assert report["total_liabilities"] == 3_000_000_000_00
    assert report["net_pnl"] == 0

    # 2. Deposit $10M
    dep_txn = create_deposit_txn("test_run", 1, 10_000_000_00, "2026-01-01 01:00:00", seq=2)
    ledger.post_transaction(dep_txn)
    report = ledger.reconcile()
    assert report["cash_cents"] == 3_010_000_000_00
    assert report["total_assets"] == 3_010_000_000_00

    # 3. Withdrawal $5M
    wd_txn = create_immediate_withdrawal_txn("test_run", 2, 5_000_000_00, "2026-01-01 02:00:00", seq=3)
    ledger.post_transaction(wd_txn)
    report = ledger.reconcile()
    assert report["cash_cents"] == 3_005_000_000_00
    assert report["total_assets"] == 3_005_000_000_00


def test_delayed_payout_queue_accounting():
    """Verify that delayed payouts transfer liability Dr CUSTOMER_DEPOSITS / Cr PAYOUT_QUEUE
    and on later settlement Dr PAYOUT_QUEUE / Cr CASH without double debiting CUSTOMER_DEPOSITS.
    """
    ledger = GeneralLedger(run_id="test_queue")
    # Opening: $100 Cash / $100 Deposits
    ledger.post_transaction(create_opening_txn("test_queue", 100_00, 100_00, "2026-01-01 00:00:00", 1))

    # Assume an obligation of $50 cannot be paid right now, queued:
    q_transfer = create_queue_transfer_txn("test_queue", 1, 50_00, "2026-01-01 01:00:00", 2)
    ledger.post_transaction(q_transfer)
    report = ledger.reconcile()

    # Cash is still 100, Customer deposits dropped to 50, Payout queue is 50
    assert report["cash_cents"] == 100_00
    assert ledger.get_balance("CUSTOMER_DEPOSITS") == 50_00
    assert ledger.get_balance("PAYOUT_QUEUE") == 50_00
    assert report["total_liabilities"] == 100_00  # Total liabilities unchanged!

    # Later settlement of $50 from Cash:
    q_paid = create_queued_payout_paid_txn("test_queue", 2, 50_00, "2026-01-01 02:00:00", 3)
    ledger.post_transaction(q_paid)
    report = ledger.reconcile()

    # Cash dropped to 50, Payout queue is 0, Customer deposits remained at 50 (NO double debit!)
    assert report["cash_cents"] == 50_00
    assert ledger.get_balance("PAYOUT_QUEUE") == 0
    assert ledger.get_balance("CUSTOMER_DEPOSITS") == 50_00
    assert report["total_liabilities"] == 50_00
    assert report["total_assets"] == 50_00


def test_full_lifecycle_and_pnl_reconciliation():
    ledger = GeneralLedger(run_id="test_full")
    ledger.post_transaction(create_opening_txn("test_full", 500_000_000_00, 500_000_000_00, "2026-01-01 00:00:00", 1))

    # Repo sweep $100M
    ledger.post_transaction(create_repo_sweep_txn("test_full", 17, 100_000_000_00, "2026-01-01 17:00:00", 2))
    assert ledger.get_balance("CASH") == 400_000_000_00
    assert ledger.get_balance("REPO") == 100_000_000_00
    ledger.reconcile()

    # Repo maturity: principal $100M + interest $6,934.93
    ledger.post_transaction(create_repo_maturity_txn("test_full", 32, 100_000_000_00, 6934_93, "2026-01-02 08:00:00", 3))
    assert ledger.get_balance("CASH") == 500_006_934_93
    assert ledger.get_balance("REPO") == 0
    report = ledger.reconcile()
    assert report["net_pnl"] == 6934_93

    # Overdraft draw $10M
    ledger.post_transaction(create_overdraft_draw_txn("test_full", 33, 10_000_000_00, "2026-01-02 09:00:00", 4))
    assert ledger.get_balance("OVERDRAFT") == 10_000_000_00
    ledger.reconcile()

    # Overdraft interest $136.98
    ledger.post_transaction(create_overdraft_interest_txn("test_full", 34, 136_98, "2026-01-02 10:00:00", 5))
    report = ledger.reconcile()
    assert report["net_pnl"] == 6934_93 - 136_98

    # Overdraft repay $10,000,136.98
    ledger.post_transaction(create_overdraft_repay_txn("test_full", 35, 10_000_136_98, "2026-01-02 11:00:00", 6))
    assert ledger.get_balance("OVERDRAFT") == 0
    ledger.reconcile()


def test_negative_cash_and_liability_exhaustion_errors():
    ledger = GeneralLedger(run_id="test_errors")
    ledger.post_transaction(create_opening_txn("test_errors", 100_00, 100_00, "2026-01-01 00:00:00", 1))

    # Attempt to withdraw $200 from cash
    with pytest.raises(ReconciliationError, match="Negative cash balance"):
        ledger.post_transaction(create_immediate_withdrawal_txn("test_errors", 1, 200_00, "2026-01-01 01:00:00", 2))
        ledger.reconcile()
