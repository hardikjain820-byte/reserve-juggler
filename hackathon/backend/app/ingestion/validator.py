from __future__ import annotations
import os
import hashlib
from datetime import datetime
from typing import Dict, Any, Tuple
import pandas as pd


REQUIRED_COLUMNS = [
    "timestamp",
    "deposits_usd",
    "withdrawals_usd",
    "net_flow_usd",
    "repo_sweep_window_open",
    "repo_sweep_mature",
    "tier1_repo_rate_apy",
    "tier2_bond_yield_pct",
    "tier2_bond_price_index",
    "tier2_bond_mod_duration",
    "tier3_stock_index_price",
    "tier3_stock_volatility_pct",
    "tier1_early_redemption_haircut_pct",
    "tier2_bond_liquidation_haircut_pct",
    "tier3_stock_liquidation_haircut_pct",
    "emergency_overdraft_penalty_apr_pct",
]


class DataValidationError(Exception):
    pass


def compute_file_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def ingest_and_validate_dataset(
    filepath: str,
    as_of_str: str = "2026-10-17T00:00:00Z"
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Dataset not found: {filepath}")

    data_hash = compute_file_sha256(filepath)
    df = pd.read_csv(filepath)

    # 1. Schema check
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise DataValidationError(f"DATA_VALIDATION_FAILED: Missing columns {missing}")
    if len(df.columns) != len(REQUIRED_COLUMNS):
        extra = [c for c in df.columns if c not in REQUIRED_COLUMNS]
        raise DataValidationError(f"DATA_VALIDATION_FAILED: Unexpected extra columns {extra}")

    # 2. Row count check
    if len(df) != 8760:
        raise DataValidationError(f"DATA_VALIDATION_FAILED: Expected 8760 rows, found {len(df)}")

    # 3. Nulls
    null_counts = df.isnull().sum().to_dict()
    if any(v > 0 for v in null_counts.values()):
        raise DataValidationError(f"DATA_VALIDATION_FAILED: Null values present: {null_counts}")

    # 4. Duplicate timestamps
    df["ts_dt"] = pd.to_datetime(df["timestamp"])
    if df["ts_dt"].duplicated().any():
        raise DataValidationError("DATA_VALIDATION_FAILED: Duplicate timestamps found")

    # 5. Timestamp monotonicity & regularity
    time_diffs = df["ts_dt"].diff().dropna()
    expected_diff = pd.Timedelta(hours=1)
    if not (time_diffs == expected_diff).all():
        raise DataValidationError("DATA_VALIDATION_FAILED: Non-monotonic or irregular timestamp diffs detected")

    # 6. Flow positivity
    if (df["deposits_usd"] <= 0).any() or (df["withdrawals_usd"] <= 0).any():
        raise DataValidationError("DATA_VALIDATION_FAILED: Non-positive deposits or withdrawals found")

    # 7. Net flow identity: deposits - withdrawals - net_flow <= 0.02
    diff = (df["deposits_usd"] - df["withdrawals_usd"] - df["net_flow_usd"]).abs()
    max_dev = diff.max()
    if max_dev > 0.02:
        raise DataValidationError(f"DATA_VALIDATION_FAILED: Net flow identity deviation {max_dev} > 0.02")

    # 8. Mutual exclusivity of window_open and mature
    both_true = df["repo_sweep_window_open"] & df["repo_sweep_mature"]
    if both_true.any():
        raise DataValidationError("DATA_VALIDATION_FAILED: repo_sweep_window_open and repo_sweep_mature both True")

    # 9. Non-negative haircuts and rates
    haircut_cols = [
        "tier1_early_redemption_haircut_pct",
        "tier2_bond_liquidation_haircut_pct",
        "tier3_stock_liquidation_haircut_pct",
        "emergency_overdraft_penalty_apr_pct",
    ]
    for c in haircut_cols:
        if (df[c] < 0).any():
            raise DataValidationError(f"DATA_VALIDATION_FAILED: Negative rate or haircut in {c}")

    # 10. Tag is_future
    as_of_dt = pd.to_datetime(as_of_str).tz_localize(None)
    df["is_future"] = df["ts_dt"] > as_of_dt
    future_count = int(df["is_future"].sum())
    df.drop(columns=["ts_dt"], inplace=True)

    report = {
        "passed": True,
        "rows": len(df),
        "columns": list(df.columns),
        "data_hash": data_hash,
        "future_rows_count": future_count,
        "max_net_flow_dev": float(max_dev),
        "as_of_timestamp": as_of_str,
    }

    return df, report
