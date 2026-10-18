"""Multi-quantile probabilistic forecaster with EWMA error correction and WAPE tracking."""

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
import numpy as np

from reserve_juggler.config import CONFIG, to_cents
from reserve_juggler.models import ForecastHorizonStep, FlowBucket


class StaleDataException(Exception):
    """Raised when incoming telemetry data is stale."""
    pass


class Forecaster:
    def __init__(
        self,
        base_bucket_usd: float = CONFIG.BASE_BUCKET_VOLUME_USD,
        ewma_alpha: float = 0.25,
        rolling_window_buckets: int = 96,  # 24 hours of history
    ) -> None:
        self.base_bucket_usd = base_bucket_usd
        self.ewma_alpha = ewma_alpha
        self.rolling_window = rolling_window_buckets

        # EWMA error states (USD)
        self.ewma_inflow_error: float = 0.0
        self.ewma_outflow_error: float = 0.0

        # Rolling history for residual variance and WAPE
        self.recent_actual_inflows: deque[float] = deque(maxlen=rolling_window_buckets)
        self.recent_actual_outflows: deque[float] = deque(maxlen=rolling_window_buckets)
        self.recent_forecast_inflows: deque[float] = deque(maxlen=rolling_window_buckets)
        self.recent_forecast_outflows: deque[float] = deque(maxlen=rolling_window_buckets)

        self.last_update_time: Optional[datetime] = None
        self.current_wape_outflow: float = 0.04
        self.current_wape_inflow: float = 0.04
        self.combined_wape: float = 0.04

    def update_actuals(self, actual_bucket: FlowBucket) -> None:
        """Update EWMA error states and rolling history when a new bucket finishes."""
        # Check data staleness
        if self.last_update_time is not None:
            time_gap = (actual_bucket.timestamp - self.last_update_time).total_seconds() / 60.0
            if time_gap > CONFIG.STALE_DATA_TIMEOUT_MINUTES:
                raise StaleDataException(
                    f"Telemetry gap of {time_gap:.1f} minutes exceeds threshold "
                    f"of {CONFIG.STALE_DATA_TIMEOUT_MINUTES} minutes."
                )

        self.last_update_time = actual_bucket.timestamp

        act_in_usd = actual_bucket.inflow_cents / 100.0
        act_out_usd = actual_bucket.outflow_cents / 100.0

        # Calculate seasonal baseline for this bucket to update EWMA error
        base_in_usd, base_out_usd, _ = self._compute_profile(actual_bucket.timestamp)
        err_in = act_in_usd - (base_in_usd + self.ewma_inflow_error)
        err_out = act_out_usd - (base_out_usd + self.ewma_outflow_error)

        # Robust clipping on residuals to prevent runaway exponential expansion during extreme shocks
        max_err = 1.5 * self.base_bucket_usd
        err_in = float(np.clip(err_in, -max_err, max_err))
        err_out = float(np.clip(err_out, -max_err, max_err))

        # Update EWMA
        self.ewma_inflow_error = (
            self.ewma_alpha * err_in + (1.0 - self.ewma_alpha) * self.ewma_inflow_error
        )
        self.ewma_outflow_error = (
            self.ewma_alpha * err_out + (1.0 - self.ewma_alpha) * self.ewma_outflow_error
        )

        self.recent_actual_inflows.append(act_in_usd)
        self.recent_actual_outflows.append(act_out_usd)
        self.recent_forecast_inflows.append(base_in_usd + self.ewma_inflow_error)
        self.recent_forecast_outflows.append(base_out_usd + self.ewma_outflow_error)

        self._recalculate_wape()

    def _recalculate_wape(self) -> None:
        """Calculate Weighted Absolute Percentage Error (WAPE) over rolling window."""
        if len(self.recent_actual_outflows) < 10:
            self.current_wape_outflow = 0.04
            self.current_wape_inflow = 0.04
            self.combined_wape = 0.04
            return

        sum_actual_out = sum(self.recent_actual_outflows)
        sum_err_out = sum(
            abs(a - f) for a, f in zip(self.recent_actual_outflows, self.recent_forecast_outflows)
        )
        self.current_wape_outflow = sum_err_out / max(1.0, sum_actual_out)

        sum_actual_in = sum(self.recent_actual_inflows)
        sum_err_in = sum(
            abs(a - f) for a, f in zip(self.recent_actual_inflows, self.recent_forecast_inflows)
        )
        self.current_wape_inflow = sum_err_in / max(1.0, sum_actual_in)

        self.combined_wape = (sum_err_out + sum_err_in) / max(1.0, sum_actual_out + sum_actual_in)

    def get_wape_cushion_multiplier(self, is_peak_day: bool = False) -> float:
        """Returns cushion expansion factor when forecast accuracy degrades."""
        target = CONFIG.TARGET_WAPE_PEAK if is_peak_day else CONFIG.TARGET_WAPE_NORMAL
        if self.combined_wape > target:
            excess = self.combined_wape - target
            return 1.0 + excess * CONFIG.WAPE_EXPANSION_FACTOR
        return 1.0

    def _compute_profile(self, target_time: datetime) -> Tuple[float, float, bool]:
        """Compute base seasonal profile and scheduled calendar overrides."""
        hour = target_time.hour
        minute = target_time.minute
        time_float = hour + minute / 60.0
        weekday = target_time.weekday()
        day = target_time.day

        # Diurnal pattern
        diurnal = (
            0.85
            + 0.55 * np.sin((time_float - 7.0) * np.pi / 12.0)
            + 0.20 * np.cos((time_float - 14.0) * np.pi / 6.0)
        )
        diurnal = float(np.clip(diurnal, 0.25, 1.65))

        # Day-of-week
        dow_mult = 1.05 + 0.05 * (weekday == 4) if weekday < 5 else 0.65

        # Scheduled overrides: Paydays (1st and 15th) and Holiday (25th)
        is_override = False
        payday_in, payday_out = 1.0, 1.0
        if day in (1, 15):
            is_override = True
            if 6 <= hour <= 12:
                payday_in, payday_out = 2.4, 1.3
            elif 13 <= hour <= 21:
                payday_in, payday_out = 1.3, 2.4
            else:
                payday_in, payday_out = 1.0, 1.0
        elif day == 25:
            is_override = True
            if 9 <= hour <= 18:
                payday_in, payday_out = 1.2, 2.2
            elif 19 <= hour <= 23 or 0 <= hour <= 3:
                payday_in, payday_out = 2.2, 1.2
            else:
                payday_in, payday_out = 1.0, 1.0

        in_mean = self.base_bucket_usd * diurnal * dow_mult * payday_in
        out_mean = self.base_bucket_usd * diurnal * dow_mult * payday_out
        return in_mean, out_mean, is_override

    def forecast_24h(
        self, current_time: datetime, current_bucket_index: int
    ) -> List[ForecastHorizonStep]:
        """Produce 96-bucket (24-hour) multi-quantile forecast."""
        if len(self.recent_actual_outflows) >= 10:
            residuals = [
                a - f
                for a, f in zip(self.recent_actual_outflows, self.recent_forecast_outflows)
            ]
            std_err_out = float(np.std(residuals))
            std_err_out = float(np.clip(std_err_out, 0.03 * self.base_bucket_usd, 0.15 * self.base_bucket_usd))
            res_in = [
                a - f
                for a, f in zip(self.recent_actual_inflows, self.recent_forecast_inflows)
            ]
            std_err_in = float(np.std(res_in))
            std_err_in = float(np.clip(std_err_in, 0.03 * self.base_bucket_usd, 0.15 * self.base_bucket_usd))
        else:
            std_err_out = 0.05 * self.base_bucket_usd
            std_err_in = 0.05 * self.base_bucket_usd

        steps: List[ForecastHorizonStep] = []
        z95 = 1.644853
        z99 = 2.326348
        z999 = 3.090232
        decay_rate = 0.75  # Intraday shock half-life of ~2.4 buckets (36 minutes)

        for step in range(1, CONFIG.FORECAST_HORIZON_BUCKETS + 1):
            future_bucket = current_bucket_index + step
            future_time = current_time + timedelta(minutes=step * CONFIG.BUCKET_MINUTES)
            base_in, base_out, is_override = self._compute_profile(future_time)

            correction_factor = decay_rate ** step
            point_in = max(25_000.0, base_in + self.ewma_inflow_error * correction_factor)
            point_out = max(25_000.0, base_out + self.ewma_outflow_error * correction_factor)

            sigma_out = std_err_out * np.sqrt(1.0 + 0.03 * (step - 1))
            sigma_in = std_err_in * np.sqrt(1.0 + 0.03 * (step - 1))

            steps.append(
                ForecastHorizonStep(
                    step=step,
                    bucket_index=future_bucket,
                    inflow_p50=to_cents(point_in),
                    inflow_p95=to_cents(point_in + z95 * sigma_in),
                    inflow_p99=to_cents(point_in + z99 * sigma_in),
                    inflow_p999=to_cents(point_in + z999 * sigma_in),
                    outflow_p50=to_cents(point_out),
                    outflow_p95=to_cents(point_out + z95 * sigma_out),
                    outflow_p99=to_cents(point_out + z99 * sigma_out),
                    outflow_p999=to_cents(point_out + z999 * sigma_out),
                    is_scheduled_override=is_override,
                )
            )

        return steps
