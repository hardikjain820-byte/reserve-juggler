from __future__ import annotations
import pandas as pd


class LeakageError(Exception):
    """Raised when an operation attempts to access lookahead data."""
    pass


def build_features(df: pd.DataFrame, as_of_index: int) -> pd.DataFrame:
    """Builds features strictly using data strictly prior to as_of_index.
    Raises LeakageError if as_of_index > len(df) or invalid.
    """
    if as_of_index < 0 or as_of_index > len(df):
        raise LeakageError(f"Invalid as_of_index {as_of_index} for dataframe of length {len(df)}")

    # Slice strictly before as_of_index
    sub_df = df.iloc[:as_of_index].copy()
    
    if len(sub_df) == 0:
        return pd.DataFrame()

    sub_df["ts"] = pd.to_datetime(sub_df["timestamp"])
    sub_df["hour"] = sub_df["ts"].dt.hour
    sub_df["dow"] = sub_df["ts"].dt.dayofweek
    sub_df["dom"] = sub_df["ts"].dt.day
    sub_df["is_month_start"] = sub_df["dom"].isin([1, 2, 3])
    sub_df["is_mid_month"] = sub_df["dom"].isin([15, 16, 17])

    return sub_df
