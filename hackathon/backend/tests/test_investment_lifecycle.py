import pytest
from backend.app.ledger.reconciliation import GeneralLedger
from backend.app.ledger.journal import (
    create_opening_txn,
    create_bond_purchase_txn,
    create_bond_carry_txn,
    create_bond_mtm_txn,
    create_bond_sale_txn,
    create_stock_purchase_txn,
    create_stock_mtm_txn,
    create_stock_sale_txn,
    create_overdraft_draw_txn,
    create_overdraft_interest_txn,
    create_overdraft_repay_txn,
)


def test_complete_bond_investment_lifecycle():
    """Verify complete bond lifecycle:
    1. Initial funding ($100M)
    2. Purchase bond for $50M
    3. Mark-to-market gain +$1M (price up)
    4. Accrue carry interest +$50,000
    5. Mark-to-market shock -$2M (price down)
    6. Liquidate bond with 2% haircut
    7. Full balance sheet and trial balance reconciliation at each step.
    """
    ledger = GeneralLedger(run_id="test_bond_lifecycle")
    
    # 1. Opening
    ledger.post_transaction(create_opening_txn("test_bond_lifecycle", 100_000_000_00, 100_000_000_00, "2026-01-01 00:00:00", 1))
    ledger.reconcile()

    # 2. Purchase bond for $50M
    ledger.post_transaction(create_bond_purchase_txn("test_bond_lifecycle", 1, 50_000_000_00, "2026-01-01 01:00:00", 2))
    assert ledger.get_balance("CASH") == 50_000_000_00
    assert ledger.get_balance("BOND") == 50_000_000_00
    r = ledger.reconcile()
    assert r["total_assets"] == 100_000_000_00
    assert r["net_pnl"] == 0

    # 3. Mark-to-market gain +$1M
    ledger.post_transaction(create_bond_mtm_txn("test_bond_lifecycle", 2, 1_000_000_00, "2026-01-01 02:00:00", 3))
    assert ledger.get_balance("BOND") == 51_000_000_00
    r = ledger.reconcile()
    assert r["total_assets"] == 101_000_000_00
    assert r["net_pnl"] == 1_000_000_00

    # 4. Accrue bond carry +$50,000
    ledger.post_transaction(create_bond_carry_txn("test_bond_lifecycle", 3, 50_000_00, "2026-01-01 03:00:00", 4))
    assert ledger.get_balance("BOND_ACCRUED_INTEREST") == 50_000_00
    r = ledger.reconcile()
    assert r["total_assets"] == 101_050_000_00
    assert r["net_pnl"] == 1_050_000_00

    # 5. Mark-to-market loss -$2M (bond value drops to $49M)
    ledger.post_transaction(create_bond_mtm_txn("test_bond_lifecycle", 4, -2_000_000_00, "2026-01-01 04:00:00", 5))
    assert ledger.get_balance("BOND") == 49_000_000_00
    r = ledger.reconcile()
    assert r["total_assets"] == 99_050_000_00
    assert r["net_pnl"] == -950_000_00

    # 6. Liquidate entire bond ($49M market value) at 2% haircut ($980,000)
    # Net cash received = $48,020,000
    haircut_cents = int(49_000_000_00 * 0.02)
    ledger.post_transaction(create_bond_sale_txn("test_bond_lifecycle", 5, 49_000_000_00, haircut_cents, "2026-01-01 05:00:00", 6))
    assert ledger.get_balance("BOND") == 0
    assert ledger.get_balance("CASH") == 50_000_000_00 + (49_000_000_00 - haircut_cents)
    r = ledger.reconcile()
    # P&L = +$1M (MTM gain) + $50k (carry) - $2M (MTM loss) - $980k (liquidation cost) = -$1,930,000
    assert r["net_pnl"] == -1_930_000_00
    assert r["total_assets"] == 100_000_000_00 + r["net_pnl"]


def test_complete_stock_lifecycle_and_overdraft_cycle():
    """Verify stock purchase, loss, liquidation with 15% haircut, and overdraft cycle."""
    ledger = GeneralLedger(run_id="test_stock_od")
    ledger.post_transaction(create_opening_txn("test_stock_od", 20_000_000_00, 20_000_000_00, "2026-01-01 00:00:00", 1))

    # Buy stock $10M
    ledger.post_transaction(create_stock_purchase_txn("test_stock_od", 1, 10_000_000_00, "2026-01-01 01:00:00", 2))
    assert ledger.get_balance("STOCK") == 10_000_000_00
    ledger.reconcile()

    # Stock crashes -20% (-$2M)
    ledger.post_transaction(create_stock_mtm_txn("test_stock_od", 2, -2_000_000_00, "2026-01-01 02:00:00", 3))
    assert ledger.get_balance("STOCK") == 8_000_000_00
    ledger.reconcile()

    # Liquidate stock ($8M market value) with 15% haircut ($1.2M)
    # Net cash received = $6.8M
    haircut_stock = int(8_000_000_00 * 0.15)
    ledger.post_transaction(create_stock_sale_txn("test_stock_od", 3, 8_000_000_00, haircut_stock, "2026-01-01 03:00:00", 4))
    assert ledger.get_balance("STOCK") == 0
    ledger.reconcile()

    # Overdraft draw $5M
    ledger.post_transaction(create_overdraft_draw_txn("test_stock_od", 4, 5_000_000_00, "2026-01-01 04:00:00", 5))
    assert ledger.get_balance("OVERDRAFT") == 5_000_000_00
    ledger.reconcile()

    # Overdraft interest $68.49
    ledger.post_transaction(create_overdraft_interest_txn("test_stock_od", 5, 68_49, "2026-01-01 05:00:00", 6))
    assert ledger.get_balance("OVERDRAFT") == 5_000_068_49
    ledger.reconcile()

    # Repay full overdraft
    ledger.post_transaction(create_overdraft_repay_txn("test_stock_od", 6, 5_000_068_49, "2026-01-01 06:00:00", 7))
    assert ledger.get_balance("OVERDRAFT") == 0
    report = ledger.reconcile()
    assert report["total_assets"] == report["total_liabilities"] + report["total_equity"] + report["net_pnl"]
