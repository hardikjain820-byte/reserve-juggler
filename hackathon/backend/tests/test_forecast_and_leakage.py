import pytest
import pandas as pd
from backend.app.ingestion.validator import ingest_and_validate_dataset
from backend.app.forecast.feature_store import build_features, LeakageError
from backend.app.forecast.models import ForecastEngine, evaluate_forecasts


DATASET_PATH = "data/treasury_4tier_dataset.csv"


def test_leakage_guard_future_tampering_immunity():
    """Verify that tampering with any future rows (>= as_of_index)
    produces ZERO difference in forecasts at as_of_index.
    """
    df, _ = ingest_and_validate_dataset(DATASET_PATH)
    as_of_idx = 1000  # evaluate as of step 1000

    # 1. Base clean forecast
    preds_clean = evaluate_forecasts(df, as_of_index=as_of_idx, target_col="withdrawals_usd", horizons=[1, 6, 24])

    # 2. Tampered dataset: inject massive 10x spike at as_of_idx and future rows
    df_tampered = df.copy()
    df_tampered.loc[as_of_idx:as_of_idx + 100, "withdrawals_usd"] *= 10.0
    df_tampered.loc[as_of_idx:as_of_idx + 100, "deposits_usd"] *= 10.0

    preds_tampered = evaluate_forecasts(df_tampered, as_of_index=as_of_idx, target_col="withdrawals_usd", horizons=[1, 6, 24])

    # 3. Assert exact equality
    for p_c, p_t in zip(preds_clean, preds_tampered):
        assert p_c.p50_cents == p_t.p50_cents
        assert p_c.p95_cents == p_t.p95_cents
        assert p_c.p99_cents == p_t.p99_cents
        assert p_c.p999_cents == p_t.p999_cents


def test_leakage_error_on_invalid_bounds():
    df, _ = ingest_and_validate_dataset(DATASET_PATH)
    with pytest.raises(LeakageError):
        build_features(df, as_of_index=len(df) + 100)
    with pytest.raises(LeakageError):
        build_features(df, as_of_index=-5)


def test_forecast_monotonic_quantiles():
    """Verify that quantile predictions satisfy P50 <= P95 <= P99 <= P99.9."""
    df, _ = ingest_and_validate_dataset(DATASET_PATH)
    preds = evaluate_forecasts(df, as_of_index=2000, target_col="withdrawals_usd", horizons=[1, 3, 6, 12, 24])

    for p in preds:
        assert p.p50_cents > 0
        assert p.p50_cents <= p.p95_cents
        assert p.p95_cents <= p.p99_cents
        assert p.p99_cents <= p.p999_cents
        assert p.low_confidence_p999 is True
