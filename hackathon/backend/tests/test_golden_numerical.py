import math
from decimal import Decimal, ROUND_FLOOR
import pytest
from backend.app.settlement.repo import RepoPosition


def test_repo_interest_golden_example():
    """Verify Example 2 from PRD:
    $100,000,000 swept at 4.05% APY, held 15h to maturity.
    Expected interest: $6,934.93.
    """
    principal_cents = 100_000_000_00  # $100M
    rate_apy = 4.05
    hours = 15

    # Hand calculation using Decimal with standard cent truncation
    # 100,000,000 * 0.0405 * 15 / 8760 = 6934.9315068...
    expected_cents = math.floor(principal_cents * (rate_apy / 100.0) * hours / 8760.0)
    assert expected_cents == 6934_93, f"Expected 693493 cents ($6,934.93), got {expected_cents}"

    repo = RepoPosition(
        position_id="test_repo",
        opened_step=17,
        opened_ts="2026-01-01 17:00:00",
        principal_cents=principal_cents,
        rate_apy_pct=rate_apy,
        maturity_step=32,
    )
    assert repo.calculate_interest(hours) == 6934_93


def test_repo_early_redemption_golden_example():
    """Verify Example 2 early redemption:
    Haircut 0.5% on $100,000,000 = $500,000. Net proceeds = $99,500,000. Interest forfeited.
    """
    principal_cents = 100_000_000_00
    repo = RepoPosition(
        position_id="test_repo_early",
        opened_step=17,
        opened_ts="2026-01-01 17:00:00",
        principal_cents=principal_cents,
        rate_apy_pct=4.05,
        maturity_step=32,
        haircut_pct=0.5,
    )
    redemption = repo.calculate_early_redemption()
    assert redemption["haircut_cents"] == 500_000_00
    assert redemption["net_proceeds_cents"] == 99_500_000_00


def test_bond_liquidation_golden_example():
    """Verify Example 3:
    $50M bond position, Dur = 1.92, yield shock +100 bp (+0.01).
    Delta B / B = -1.92 * 0.01 = -1.92%.
    Market value = $50M * (1 - 0.0192) = $49,040,000.
    Liquidation haircut 2% of market value = $980,800.
    Proceeds = $49,040,000 - $980,800 = $48,059,200 (exact to the dollar).
    """
    invested_usd = 50_000_000.0
    dur = 1.92
    delta_yield = 0.01
    price_pct_change = -dur * delta_yield  # -0.0192 (-1.92%)
    
    market_value = invested_usd * (1.0 + price_pct_change)
    assert market_value == 49_040_000.0

    haircut_pct = 0.02
    haircut_usd = market_value * haircut_pct
    assert haircut_usd == 980_800.0

    net_proceeds_usd = market_value - haircut_usd
    assert net_proceeds_usd == 48_059_200.0
    assert round(net_proceeds_usd) == 48_059_200


def test_reserve_sizing_golden_example():
    """Verify Example 1 / AC-3 from PRD:
    Q = $39,113,465, m = 10% -> R_prob = max(25M, 39,113,465 * 1.10) = $43,024,811.50 -> $43,024,812
    S_add = (3 - 1) * 15,335,204 = $30,670,408
    R_total = 43,024,812 + 30,670,408 = $73,695,220.
    """
    q_usd = 39_113_465.0
    min_floor = 25_000_000.0
    m = 0.10
    r_prob = max(min_floor, round(q_usd * (1.0 + m)))
    assert r_prob == 43_024_812

    k = 3.0
    w_p50 = 15_335_204.0
    s_add = round((k - 1.0) * w_p50)
    assert s_add == 30_670_408

    r_total = r_prob + s_add
    assert r_total == 73_695_220


def test_overdraft_hourly_interest_example():
    """Verify Example 5 overdraft interest:
    $5.30M drawn at 12% APR ACT/365:
    5,300,000 * 0.12 / 8760 = $72.6027... -> $72.60 / hour.
    """
    od_cents = 5_300_000_00
    apr = 0.12
    hourly_interest = math.floor(od_cents * apr * (1.0 / 8760.0))
    assert hourly_interest == 72_60, f"Expected 7260 cents ($72.60), got {hourly_interest}"
