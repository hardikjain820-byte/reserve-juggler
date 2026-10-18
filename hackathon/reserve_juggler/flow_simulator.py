"""Flow Simulator: generates realistic 15-minute bucket inflows and outflows."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import numpy as np

from reserve_juggler.config import CONFIG, to_cents
from reserve_juggler.models import FlowBucket


@dataclass
class ShockConfig:
    start_bucket: int
    duration_buckets: int = 8  # 2 hours = 8 * 15m
    outflow_multiplier: float = 3.0
    inflow_multiplier: float = 1.0
    description: str = "3x withdrawal surge for 2 hours"


class FlowSimulator:
    def __init__(
        self,
        start_time: Optional[datetime] = None,
        base_bucket_usd: float = CONFIG.BASE_BUCKET_VOLUME_USD,  # $2.5M in + $2.5M out = $20M/hr gross
        seed: Optional[int] = 42,
    ) -> None:
        self.start_time = start_time or datetime(2026, 10, 1, 0, 0, 0)
        self.base_bucket_usd = base_bucket_usd
        self.rng = np.random.default_rng(seed)
        self.shocks: List[ShockConfig] = []

    def add_shock(self, shock: ShockConfig) -> None:
        self.shocks.append(shock)

    def _get_time_of_day_multiplier(self, hour: int, minute: int) -> float:
        """Realistic banking diurnal curve: troughs at 03:00, peaks at 11:00 and 16:00."""
        time_float = hour + minute / 60.0
        diurnal = (
            0.85
            + 0.55 * np.sin((time_float - 7.0) * np.pi / 12.0)
            + 0.20 * np.cos((time_float - 14.0) * np.pi / 6.0)
        )
        return float(np.clip(diurnal, 0.25, 1.65))

    def _get_day_of_week_multiplier(self, weekday: int) -> float:
        """Monday=0 ... Sunday=6. Weekdays have higher B2B volume; weekends lower."""
        if weekday < 5:  # Mon - Fri
            return 1.05 + 0.05 * (weekday == 4)  # Friday has settlement surge
        return 0.65  # Weekend retail-only

    def _get_payday_multiplier(self, day_of_month: int, hour: int) -> tuple[float, float, Optional[str]]:
        """Payday spikes on 1st and 15th. Inflows surge in morning; outflows surge afternoon."""
        if day_of_month in (1, 15):
            if 6 <= hour <= 12:
                # Corporate payroll direct deposit batch
                return 2.4, 1.3, f"Payday direct deposit wave (Day {day_of_month})"
            elif 13 <= hour <= 21:
                # Customer bills & disbursement wave
                return 1.3, 2.4, f"Payday disbursement wave (Day {day_of_month})"
            return 1.0, 1.0, f"Payday background (Day {day_of_month})"
        return 1.0, 1.0, None

    def _get_holiday_multiplier(self, day_of_month: int, hour: int) -> tuple[float, float, Optional[str]]:
        """Shopping holiday on Day 25: Daytime customer spending + Evening merchant settlement batch."""
        if day_of_month == 25:
            if 9 <= hour <= 18:
                # E-commerce and retail shopping checkout wave
                return 1.2, 2.2, "Shopping Holiday retail spending surge"
            elif 19 <= hour <= 23 or 0 <= hour <= 3:
                # Acquirer & card network batch settlements into merchant accounts
                return 2.2, 1.2, "Shopping Holiday merchant settlement batch"
            return 1.0, 1.0, "Shopping Holiday transition"
        return 1.0, 1.0, None

    def generate_bucket(self, bucket_index: int) -> FlowBucket:
        bucket_time = self.start_time + timedelta(minutes=bucket_index * CONFIG.BUCKET_MINUTES)
        hour = bucket_time.hour
        minute = bucket_time.minute
        weekday = bucket_time.weekday()
        day = bucket_time.day

        tod_mult = self._get_time_of_day_multiplier(hour, minute)
        dow_mult = self._get_day_of_week_multiplier(weekday)
        payday_in, payday_out, payday_note = self._get_payday_multiplier(day, hour)
        hol_in, hol_out, hol_note = self._get_holiday_multiplier(day, hour)

        scheduled_note = payday_note or hol_note

        # Base nominal bucket flows: $2.5M in, $2.5M out
        inflow_mean = self.base_bucket_usd * tod_mult * dow_mult * payday_in * hol_in
        outflow_mean = self.base_bucket_usd * tod_mult * dow_mult * payday_out * hol_out

        # Gaussian random noise (sigma ~ 5% of volume)
        noise_in = self.rng.normal(0.0, 0.05 * inflow_mean)
        noise_out = self.rng.normal(0.0, 0.05 * outflow_mean)

        inflow_usd = max(25_000.0, inflow_mean + noise_in)
        outflow_usd = max(25_000.0, outflow_mean + noise_out)

        # Check for active shocks
        is_shock = False
        for shock in self.shocks:
            if shock.start_bucket <= bucket_index < shock.start_bucket + shock.duration_buckets:
                inflow_usd *= shock.inflow_multiplier
                outflow_usd *= shock.outflow_multiplier
                is_shock = True
                scheduled_note = f"SHOCK INJECTED: {shock.description}"

        return FlowBucket(
            bucket_index=bucket_index,
            timestamp=bucket_time,
            inflow_cents=to_cents(inflow_usd),
            outflow_cents=to_cents(outflow_usd),
            scheduled_type=scheduled_note,
            is_shock=is_shock,
        )

    def generate_series(self, num_buckets: int) -> List[FlowBucket]:
        return [self.generate_bucket(i) for i in range(num_buckets)]
