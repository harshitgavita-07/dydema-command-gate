"""SHA-256 hash-chained audit log for gate decisions and API costs.

Every entry chains to the previous hash, so a tampered or reordered log
fails verify(). Decisions that never fired an action are still recorded:
the point of the layer is proving what was *not* done, and why.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

GENESIS = "0" * 64


class AuditLog:
    def __init__(self):
        self.last_hash = GENESIS
        self.entries: list[dict] = []

    def append(self, item: Mapping[str, Any]) -> str:
        body = dict(item)
        body["previous"] = self.last_hash
        encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        self.last_hash = hashlib.sha256(encoded).hexdigest()
        entry = dict(body)
        entry["hash"] = self.last_hash
        self.entries.append(entry)
        return self.last_hash

    def verify(self) -> bool:
        previous = GENESIS
        for entry in self.entries:
            body = {k: v for k, v in entry.items() if k != "hash"}
            if body.get("previous") != previous:
                return False
            encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
            digest = hashlib.sha256(encoded).hexdigest()
            if digest != entry["hash"]:
                return False
            previous = digest
        return True

    def summary(self) -> dict:
        states: dict[str, int] = {}
        fired = 0
        for entry in self.entries:
            state = str(entry.get("state", "unknown"))
            states[state] = states.get(state, 0) + 1
            if entry.get("fired"):
                fired += 1
        return {"entries": len(self.entries), "fired": fired, "states": states,
                "chain_valid": self.verify(), "head": self.last_hash}
