from __future__ import annotations
import math
from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel, Field
from backend.app.settlement.repo import RepoPosition


class PayoutItem(BaseModel):
    queue_id: str
    step_enqueued: int
    amount_cents: int
    amount_paid_cents: int = 0

    @property
    def remaining_cents(self) -> int:
        return self.amount_cents - self.amount_paid_cents


class PayoutQueue:
    def __init__(self):
        self.items: List[PayoutItem] = []

    @property
    def total_outstanding_cents(self) -> int:
        return sum(item.remaining_cents for item in self.items)

    def enqueue(self, queue_id: str, step_index: int, amount_cents: int) -> None:
        self.items.append(PayoutItem(queue_id=queue_id, step_enqueued=step_index, amount_cents=amount_cents))

    def pay_fifo(self, available_cash_cents: int) -> Tuple[int, List[Tuple[str, int]]]:
        """Pays queued payouts FIFO. Returns (cash_used_cents, list of (queue_id, paid_cents))."""
        cash_left = available_cash_cents
        payments = []
        for item in self.items:
            if cash_left <= 0:
                break
            rem = item.remaining_cents
            if rem > 0:
                to_pay = min(cash_left, rem)
                item.amount_paid_cents += to_pay
                cash_left -= to_pay
                payments.append((item.queue_id, to_pay))
        
        # Clean up fully paid items
        self.items = [item for item in self.items if item.remaining_cents > 0]
        used_cash = available_cash_cents - cash_left
        return used_cash, payments
