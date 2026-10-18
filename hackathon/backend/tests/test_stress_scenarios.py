import pytest
from backend.app.core.config import TreasuryConfig
from backend.app.ingestion.validator import ingest_and_validate_dataset
from backend.app.stress.engine import StressScenarioParams, run_stress_scenario


DATASET_PATH = "data/treasury_4tier_dataset.csv"
SCENARIO_IDS = [
    "OUTFLOW_MULT",
    "WITHDRAWAL_SPIKE",
    "DELAYED_DEPOSITS",
    "REPO_UNAVAILABLE",
    "LIQUIDATION_DELAY",
    "BOND_SHOCK",
    "EQUITY_CRASH",
    "CORRELATED_RUN",
    "OVERDRAFT_RESTRICTED",
    "COMBINED_WORST",
]


@pytest.fixture(scope="module")
def dataset_and_config():
    cfg = TreasuryConfig.load("config/treasury.yaml")
    df, report = ingest_and_validate_dataset(DATASET_PATH)
    return df, report["data_hash"], cfg


@pytest.mark.parametrize("scen_id", SCENARIO_IDS)
def test_each_prd_stress_scenario(dataset_and_config, scen_id):
    df, data_hash, cfg = dataset_and_config
    params = StressScenarioParams(scenario_id=scen_id, start_step=17, duration_hours=12)
    report = run_stress_scenario(
        base_df=df,
        data_hash=data_hash,
        base_config=cfg,
        params=params,
        horizon_steps=48,
    )

    assert report.scenario_id == scen_id
    assert report.min_cash_stressed_cents is not None
    # Verify stressed cash is <= unstressed cash (or stress impacted the system)
    assert report.min_cash_stressed_cents <= report.min_cash_unstressed_cents or scen_id in ["LIQUIDATION_DELAY", "BOND_SHOCK", "EQUITY_CRASH"]
