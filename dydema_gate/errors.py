"""Error taxonomy for the Dydema EEG API.

Every documented error shares one JSON shape:
{"type", "code", "message", "field", "alternatives", "details"}.
Switch on `code`; show `message` and `alternatives` to the user.
Source: https://developers.dydema.com/docs (Errors & limits).
"""
from __future__ import annotations

# Codes worth retrying (short-term): plus HTTP 409 and 5xx statuses.
RETRYABLE_CODES = {"RATE_LIMITED", "CONCURRENCY_LIMITED"}
RETRYABLE_STATUSES = {409, 500, 502, 503}
# Codes a person or time must fix: never retry unchanged.
PERSON_ACTION_CODES = {
    "INSUFFICIENT_CREDIT", "BUDGET_EXCEEDED", "USAGE_CAP_EXCEEDED",
    "UNAUTHENTICATED", "KEY_REVOKED", "KEY_EXPIRED", "SCOPE_MISSING",
    "TENANT_SUSPENDED", "IP_NOT_ALLOWED",
}


class DydemaError(Exception):
    """One API error, carrying the documented fields."""

    def __init__(self, status, code, message, alternatives=None, field=None,
                 request_id=None, retry_after=None):
        self.status = status
        self.code = code or "UNKNOWN"
        self.message = message or ""
        self.alternatives = alternatives
        self.field = field
        self.request_id = request_id
        self.retry_after = retry_after
        super().__init__(f"{status} {self.code}: {self.message}")

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE_CODES or self.status in RETRYABLE_STATUSES

    @classmethod
    def from_response(cls, status, payload, retry_after=None):
        payload = payload if isinstance(payload, dict) else {}
        details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
        return cls(
            status=status,
            code=payload.get("code"),
            message=payload.get("message"),
            alternatives=payload.get("alternatives"),
            field=payload.get("field"),
            request_id=details.get("request_id"),
            retry_after=retry_after,
        )


class SpendRefused(Exception):
    """The local budget guard blocked a paid call before it left the machine.

    This is the default posture: the cap starts at $0.00, so nothing that costs
    money can run until the operator explicitly raises it.
    """
