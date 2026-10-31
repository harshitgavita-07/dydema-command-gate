"""Clean-room bridge from NeuroComm-style cheap-EEG readings to gate inputs.

Inspired by Julian Weaver's NeuroComm (https://github.com/weavejul/NeuroComm):
a hacked MindFlex headset whose Arduino stream was decoded by the Brain
library into band strengths, and whose proof of concept answered yes/no
questions from concentration level. NeuroComm ships no license, so none of
its code is copied here; this module only re-implements the published idea
(concentration as a command channel, unconcentrated as rest) against the
documented Brain/NeuroSky output format, and credits the original.

The mapping below is a demo heuristic, not a validated EEG model. Its only
job is to turn one-stream cheap-EEG readings into the same {label,
probabilities} shape the Dydema API returns, so the command gate can prove
it abstains while a wearer is unconcentrated or the headset has poor contact.
"""
from __future__ import annotations

from typing import Any, Mapping

COMMAND_LABEL = "concentrate"
REST_LABEL = "rest"


def from_brain_reading(reading: Mapping[str, Any]) -> dict[str, Any]:
    """One Brain-library style reading -> a Dydema-shaped prediction.

    Expected keys (NeuroSky eSense + band strengths):
      signal_quality: 0 = good contact, 200 = no contact
      attention:      0-100 eSense attention
      meditation:     0-100 eSense meditation
    """
    try:
        quality = float(reading["signal_quality"])
        attention = float(reading["attention"])
        meditation = float(reading["meditation"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"reading needs signal_quality, attention, meditation: {exc}") from None
    for name, value in (("attention", attention), ("meditation", meditation)):
        if not 0.0 <= value <= 100.0:
            raise ValueError(f"{name} must be in 0-100, got {value}")
    if quality < 0 or quality > 200:
        raise ValueError(f"signal_quality must be in 0-200, got {quality}")

    if quality >= 100:  # poor contact: abstain hard
        p_command = 0.05
    else:
        contact = 1.0 - quality / 200.0
        evidence = attention / (attention + meditation) if (attention + meditation) > 0 else 0.5
        p_command = 0.05 + 0.9 * contact * evidence
    return {"probabilities": {COMMAND_LABEL: round(p_command, 6),
                              REST_LABEL: round(1.0 - p_command, 6)}}


def simulate_session(seed: int = 7) -> list[dict[str, Any]]:
    """A deterministic pretend session: rest, weak focus, strong focus, drift.

    Returns brain readings alternating unconcentrated and concentrated blocks,
    ending with a long unconcentrated stretch (where a bare classifier would
    still fire 'concentrate' sometimes; the gate must not).
    """
    import random
    rng = random.Random(seed)
    readings: list[dict[str, Any]] = []

    def block(n: int, attention: float, meditation: float, jitter: float, quality: float = 0.0):
        for _ in range(n):
            readings.append({
                "signal_quality": quality,
                "attention": min(100.0, max(0.0, attention + rng.uniform(-jitter, jitter))),
                "meditation": min(100.0, max(0.0, meditation + rng.uniform(-jitter, jitter))),
            })

    block(20, 30, 70, 10)          # at rest: attention low
    block(10, 55, 50, 12)          # weak focus: below the gate's bar
    block(12, 92, 15, 5)           # strong focus: should fire once
    block(25, 35, 65, 18)          # back to rest, noisy: must not fire
    block(6, 80, 20, 5, quality=200)  # headset off head: must not fire
    return readings
