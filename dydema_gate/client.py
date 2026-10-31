"""Zero-dependency client for the Dydema EEG API (Wizard).

Implements only the documented public routes:
  POST   /v1/task-models            (dry_run estimate or paid create)
  POST   /v1/task-models/{id}/trials, /fit   (batched create path)
  POST   /v1/task-models/{id}/predictions    (paid per window)
  GET    /v1/task-models, /v1/task-models/{id}
  PATCH  /v1/task-models/{id}
  DELETE /v1/task-models/{id}
  GET    /v1/usage
Source: https://developers.dydema.com/llms.txt (exact reference).

Auth: `Authorization: Bearer $DYDEMA_API_KEY` on every request.
Retries: POSTs carry an Idempotency-Key (uuid4), reused verbatim across
retries; 409, 5xx, and 429 RATE_LIMITED/CONCURRENCY_LIMITED are retried
after Retry-After or exponential backoff (1s, 2s, 4s...), max 5 attempts.
Every other 4xx raises immediately. Connection/timeout errors retry too.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

from .budget import Budget
from .errors import DydemaError

DEFAULT_BASE_URL = "https://dydema--eegapi-gateway.modal.run/v1"
MAX_ATTEMPTS = 5


class DydemaClient:
    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL,
                 budget: Budget | None = None, timeout: float = 120.0,
                 sleep=time.sleep):
        if not api_key:
            raise ValueError("api_key is required (set DYDEMA_API_KEY)")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.budget = budget or Budget()
        self.timeout = timeout
        self.sleep = sleep
        self.request_count = 0

    # ---- low level -------------------------------------------------
    def _request(self, method: str, path: str, body: dict | None,
                 cost_kind: str, idempotent: bool) -> tuple[Any, str | None]:
        route = f"{method} {path}"
        self.budget.authorize(cost_kind, route)
        url = self.base_url + path
        idem_key = uuid.uuid4().hex if idempotent else None
        encoded = json.dumps(body).encode() if body is not None else None
        attempt = 0
        while True:
            attempt += 1
            headers = {"Authorization": f"Bearer {self.api_key}"}
            if encoded is not None:
                headers["Content-Type"] = "application/json"
            if idem_key:
                headers["Idempotency-Key"] = idem_key
            request = urllib.request.Request(url, data=encoded, headers=headers, method=method)
            self.request_count += 1
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    usage = response.headers.get("X-Usage-Usd")
                    self.budget.record(route, usage)
                    payload = json.loads(response.read().decode() or "null")
                    return payload, usage
            except urllib.error.HTTPError as exc:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                usage = exc.headers.get("X-Usage-Usd") if exc.headers else None
                if usage:
                    self.budget.record(route, usage)
                try:
                    payload = json.loads(exc.read().decode() or "{}")
                except json.JSONDecodeError:
                    payload = {}
                error = DydemaError.from_response(exc.code, payload, retry_after=retry_after)
                if error.retryable and attempt < MAX_ATTEMPTS:
                    self.sleep(self._wait_seconds(retry_after, attempt))
                    continue
                raise error from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt < MAX_ATTEMPTS:
                    self.sleep(self._wait_seconds(None, attempt))
                    continue
                raise DydemaError(0, "TRANSPORT", f"request failed after {attempt} attempts: {exc}") from None

    @staticmethod
    def _wait_seconds(retry_after: str | None, attempt: int) -> float:
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                pass
        return float(2 ** (attempt - 1))

    # ---- task models -----------------------------------------------
    def estimate(self, payload: dict) -> dict:
        """Free dry run: reports category, create_usd, hosting and warnings."""
        body = dict(payload, dry_run=True)
        result, _ = self._request("POST", "/task-models", body, "free", idempotent=True)
        return result

    def create_task_model(self, payload: dict) -> dict:
        """PAID create ($1.00 one-time fee + hosting). Needs budget headroom."""
        result, _ = self._request("POST", "/task-models", body=payload,
                                  cost_kind="create", idempotent=True)
        return result

    def predict(self, model_id: str, payload: dict) -> dict:
        """PAID predictions ($0.003 per window)."""
        result, _ = self._request("POST", f"/task-models/{model_id}/predictions",
                                  body=payload, cost_kind="predictions", idempotent=True)
        return result

    def add_trials(self, model_id: str, payload: dict) -> dict:
        result, _ = self._request("POST", f"/task-models/{model_id}/trials",
                                  body=payload, cost_kind="trials", idempotent=True)
        return result

    def fit(self, model_id: str) -> dict:
        result, _ = self._request("POST", f"/task-models/{model_id}/fit",
                                  body={}, cost_kind="fit", idempotent=True)
        return result

    def list_task_models(self, limit: int = 100) -> dict:
        result, _ = self._request("GET", f"/task-models?limit={int(limit)}", None, "free", False)
        return result

    def get_task_model(self, model_id: str) -> dict:
        result, _ = self._request("GET", f"/task-models/{model_id}", None, "free", False)
        return result

    def patch_task_model(self, model_id: str, **fields) -> dict:
        result, _ = self._request("PATCH", f"/task-models/{model_id}", fields, "free", False)
        return result

    def delete_task_model(self, model_id: str) -> dict:
        result, _ = self._request("DELETE", f"/task-models/{model_id}", None, "free", False)
        return result

    def usage(self) -> dict:
        result, _ = self._request("GET", "/usage", None, "free", False)
        return result
