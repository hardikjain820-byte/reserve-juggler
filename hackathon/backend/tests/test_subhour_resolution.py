import pytest
import pandas as pd
from backend.app.ingestion.validator import ingest_and_validate_dataset
from backend.app.ingestion.subhour import derive_15min_dataset


DATASET_PATH = "data/treasury_4tier_dataset.csv"


def test_15min_flow_conservation_and_labeling():
    """Verify that derived 15-minute steps conserve hourly totals to the exact cent
    and clearly label all rows as derived=True.
    """
    df, _ = ingest_and_validate_dataset(DATASET_PATH)
    # Test over first 168 hours (1 full week)
    df_sample = df.iloc[:168].copy()
    df_15min = derive_15min_dataset(df_sample)

    assert len(df_15min) == 168 * 4
    assert bool(df_15min["derived"].all())

    # Check each hour's conservation
    for h in range(168):
        orig_row = df_sample.iloc[h]
        orig_dep_cents = int(round(orig_row["deposits_usd"] * 100))
        orig_wd_cents = int(round(orig_row["withdrawals_usd"] * 100))

        sub_block = df_15min.iloc[h * 4 : (h + 1) * 4]
        sub_dep_cents = sum(int(round(r * 100)) for r in sub_block["deposits_usd"])
        sub_wd_cents = sum(int(round(r * 100)) for r in sub_block["withdrawals_usd"])

        assert sub_dep_cents == orig_dep_cents, f"Hour {h} deposit mismatch"
        assert sub_wd_cents == orig_wd_cents, f"Hour {h} withdrawal mismatch"

        # Check that :15, :30, :45 do not trigger repo windows
        for i in range(1, 4):
            assert not bool(sub_block.iloc[i]["repo_sweep_window_open"])
            assert not bool(sub_block.iloc[i]["repo_sweep_mature"])
