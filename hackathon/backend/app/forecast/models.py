from __future__ import annotations
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
from pydantic import BaseModel
from backend.app.forecast.feature_store import build_features, LeakageError


class ForecastQuantiles(BaseModel):
    horizon_h: int
    p50_cents: int
    p95_cents: int
    p99_cents: int
    p999_cents: int
    low_confidence_p999: bool = True


class ForecastEngine:
    def __init__(self, target_col: str):
        self.target_col = target_col
        self.profile_m2: Dict[Tuple[int, int], float] = {}
        self.cal_multipliers: Dict[int, float] = {}
        self.ratio_quantiles: Dict[str, float] = {
            "p50": 1.0,
            "p95": 1.25,
            "p99": 1.50,
            "p999": 1.85,
        }
        self.fitted_history_len = 0

    def fit(self, df_history: pd.DataFrame) -> None:
        """Fits profiles and empirical ratio quantiles strictly on historical data."""
        if len(df_history) < 24:
            return  # insufficient burn-in

        self.fitted_history_len = len(df_history)
        df = df_history.copy()
        if "ts" not in df.columns:
            df["ts"] = pd.to_datetime(df["timestamp"])
            df["hour"] = df["ts"].dt.hour
            df["dow"] = df["ts"].dt.dayofweek
            df["dom"] = df["ts"].dt.day

        # 1. M2 Profile: hour x dow mean
        grouped = df.groupby(["hour", "dow"])[self.target_col].mean().to_dict()
        self.profile_m2 = grouped

        # 2. Calendar multipliers for dom in [1, 2, 3, 15, 16, 17]
        overall_mean = df[self.target_col].mean()
        cal_days = [1, 2, 3, 15, 16, 17]
        for d in cal_days:
            sub = df[df["dom"] == d]
            if len(sub) > 0:
                self.cal_multipliers[d] = float(sub[self.target_col].mean() / max(overall_mean, 1e-6))
            else:
                self.cal_multipliers[d] = 1.0

        # 3. Residual ratios for empirical quantiles
        # ratio = actual / profile
        ratios = []
        for _, row in df.iterrows():
            h, dow = int(row["hour"]), int(row["dow"])
            prof = self.profile_m2.get((h, dow), overall_mean)
            act = float(row[self.target_col])
            if prof > 0:
                ratios.append(act / prof)

        if ratios:
            ratios_arr = np.array(ratios)
            self.ratio_quantiles = {
                "p50": float(np.percentile(ratios_arr, 50)),
                "p95": float(np.percentile(ratios_arr, 95)),
                "p99": float(np.percentile(ratios_arr, 99)),
                "p999": float(np.percentile(ratios_arr, 99.9)),
            }

    def predict_point(self, target_ts: pd.Timestamp, model_id: str = "M3") -> float:
        """Generates point forecast for target timestamp."""
        h = target_ts.hour
        dow = target_ts.dayofweek
        dom = target_ts.day

        base_val = self.profile_m2.get((h, dow), 10_000_000.0)

        if model_id == "M2":
            return base_val
        elif model_id == "M3":
            # Apply calendar multiplier if applicable
            mult = self.cal_multipliers.get(dom, 1.0)
            return base_val * mult
        else:
            return base_val

    def predict_quantiles(self, target_ts: pd.Timestamp, horizon_h: int = 1, model_id: str = "M3") -> ForecastQuantiles:
        point = self.predict_point(target_ts, model_id=model_id)
        
        # Multiply by empirical ratio quantiles
        p50 = max(0, point * self.ratio_quantiles["p50"])
        p95 = max(p50, point * self.ratio_quantiles["p95"])
        p99 = max(p95, point * self.ratio_quantiles["p99"])
        p999 = max(p99, point * self.ratio_quantiles["p999"])

        return ForecastQuantiles(
            horizon_h=horizon_h,
            p50_cents=int(round(p50 * 100)),
            p95_cents=int(round(p95 * 100)),
            p99_cents=int(round(p99 * 100)),
            p999_cents=int(round(p999 * 100)),
            low_confidence_p999=True,
        )


def evaluate_forecasts(
    df: pd.DataFrame,
    as_of_index: int,
    target_col: str,
    horizons: List[int] = [1, 6, 12, 24],
    model_id: str = "M3",
) -> List[ForecastQuantiles]:
    """Evaluates multi-horizon forecasts with strict leakage protection."""
    # Build historical features strictly before as_of_index
    df_hist = build_features(df, as_of_index)
    if len(df_hist) == 0:
        raise LeakageError("No history available prior to as_of_index")

    forecaster = ForecastEngine(target_col=target_col)
    forecaster.fit(df_hist)

    as_of_ts = pd.to_datetime(df.iloc[as_of_index - 1]["timestamp"])

    results = []
    for h in horizons:
        target_ts = as_of_ts + pd.Timedelta(hours=h)
        q = forecaster.predict_quantiles(target_ts, horizon_h=h, model_id=model_id)
        results.append(q)

    return results
