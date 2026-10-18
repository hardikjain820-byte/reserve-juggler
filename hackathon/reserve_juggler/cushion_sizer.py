"""Cushion Sizer: calculates the mathematical required cash buffer.

Implements:
required_buffer = Q_q( max_{k <= H} cumulative(Out_t - In_t) ) * wape_multiplier + stress_addon + treasury_floor
"""

from typing import List, Optional, Tuple
import numpy as np

from reserve_juggler.config import CONFIG, to_cents
from reserve_juggler.models import ForecastHorizonStep


class CushionSizer:
    def __init__(
        self,
        confidence_quantile: float = CONFIG.CONFIDENCE_QUANTILE,
        stress_addon_cents: int = CONFIG.stress_addon_cents,
        treasury_floor_cents: int = CONFIG.treasury_floor_cents,
        num_monte_carlo_paths: int = 3000,
        seed: Optional[int] = 42,
    ) -> None:
        self.q = confidence_quantile
        self.stress_addon_cents = stress_addon_cents
        self.treasury_floor_cents = treasury_floor_cents
        self.num_paths = num_monte_carlo_paths
        self.rng = np.random.default_rng(seed)

    def calculate_cushion(
        self,
        forecast_steps: List[ForecastHorizonStep],
        horizon_buckets: Optional[int] = None,
        wape_multiplier: float = 1.0,
        manual_addon_cents: int = 0,
    ) -> Tuple[int, int, float]:
        """Calculate required cash buffer in integer minor units (cents).

        Returns:
            (required_buffer_cents, q_max_deficit_cents, simulated_p999_usd)
        """
        if not forecast_steps:
            return self.treasury_floor_cents, 0, 0.0

        H = min(len(forecast_steps), horizon_buckets or CONFIG.FORECAST_HORIZON_BUCKETS)
        steps = forecast_steps[:H]

        # Extract expected net outflows (Outflow - Inflow) in USD
        # For each step:
        # Outflow mean = outflow_p50
        # Inflow mean = inflow_p50
        # Variance from difference between P95 and P50: sigma ~ (P95 - P50) / 1.645
        z95 = 1.644853

        means = np.zeros(H, dtype=np.float64)
        sigmas = np.zeros(H, dtype=np.float64)

        for i, s in enumerate(steps):
            out_mean = s.outflow_p50 / 100.0
            in_mean = s.inflow_p50 / 100.0
            means[i] = out_mean - in_mean

            out_sigma = max(10_000.0, (s.outflow_p95 - s.outflow_p50) / (100.0 * z95))
            in_sigma = max(10_000.0, (s.inflow_p95 - s.inflow_p50) / (100.0 * z95))
            sigmas[i] = np.sqrt(out_sigma**2 + in_sigma**2)

        # Vectorized path simulation of cumulative net deficits across horizon H
        # Standard normal random matrix: (num_paths, H)
        z_shocks = self.rng.standard_normal((self.num_paths, H))
        # Simulated net outflows at each step
        sim_flows = means + sigmas * z_shocks  # shape (num_paths, H)
        # Cumulative deficits over time
        cum_deficits = np.cumsum(sim_flows, axis=1)  # shape (num_paths, H)
        # Maximum cumulative deficit along each path
        max_path_deficits = np.max(cum_deficits, axis=1)  # shape (num_paths,)

        # Compute empirical quantile Q_q
        q_deficit_usd = float(np.quantile(max_path_deficits, self.q))
        q_deficit_cents = max(0, to_cents(q_deficit_usd))

        # Apply WAPE expansion factor if forecast accuracy is degraded
        adjusted_q_cents = int(round(q_deficit_cents * wape_multiplier))

        # Required buffer formula:
        # required_buffer = Q_q(max cumulative deficit) + stress_addon + treasury_floor
        buffer_calc_cents = (
            adjusted_q_cents
            + self.stress_addon_cents
            + self.treasury_floor_cents
            + manual_addon_cents
        )

        # Enforce hard treasury floor: no model output can go below the floor
        final_buffer_cents = max(buffer_calc_cents, self.treasury_floor_cents)

        return final_buffer_cents, q_deficit_cents, q_deficit_usd
