import pytest
from fastapi.testclient import TestClient
from backend.app.api.main import app


client = TestClient(app)


def test_api_health_endpoint():
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "HEALTHY"
    assert data["mode"] == "SIMULATION"
    assert data["dataset_loaded"] is True
    assert data["rows"] == 8760


def test_api_config_endpoint():
    res = client.get("/api/v1/config")
    assert res.status_code == 200
    data = res.json()
    assert "opening_cash_usd" in data
    assert data["stock_max_pct_of_portfolio"] == 0.0


def test_api_sim_step_and_idempotency():
    # 1. Step without key
    res1 = client.post("/api/v1/sim/runs/run_live_01/step")
    assert res1.status_code == 200
    step_data = res1.json()
    assert "step" in step_data

    # 2. Step with Idempotency-Key
    idem_key = "test_key_abc_123"
    res2 = client.post("/api/v1/sim/runs/run_live_01/step", headers={"Idempotency-Key": idem_key})
    assert res2.status_code == 200
    data2 = res2.json()

    # 3. Replay same Idempotency-Key
    res3 = client.post("/api/v1/sim/runs/run_live_01/step", headers={"Idempotency-Key": idem_key})
    assert res3.status_code == 200
    data3 = res3.json()
    # Replay must return identical result without advancing
    assert data2 == data3


def test_api_kpis_endpoint():
    res = client.get("/api/v1/kpis?run_id=run_live_01")
    assert res.status_code == 200
    data = res.json()
    assert "cash_cents" in data
    assert "headroom_cents" in data
    assert "payout_success" in data


def test_api_manual_sweep_preview_validation():
    # Attempting to sweep $999B (exceeding surplus)
    res = client.post(
        "/api/v1/treasury/sweeps/preview",
        json={"tier": 1, "amount_cents": "99900000000000"}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["valid"] is False
    assert "SWEEP_EXCEEDS_SURPLUS" in data["reason_codes"]


def test_api_audit_verify_endpoint():
    res = client.get("/api/v1/audit/verify?run_id=run_live_01")
    assert res.status_code == 200
    data = res.json()
    assert data["valid"] is True
    assert data["checked_records"] > 0
    assert data["error"] is None


def test_api_openapi_and_docs_endpoints():
    # 1. /openapi.json must return 200 with valid schema
    res_openapi = client.get("/openapi.json")
    assert res_openapi.status_code == 200
    schema = res_openapi.json()
    assert "openapi" in schema
    assert "paths" in schema
    assert "/health" in schema["paths"]
    assert "/api/v1/backtests" in schema["paths"]

    # 2. /docs must return 200 HTML
    res_docs = client.get("/docs")
    assert res_docs.status_code == 200
    assert "swagger-ui" in res_docs.text.lower()
