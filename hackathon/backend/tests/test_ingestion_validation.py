import pytest
import os
import pandas as pd
from backend.app.ingestion.validator import ingest_and_validate_dataset, DataValidationError


DATASET_PATH = "data/treasury_4tier_dataset.csv"


def test_ingestion_ac1_real_dataset():
    """Verify AC-1:
    8760 rows, 16 columns, 0 nulls, 0 duplicates, hourly monotonic,
    max net flow dev <= 0.02, is_future == 1823.
    """
    assert os.path.exists(DATASET_PATH), f"Dataset not found at {DATASET_PATH}"
    df, report = ingest_and_validate_dataset(DATASET_PATH, as_of_str="2026-10-17T00:00:00Z")

    assert report["passed"] is True
    assert report["rows"] == 8760
    assert len(report["columns"]) == 17  # 16 original + is_future
    assert report["future_rows_count"] == 1823
    assert report["max_net_flow_dev"] <= 0.02


def test_ingestion_ac2_corrupt_fixtures(tmp_path):
    """Verify AC-2:
    Corrupt fixtures are rejected with DataValidationError.
    """
    # 1. Missing column
    df = pd.read_csv(DATASET_PATH).drop(columns=["tier1_repo_rate_apy"])
    bad_csv = tmp_path / "missing_col.csv"
    df.to_csv(bad_csv, index=False)
    with pytest.raises(DataValidationError, match="Missing columns"):
        ingest_and_validate_dataset(str(bad_csv))

    # 2. Duplicate timestamp
    df = pd.read_csv(DATASET_PATH)
    df.loc[1, "timestamp"] = df.loc[0, "timestamp"]
    bad_csv2 = tmp_path / "dup_ts.csv"
    df.to_csv(bad_csv2, index=False)
    with pytest.raises(DataValidationError, match="Duplicate timestamps"):
        ingest_and_validate_dataset(str(bad_csv2))

    # 3. Net flow mismatch > $0.02
    df = pd.read_csv(DATASET_PATH)
    df.loc[5, "net_flow_usd"] += 1.0  # $1 mismatch
    bad_csv3 = tmp_path / "bad_net.csv"
    df.to_csv(bad_csv3, index=False)
    with pytest.raises(DataValidationError, match="Net flow identity deviation"):
        ingest_and_validate_dataset(str(bad_csv3))

    # 4. Both sweep window open and mature True
    df = pd.read_csv(DATASET_PATH)
    df.loc[10, "repo_sweep_window_open"] = True
    df.loc[10, "repo_sweep_mature"] = True
    bad_csv4 = tmp_path / "both_flags.csv"
    df.to_csv(bad_csv4, index=False)
    with pytest.raises(DataValidationError, match="repo_sweep_window_open and repo_sweep_mature both True"):
        ingest_and_validate_dataset(str(bad_csv4))
