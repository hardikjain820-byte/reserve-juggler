import pytest
from backend.app.audit.chain import AuditChain


def test_audit_chain_valid_and_tamper_detection():
    chain = AuditChain(run_id="run_audit_test", data_hash="dummy_data_hash", config_hash="dummy_config_hash")

    # Add 5 records
    for i in range(1, 6):
        chain.append_record(
            step_index=i,
            action=f"ACTION_{i}",
            entity_type="TXN",
            entity_id=f"txn_{i}",
            payload={"amount": i * 100},
            balances_before={"CASH": (i - 1) * 100},
            balances_after={"CASH": i * 100},
            reason="TEST",
        )

    # 1. Unmodified chain must pass
    valid, checked, err = chain.verify()
    assert valid is True
    assert checked == 5
    assert err is None

    # 2. Tamper with record 3 payload
    chain.records[2].payload["amount"] = 999999
    valid, checked, err = chain.verify()
    assert valid is False
    assert "record_hash mismatch at seq 3" in err

    # 3. Restore and test swap tampering
    chain.records[2].payload["amount"] = 300  # restore
    # Swap records 1 and 2
    chain.records[1], chain.records[2] = chain.records[2], chain.records[1]
    valid, checked, err = chain.verify()
    assert valid is False
