"""A local fake of the Dydema EEG API for tests and the offline demo.

Speaks the documented routes, error shapes, idempotency rules and
X-Usage-Usd headers from https://developers.dydema.com/llms.txt, so the
whole create -> predict -> gate loop runs with no key and no money.
Predictions come from a deterministic stand-in classifier (RMS over C3/C4)
- it is not Wizard and makes no accuracy claim.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CHANNEL_INDEX = {"C3": 8, "C4": 10}
MODEL_PREFIX = "clf_"
VALID_UNITS = {"uV", "mV", "V"}
UNSUPPORTED_HINTS = ("emotion", "affect", "diagnos", "clinical")


class _State:
    def __init__(self):
        self.models: dict[str, dict] = {}
        self.idempotency: dict[str, tuple[str, int, dict, str]] = {}
        self.armed: list[tuple[int, str]] = []
        self.hits = 0
        self.total_usd = 0.0
        self.total_windows = 0
        self.create_usd = 0.0
        self.counter = 0


def _error(status, code, message, field=None, alternatives=None):
    return status, {"type": "error", "code": code, "message": message,
                    "field": field, "alternatives": alternatives,
                    "details": {"request_id": "req_fake"}}


class _Handler(BaseHTTPRequestHandler):
    state: _State

    def log_message(self, *args):  # keep test output clean
        pass

    # -- helpers ------------------------------------------------------
    def _send(self, status, payload, usage_usd=None):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if usage_usd is not None:
            self.send_header("X-Usage-Usd", f"{usage_usd:.3f}")
        self.end_headers()
        self.wfile.write(body)

    def _auth_error(self):
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer dk_live_"):
            return _error(401, "UNAUTHENTICATED", "No key, a malformed key, or one the API does not recognize.")
        key = header[len("Bearer "):]
        if key.startswith("dk_live_revoked"):
            return _error(401, "KEY_REVOKED", "The key was revoked.")
        return None

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode() or "{}")

    # -- routing ------------------------------------------------------
    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _dispatch(self, method):
        self.state.hits += 1
        if self.state.armed:
            status, code = self.state.armed.pop(0)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Retry-After", "0")
            payload = {"type": "error", "code": code, "message": f"armed {code}",
                       "field": None, "alternatives": None, "details": {"request_id": "req_fake"}}
            body = json.dumps(payload).encode()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        auth = self._auth_error()
        if auth:
            self._send(*auth)
            return
        path = self.path.split("?", 1)[0].rstrip("/")
        parts = [p for p in path.split("/") if p]
        try:
            if parts == ["v1", "usage"] and method == "GET":
                self._usage()
            elif parts == ["v1", "task-models"] and method == "POST":
                self._create()
            elif parts == ["v1", "task-models"] and method == "GET":
                self._list()
            elif len(parts) == 3 and parts[:2] == ["v1", "task-models"]:
                self._one_model(method, parts[2])
            elif len(parts) == 4 and parts[:2] == ["v1", "task-models"] and parts[3] == "predictions" and method == "POST":
                self._predict(parts[2])
            else:
                self._send(*_error(404, "NOT_FOUND", "Unknown path."))
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            self._send(*_error(422, "INVALID_REQUEST", f"bad request: {exc}"))

    # -- endpoints ----------------------------------------------------
    def _usage(self):
        month = None
        today = None
        if self.state.total_usd or self.state.total_windows:
            today = {"usd": f"{self.state.total_usd:.3f}", "windows": str(self.state.total_windows)}
            month = {"usd": f"{self.state.total_usd:.3f}", "windows": str(self.state.total_windows),
                     "task_model_create_usd": f"{self.state.create_usd:.2f}",
                     "task_model_hosting_usd": "0.00"}
        self._send(200, {"today": today, "month": month,
                         "limits": {"rps": 5, "burst": 10, "concurrency": 2}}, usage_usd=0.0)

    def _list(self):
        models = sorted(self.state.models.values(), key=lambda m: m["created"], reverse=True)
        self._send(200, {"object": "list", "data": models, "next_before": None}, usage_usd=0.0)

    def _one_model(self, method, model_id):
        model = self.state.models.get(model_id)
        if model is None or model["status"] in {"expired", "deleted"}:
            self._send(*_error(404, "CLASSIFIER_NOT_FOUND", "No such task model on this account."))
            return
        if method == "GET":
            self._send(200, model, usage_usd=0.0)
        elif method == "PATCH":
            body = self._read_json()
            for key in ("expires_at", "name"):
                if key in body:
                    model[key] = body[key]
            self._send(200, model, usage_usd=0.0)
        elif method == "DELETE":
            model["status"] = "deleted"
            self._send(200, {"id": model_id, "status": "deleted"}, usage_usd=0.0)
        else:
            self._send(*_error(404, "NOT_FOUND", "Unknown path."))

    def _create(self):
        body = self._read_json()
        units = body.get("units")
        mode = body.get("mode")
        if mode != "zero_shot" and units not in VALID_UNITS:
            self._send(*_error(422, "UNITS_REQUIRED", "units must be uV, mV or V", field="units"))
            return
        description = str(body.get("description") or "")
        if len(description) > 100:
            self._send(*_error(422, "INVALID_REQUEST", "description is at most 100 characters", field="description"))
            return
        if any(hint in description.lower() for hint in UNSUPPORTED_HINTS):
            self._send(*_error(422, "TASK_UNSUPPORTED", "This task is refused by model licence terms."))
            return
        labels = body.get("labels") or []
        if mode != "zero_shot":
            counts: dict[str, int] = {}
            for label in labels:
                counts[label] = counts.get(label, 0) + 1
            if len(counts) < 2 or min(counts.values(), default=0) < 5:
                self._send(*_error(422, "TOO_FEW_TRIALS", "At least 2 classes of at least 5 trials."))
                return
        if body.get("dry_run"):
            estimate = {"ready": True, "category": "motor_imagery" if mode != "zero_shot" else "resting_state",
                        "create_usd": "1.00", "hosting_usd_per_month": "1.00",
                        "warnings": ["Trial duration can affect accuracy."]}
            if mode == "zero_shot":
                estimate.update({
                    "mode": "zero_shot",
                    "classes": body.get("classes") or ["eyes_closed", "eyes_open"],
                    "explanation": "Eyes closed: rest with eyes closed. Eyes open: rest with eyes open.",
                    "reference_classes": {c: c for c in (body.get("classes") or ["eyes_closed", "eyes_open"])},
                    "evidence": {"reference_trials": 1200, "conditions": "internal evaluation"},
                })
            self._send(200, estimate, usage_usd=0.0)
            return
        # paid create: idempotency makes a retried create answer once, billed once
        idem = self.headers.get("Idempotency-Key")
        raw_body_hash = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        if idem and idem in self.state.idempotency:
            stored_hash, status, payload, usage = self.state.idempotency[idem]
            if stored_hash != raw_body_hash:
                self._send(*_error(422, "IDEMPOTENCY_KEY_REUSED", "A different body used this Idempotency-Key."))
                return
            self._send(status, payload, usage_usd=float(usage))
            return
        self.state.counter += 1
        digest = hashlib.sha256(f"{time.time_ns()}-{self.state.counter}".encode()).hexdigest()[:32]
        classes = sorted(set(labels)) if labels else (body.get("classes") or ["eyes_closed", "eyes_open"])
        model = {
            "id": MODEL_PREFIX + digest,
            "status": "active",
            "name": body.get("name"),
            "description": description,
            "created": int(time.time()),
            "expires_at": None,
            "training_report": {"validation_accuracy": 0.92,
                                "chance": round(1.0 / max(2, len(classes)), 4)},
        }
        if mode == "zero_shot":
            model["mode"] = "zero_shot"
        self.state.models[model["id"]] = model
        self.state.total_usd += 1.0
        self.state.create_usd += 1.0
        if idem:
            self.state.idempotency[idem] = (raw_body_hash, 201, model, "1.000")
        self._send(201, model, usage_usd=1.0)

    def _predict(self, model_id):
        model = self.state.models.get(model_id)
        if model is None or model["status"] != "active":
            self._send(*_error(404, "CLASSIFIER_NOT_FOUND", "Task model unavailable."))
            return
        body = self._read_json()
        shape = body.get("shape")
        x_b64 = body.get("x")
        if not shape or not x_b64:
            self._send(*_error(422, "INVALID_REQUEST", "predictions need x and shape"))
            return
        trials, channels, samples = shape
        raw = base64.b64decode(x_b64)
        values = struct.unpack(f"<{len(raw) // 4}f", raw)
        c3 = CHANNEL_INDEX["C3"] if channels > 10 else 0
        c4 = CHANNEL_INDEX["C4"] if channels > 10 else min(1, channels - 1)
        data = []
        for t in range(trials):
            base = t * channels * samples
            rms_c3 = _rms(values[base + c3 * samples: base + (c3 + 1) * samples])
            rms_c4 = _rms(values[base + c4 * samples: base + (c4 + 1) * samples])
            total = rms_c3 + rms_c4 or 1.0
            delta = (rms_c4 - rms_c3) / total
            p_left = min(0.95, 0.05 + 3.0 * max(0.0, delta))
            p_right = min(0.95, 0.05 + 3.0 * max(0.0, -delta))
            p_rest = max(0.0, 1.0 - p_left - p_right)
            probs = {"left": round(p_left, 4), "right": round(p_right, 4), "rest": round(p_rest, 4)}
            label = max(probs, key=probs.get)
            data.append({"object": "classification", "index": t, "label": label,
                         "probabilities": probs})
        windows = trials
        cost = 0.003 * windows
        self.state.total_usd += cost
        self.state.total_windows += windows
        self._send(200, {"object": "list", "data": data}, usage_usd=cost)


def _rms(values) -> float:
    if not values:
        return 0.0
    return math.sqrt(sum(v * v for v in values) / len(values))


class FakeGateway:
    """Context manager: a running fake API on a localhost ephemeral port."""

    def __init__(self):
        self.state = _State()
        handler = type("Handler", (_Handler,), {"state": self.state})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}/v1"

    def arm_error(self, status: int, code: str, times: int = 1) -> None:
        """Make the next `times` requests fail with this status/code (retry tests)."""
        self.state.armed.extend([(status, code)] * times)

    def __enter__(self) -> "FakeGateway":
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
