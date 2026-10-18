"""Cryptographically chained immutable audit logger."""

import hashlib
import json
from dataclasses import asdict
from typing import List, Optional

from reserve_juggler.models import AuditRecord


class AuditLogger:
    GENESIS_HASH = "0000000000000000000000000000000000000000000000000000000000000000"

    def __init__(self, log_file_path: Optional[str] = None) -> None:
        self.log_file_path = log_file_path
        self.chain: List[AuditRecord] = []
        self._last_hash = self.GENESIS_HASH

    def _compute_hash(
        self,
        prev_hash: str,
        cycle_index: int,
        timestamp: str,
        cash_before_cents: int,
        vault_before_cents: int,
        forecast_p999_max_deficit_cents: int,
        required_cushion_cents: int,
        headroom_cents: int,
        decision: str,
        sweep_amount_cents: int,
        reason: str,
    ) -> str:
        payload = (
            f"{prev_hash}|{cycle_index}|{timestamp}|{cash_before_cents}|{vault_before_cents}|"
            f"{forecast_p999_max_deficit_cents}|{required_cushion_cents}|{headroom_cents}|"
            f"{decision}|{sweep_amount_cents}|{reason}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def record(
        self,
        cycle_index: int,
        timestamp: str,
        cash_before_cents: int,
        vault_before_cents: int,
        forecast_p999_max_deficit_cents: int,
        required_cushion_cents: int,
        headroom_cents: int,
        decision: str,
        sweep_amount_cents: int,
        reason: str,
    ) -> AuditRecord:
        record_hash = self._compute_hash(
            prev_hash=self._last_hash,
            cycle_index=cycle_index,
            timestamp=timestamp,
            cash_before_cents=cash_before_cents,
            vault_before_cents=vault_before_cents,
            forecast_p999_max_deficit_cents=forecast_p999_max_deficit_cents,
            required_cushion_cents=required_cushion_cents,
            headroom_cents=headroom_cents,
            decision=decision,
            sweep_amount_cents=sweep_amount_cents,
            reason=reason,
        )

        record = AuditRecord(
            cycle_index=cycle_index,
            timestamp=timestamp,
            cash_before_cents=cash_before_cents,
            vault_before_cents=vault_before_cents,
            forecast_p999_max_deficit_cents=forecast_p999_max_deficit_cents,
            required_cushion_cents=required_cushion_cents,
            headroom_cents=headroom_cents,
            decision=decision,
            sweep_amount_cents=sweep_amount_cents,
            reason=reason,
            prev_hash=self._last_hash,
            record_hash=record_hash,
        )

        self.chain.append(record)
        self._last_hash = record_hash

        if self.log_file_path:
            with open(self.log_file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(record)) + "\n")

        return record

    def verify_chain_integrity(self) -> bool:
        """Verify the full hash chain to detect tampering or record loss."""
        expected_prev = self.GENESIS_HASH
        for rec in self.chain:
            if rec.prev_hash != expected_prev:
                return False
            recomputed = self._compute_hash(
                prev_hash=rec.prev_hash,
                cycle_index=rec.cycle_index,
                timestamp=rec.timestamp,
                cash_before_cents=rec.cash_before_cents,
                vault_before_cents=rec.vault_before_cents,
                forecast_p999_max_deficit_cents=rec.forecast_p999_max_deficit_cents,
                required_cushion_cents=rec.required_cushion_cents,
                headroom_cents=rec.headroom_cents,
                decision=rec.decision,
                sweep_amount_cents=rec.sweep_amount_cents,
                reason=rec.reason,
            )
            if recomputed != rec.record_hash:
                return False
            expected_prev = rec.record_hash
        return True

    def get_recent(self, count: int = 50) -> List[AuditRecord]:
        return self.chain[-count:]
