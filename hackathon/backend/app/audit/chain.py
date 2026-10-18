from __future__ import annotations
from typing import Dict, List, Optional, Tuple, Any
from pydantic import BaseModel
import hashlib
import json


class AuditRecord(BaseModel):
    seq: int
    run_id: str
    step_index: int
    action: str
    entity_type: str
    entity_id: str
    payload: Dict[str, Any]
    balances_before: Dict[str, int]
    balances_after: Dict[str, int]
    reason: str
    prev_hash: str
    record_hash: str


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class AuditChain:
    def __init__(self, run_id: str, data_hash: str, config_hash: str):
        self.run_id = run_id
        genesis_raw = f"RESERVE_JUGGLER_GENESIS_V1|{data_hash}|{config_hash}"
        self.genesis_hash = hashlib.sha256(genesis_raw.encode("utf-8")).hexdigest()
        self.records: List[AuditRecord] = []

    def append_record(
        self,
        step_index: int,
        action: str,
        entity_type: str,
        entity_id: str,
        payload: Dict[str, Any],
        balances_before: Dict[str, int],
        balances_after: Dict[str, int],
        reason: str,
    ) -> AuditRecord:
        seq = len(self.records) + 1
        prev_hash = self.records[-1].record_hash if self.records else self.genesis_hash

        body = {
            "seq": seq,
            "run_id": self.run_id,
            "step_index": step_index,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "payload": payload,
            "balances_before": balances_before,
            "balances_after": balances_after,
            "reason": reason,
        }
        to_hash = prev_hash + canonical_json(body)
        record_hash = hashlib.sha256(to_hash.encode("utf-8")).hexdigest()

        rec = AuditRecord(
            seq=seq,
            run_id=self.run_id,
            step_index=step_index,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
            balances_before=balances_before,
            balances_after=balances_after,
            reason=reason,
            prev_hash=prev_hash,
            record_hash=record_hash,
        )
        self.records.append(rec)
        return rec

    def verify(self) -> Tuple[bool, int, Optional[str]]:
        """Verifies integrity of the hash chain. Returns (valid, checked_count, first_broken_seq)."""
        expected_prev = self.genesis_hash
        for i, rec in enumerate(self.records):
            if rec.prev_hash != expected_prev:
                return False, i, f"prev_hash mismatch at seq {rec.seq}"
            
            body = {
                "seq": rec.seq,
                "run_id": rec.run_id,
                "step_index": rec.step_index,
                "action": rec.action,
                "entity_type": rec.entity_type,
                "entity_id": rec.entity_id,
                "payload": rec.payload,
                "balances_before": rec.balances_before,
                "balances_after": rec.balances_after,
                "reason": rec.reason,
            }
            computed_hash = hashlib.sha256((expected_prev + canonical_json(body)).encode("utf-8")).hexdigest()
            if computed_hash != rec.record_hash:
                return False, i, f"record_hash mismatch at seq {rec.seq}"
            expected_prev = rec.record_hash

        return True, len(self.records), None
