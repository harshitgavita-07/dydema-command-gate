"""Synthetic EEG trials for demos and tests. NOT real EEG.

Mirrors the Dydema quickstart: trials of 4 s, 19 channels at 128 Hz, uV.
"left" trials carry a 10 Hz rhythm over C4, "right" trials over C3, on top
of noise. "rest" trials are noise only. Pure stdlib so the whole repo runs
with no packages.
"""
from __future__ import annotations

import base64
import math
import random
import struct

CHANNELS = ["Fp1", "Fp2", "F7", "F3", "Fz", "F4", "F8", "T7", "C3", "Cz",
            "C4", "T8", "P7", "P3", "Pz", "P4", "P8", "O1", "O2"]
RATE_HZ = 128
TRIAL_SECONDS = 4
SAMPLES = RATE_HZ * TRIAL_SECONDS

MOTOR_DESCRIPTION = ("Motor imagery: after a cue, imagine squeezing the left "
                     "or the right hand. Labels: left, right.")
ZERO_SHOT_DESCRIPTION = ("Resting state: eyes closed (resting) versus eyes "
                         "open (resting).")


def build_trials(labels: list[str], seed: int = 40) -> tuple[str, list[int]]:
    """Return (base64 little-endian float32, shape) for the given labels."""
    rng = random.Random(seed)
    t = [s / RATE_HZ for s in range(SAMPLES)]
    data: list[float] = []
    for label in labels:
        for channel in CHANNELS:
            rhythm = 0.0
            if label == "left" and channel == "C4":
                rhythm = 20.0
            elif label == "right" and channel == "C3":
                rhythm = 20.0
            for i in range(SAMPLES):
                noise = 10.0 * rng.gauss(0.0, 1.0)
                data.append(noise + rhythm * math.sin(2 * math.pi * 10 * t[i]))
    flat = struct.pack(f"<{len(data)}f", *data)  # little-endian float32
    shape = [len(labels), len(CHANNELS), SAMPLES]
    return base64.b64encode(flat).decode("ascii"), shape


def training_payload(labels: list[str] | None = None, name: str = "hand imagery (command-gate)",
                     expires_in_days: int | None = 1) -> dict:
    labels = labels or ["left", "right"] * 12
    x_b64, shape = build_trials(labels)
    payload = {
        "x": x_b64,
        "shape": shape,
        "sampling_rate_hz": RATE_HZ,
        "units": "uV",
        "channels": CHANNELS,
        "labels": labels,
        "description": MOTOR_DESCRIPTION,
        "name": name,
    }
    if expires_in_days is not None:
        payload["expires_in_days"] = expires_in_days
    return payload


def prediction_payload(labels: list[str]) -> dict:
    """Unlabeled prediction request (truth labels kept by the caller)."""
    x_b64, shape = build_trials(labels, seed=len(labels) * 7 + 1)
    return {
        "x": x_b64,
        "shape": shape,
        "sampling_rate_hz": RATE_HZ,
        "units": "uV",
        "channels": CHANNELS,
    }


def zero_shot_estimate_payload() -> dict:
    return {
        "mode": "zero_shot",
        "description": ZERO_SHOT_DESCRIPTION,
        "classes": ["eyes_closed", "eyes_open"],
        "channels": CHANNELS,
        "sampling_rate_hz": RATE_HZ,
        "trial_seconds": TRIAL_SECONDS,
    }
