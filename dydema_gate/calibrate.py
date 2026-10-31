"""Offline calibration: pick gate settings that hit a false-activation target.

Replays deterministic prediction scenarios (rest, weak evidence, sustained
commands, oscillation, runaway) through the gate for a grid of configs and
reports, per config: false activations per minute, mean fire latency, missed
commands and blocked windows. `pick` returns the fastest config that meets
the target false-activation rate. Pure offline; no API, no money.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from .gate import GateConfig, IdleGate

WINDOW_MS = 250


@dataclass(frozen=True)
class ScenarioResult:
    config: GateConfig
    false_activations_per_minute: float
    mean_fire_latency_ms: float | None
    fired: int
    missed_commands: int
    blocked_windows: int
    windows: int


def _normalized(probs: dict) -> dict:
    probs = {k: max(0.02, v) for k, v in probs.items()}
    total = sum(probs.values())
    return {"probabilities": {k: v / total for k, v in probs.items()}}


def _strong(label: str, rng: random.Random) -> dict:
    p = 0.85 + rng.uniform(-0.04, 0.04)
    rest = 0.10 + rng.uniform(-0.04, 0.04)
    other = max(0.02, 1.0 - p - rest)
    probs = {"left": other, "right": other, "rest": rest}
    probs[label] = p
    return _normalized(probs)


def _weak(label: str, rng: random.Random) -> dict:
    p = 0.62 + rng.uniform(-0.06, 0.06)
    rest = max(0.02, 1.0 - p - 0.15)
    probs = {"left": 0.15, "right": 0.15, "rest": rest}
    probs[label] = p
    return _normalized(probs)


def _rest(rng: random.Random) -> dict:
    rest = 0.78 + rng.uniform(-0.06, 0.06)
    share = (1.0 - rest) / 2
    return {"probabilities": {"left": share, "right": share, "rest": rest}}


def build_stream(seed: int = 11) -> list[dict]:
    """One deterministic scenario stream with truth labels per window."""
    rng = random.Random(seed)
    stream: list[dict] = []

    def add(n, truth, maker):
        for _ in range(n):
            stream.append({"truth": truth, "prediction": maker(rng)})

    add(24, "rest", _rest)                       # long rest: any fire is false
    add(6, "left", lambda r: _weak("left", r))   # weak evidence: must not fire
    add(8, "left", lambda r: _strong("left", r)) # sustained: should fire once
    add(16, "rest", _rest)
    for i in range(6):  # oscillation: alternating strong labels must never fire
        label = "left" if i % 2 == 0 else "right"
        stream.append({"truth": "alternate", "prediction": _strong(label, rng)})
    add(8, "right", lambda r: _strong("right", r))
    add(20, "rest", _rest)
    add(30, "right", lambda r: _strong("right", r))  # runaway: one fire, then suppression
    add(20, "rest", _rest)
    return stream


def run_scenario(stream: list[dict], config: GateConfig) -> ScenarioResult:
    gate = IdleGate(config)
    false_fires = 0
    fired = 0
    latencies: list[int] = []
    blocked = 0
    # command-block onset tracking for latency and misses
    onset: dict[str, int] = {}
    prev_truth: str | None = None
    for i, row in enumerate(stream):
        truth = row["truth"]
        if truth in ("left", "right") and truth != prev_truth:
            onset[truth] = i
        prev_truth = truth
        decision = gate.update(row["prediction"], now_ms=i * WINDOW_MS)
        if decision.state == "blocked_drift":
            blocked += 1
        if decision.fired:
            fired += 1
            if truth in ("left", "right") and decision.command == truth:
                latencies.append((i - onset.get(truth, i)) * WINDOW_MS)
            else:
                false_fires += 1
    minutes = len(stream) * WINDOW_MS / 60000.0
    # a sustained block that never fired counts as missed (weak/oscillating blocks SHOULD miss)
    sustained_blocks = [("left", 8), ("right", 8), ("right", 30)]
    expected_fires = len(sustained_blocks)
    missed = max(0, expected_fires - len(latencies))
    return ScenarioResult(
        config=config,
        false_activations_per_minute=false_fires / minutes if minutes else 0.0,
        mean_fire_latency_ms=(sum(latencies) / len(latencies)) if latencies else None,
        fired=fired,
        missed_commands=missed,
        blocked_windows=blocked,
        windows=len(stream),
    )


def sweep(target_false_per_minute: float = 0.2, seed: int = 11) -> list[ScenarioResult]:
    stream = build_stream(seed)
    results: list[ScenarioResult] = []
    for enter in (0.75, 0.80, 0.85, 0.90):
        for margin in (0.15, 0.25, 0.35):
            for dwell in (2, 3, 4):
                config = GateConfig(enter_probability=enter, min_margin=margin,
                                    dwell_windows=dwell)
                results.append(run_scenario(stream, config))
    return results


def pick(results: list[ScenarioResult], target_false_per_minute: float = 0.2) -> ScenarioResult | None:
    """Fastest config meeting the false-activation target; None if none do."""
    eligible = [r for r in results
                if r.false_activations_per_minute <= target_false_per_minute
                and r.mean_fire_latency_ms is not None and r.missed_commands == 0]
    if not eligible:
        return None
    return min(eligible, key=lambda r: (r.mean_fire_latency_ms or 1e9,
                                        r.config.dwell_windows,
                                        -r.config.enter_probability))
