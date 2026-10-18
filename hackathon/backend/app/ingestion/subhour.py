from __future__ import annotations
import math
import pandas as pd


def derive_15min_dataset(df_hourly: pd.DataFrame) -> pd.DataFrame:
    """Derives 15-minute sub-steps from hourly rows deterministically.
    Preserves hourly deposit and withdrawal totals to the exact cent.
    Flags each row as derived=True.
    """
    sub_rows = []

    for _, row in df_hourly.iterrows():
        base_ts = pd.to_datetime(row["timestamp"])
        
        # Exact cent conversion
        dep_cents = int(round(float(row["deposits_usd"]) * 100))
        wd_cents = int(round(float(row["withdrawals_usd"]) * 100))

        # Integer split across 4 quarters with remainder in 4th quarter
        dep_q = dep_cents // 4
        dep_r = dep_cents - (dep_q * 3)

        wd_q = wd_cents // 4
        wd_r = wd_cents - (wd_q * 3)

        quarters = [
            (dep_q, wd_q),
            (dep_q, wd_q),
            (dep_q, wd_q),
            (dep_r, wd_r),
        ]

        for i, (d_c, w_c) in enumerate(quarters):
            sub_ts = base_ts + pd.Timedelta(minutes=15 * i)
            sub_row = row.to_dict()
            sub_row["timestamp"] = str(sub_ts)
            sub_row["deposits_usd"] = d_c / 100.0
            sub_row["withdrawals_usd"] = w_c / 100.0
            sub_row["net_flow_usd"] = (d_c - w_c) / 100.0
            sub_row["step_minutes"] = 15
            sub_row["derived"] = True

            # Repo flags only active on the top of the hour (:00)
            if i > 0:
                sub_row["repo_sweep_window_open"] = False
                sub_row["repo_sweep_mature"] = False

            sub_rows.append(sub_row)

    return pd.DataFrame(sub_rows)
