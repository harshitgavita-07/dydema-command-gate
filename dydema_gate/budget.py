"""Local spend guard. Default cap is $0.00: paid calls are refused locally.

Free calls (every GET, and any create with "dry_run": true) always pass.
Paid calls check the cap BEFORE leaving the machine, and the X-Usage-Usd
response header is recorded after each call so the running total is real,
not estimated.
"""
from __future__ import annotations

from decimal import Decimal

from .errors import SpendRefused

PAID_ROUTE_KINDS = {"create", "trials", "fit", "predictions"}


class Budget:
    def __init__(self, cap_usd: str | float | Decimal = "0.00"):
        self.cap_usd = Decimal(str(cap_usd))
        self.spent_usd = Decimal("0")
        self.ledger: list[dict] = []

    def allow_spend(self, cap_usd: str | float | Decimal) -> None:
        """Operator opt-in: raise the cap. The only way a paid call can run."""
        cap = Decimal(str(cap_usd))
        if cap < 0:
            raise ValueError("cap must be >= 0")
        self.cap_usd = cap

    def authorize(self, kind: str, route: str) -> None:
        if kind not in PAID_ROUTE_KINDS:
            return
        if self.spent_usd >= self.cap_usd:
            raise SpendRefused(
                f"blocked {route}: session spend ${self.spent_usd} has reached the "
                f"${self.cap_usd} cap (default $0.00). Pass --allow-spend USD to raise it."
            )

    def record(self, route: str, usage_header: str | None) -> Decimal:
        amount = Decimal("0")
        if usage_header:
            try:
                amount = Decimal(str(usage_header))
            except ArithmeticError:
                amount = Decimal("0")
        self.spent_usd += amount
        self.ledger.append({"route": route, "usd": str(amount)})
        return amount
