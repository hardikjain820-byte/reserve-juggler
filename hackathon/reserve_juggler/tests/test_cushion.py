"""Automated tests for Cushion Sizer formula, quantiles, and floors."""

from datetime import datetime, timedelta
import pytest

from reserve_juggler.config import CONFIG, to_cents
from reserve_juggler.cushion_sizer import CushionSizer
from reserve_juggler.forecaster import Forecaster
from reserve_juggler.models import ForecastHorizonStep


def test_cushion_hard_treasury_floor():
    """Verify that buffer never falls below treasury floor even when inflows exceed outflows."""
    sizer = CushionSizer(
        confidence_quantile=0.999,
        stress_addon_cents=0,
        treasury_floor_cents=CONFIG.treasury_floor_cents,
    )

    # Inflows heavily exceed outflows -> cumulative deficit is 0
    steps = [
        ForecastHorizonStep(
            step=i,
            bucket_index=i,
            inflow_p50=to_cents(10_000_000.0),
            inflow_p95=to_cents(11_000_000.0),
            inflow_p99=to_cents(12_000_000.0),
            inflow_p999=to_cents(13_000_000.0),
            outflow_p50=to_cents(2_000_000.0),
            outflow_p95=to_cents(2_200_000.0),
            outflow_p99=to_cents(2_500_000.0),
            outflow_p999=to_cents(2_800_000.0),
        )
        for i in range(1, 97)
    ]

    buffer_cents, q_deficit, _ = sizer.calculate_cushion(steps)
    assert buffer_cents >= CONFIG.treasury_floor_cents
    assert q_deficit == 0


def test_cushion_formula_components():
    """Verify formula: Q_q(max cumulative deficit) + stress_addon + treasury_floor."""
    stress_addon = 500_000_00  # $500,000 in cents
    floor = 1_000_000_00  # $1,000,000 in cents
    sizer = CushionSizer(
        confidence_quantile=0.999,
        stress_addon_cents=stress_addon,
        treasury_floor_cents=floor,
    )

    # Net outflow scenario: outflow > inflow
    steps = [
        ForecastHorizonStep(
            step=i,
            bucket_index=i,
            inflow_p50=to_cents(4_000_000.0),
            inflow_p95=to_cents(4_200_000.0),
            inflow_p99=to_cents(4_400_000.0),
            inflow_p999=to_cents(4_600_000.0),
            outflow_p50=to_cents(5_000_000.0),
            outflow_p95=to_cents(5_300_000.0),
            outflow_p99=to_cents(5_500_000.0),
            outflow_p999=to_cents(5_800_000.0),
        )
        for i in range(1, 97)
    ]

    buffer_cents, q_deficit, _ = sizer.calculate_cushion(steps, wape_multiplier=1.0)
    expected_buffer = q_deficit + stress_addon + floor
    assert buffer_cents == expected_buffer
    assert q_deficit > 0


def test_wape_dynamic_cushion_widening():
    """Verify that degrading forecast accuracy widens the cushion automatically."""
    sizer = CushionSizer()

    steps = [
        ForecastHorizonStep(
            step=i,
            bucket_index=i,
            inflow_p50=to_cents(5_000_000.0),
            inflow_p95=to_cents(5_200_000.0),
            inflow_p99=to_cents(5_400_000.0),
            inflow_p999=to_cents(5_600_000.0),
            outflow_p50=to_cents(5_500_000.0),
            outflow_p95=to_cents(5_800_000.0),
            outflow_p99=to_cents(6_000_000.0),
            outflow_p999=to_cents(6_300_000.0),
        )
        for i in range(1, 97)
    ]

    normal_buffer, q_norm, _ = sizer.calculate_cushion(steps, wape_multiplier=1.0)
    widened_buffer, q_wide, _ = sizer.calculate_cushion(steps, wape_multiplier=1.3)

    assert widened_buffer > normal_buffer
