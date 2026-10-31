"""Command line: simulate (offline), estimate/usage/list (live, free),
demo (live, paid - locked behind --allow-spend).

    python -m dydema_gate.cli simulate
    python -m dydema_gate.cli estimate
    python -m dydema_gate.cli usage
    python -m dydema_gate.cli list
    python -m dydema_gate.cli demo --allow-spend 2.00
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .audit import AuditLog
from .budget import Budget
from .client import DydemaClient
from .dotenv import load_env
from .errors import DydemaError, SpendRefused
from .fake_gateway import FakeGateway
from .gate import GateConfig, IdleGate
from . import calibrate, neurocomm, synthetic

WINDOW_MS = 250


def _live_client(budget: Budget) -> DydemaClient:
    load_env()
    key = os.environ.get("DYDEMA_API_KEY", "")
    if not key:
        raise SystemExit("DYDEMA_API_KEY is not set. Copy .env.example to .env and paste your key.")
    return DydemaClient(key, budget=budget)


def _run_gate_stream(client: DydemaClient, model_id: str, truth: list[str],
                     audit: AuditLog, budget: Budget) -> dict:
    gate = IdleGate(GateConfig())
    fired: list[dict] = []
    false_activations = 0
    for i, label in enumerate(truth):
        payload = synthetic.prediction_payload([label])
        response = client.predict(model_id, payload)
        prediction = response["data"][0]
        decision = gate.update(prediction, now_ms=i * WINDOW_MS)
        audit.append({"time_ms": i * WINDOW_MS, "truth": label,
                      "label": prediction["label"], "state": decision.state,
                      "fired": decision.fired, "command": decision.command,
                      "probability": decision.probability, "drift": decision.drift,
                      "usage_usd": budget.ledger[-1]["usd"] if budget.ledger else "0"})
        if decision.fired:
            fired.append({"window": i, "command": decision.command, "truth": label})
            if label == "rest":
                false_activations += 1
    return {"windows": len(truth), "fired": fired,
            "false_activations": false_activations,
            "audit": audit.summary()}


def cmd_simulate(_args) -> int:
    """Full loop against the built-in fake gateway. No key, no money."""
    print("SIMULATED run: local fake gateway, no real API calls, no real money.\n")
    budget = Budget()  # $0.00 default
    with FakeGateway() as gateway:
        client = DydemaClient("dk_live_simulated", base_url=gateway.base_url,
                              budget=budget, sleep=lambda s: None)

        print("1. Free dry-run estimate (labeled motor-imagery trials):")
        estimate = client.estimate(synthetic.training_payload())
        print("  ", json.dumps(estimate, indent=2)[:400], "\n")

        print("2. Create with the default $0.00 cap:")
        try:
            client.create_task_model(synthetic.training_payload())
            print("   UNEXPECTED: create went through without a budget")
            return 1
        except SpendRefused as exc:
            print(f"   locked, as designed: {exc}\n")

        print("3. Operator raises the cap to $2.00 (simulated money) and creates:")
        budget.allow_spend("2.00")
        model = client.create_task_model(synthetic.training_payload())
        print(f"   model {model['id']} status={model['status']} "
              f"training_report={json.dumps(model['training_report'])}\n")

        print("4. Streaming windows through the command gate:")
        truth = (["rest"] * 8 + ["left"] * 6 + ["rest"] * 4
                 + ["right"] * 6 + ["rest"] * 10 + ["right"] * 24)
        audit = AuditLog()
        result = _run_gate_stream(client, model["id"], truth, audit, budget)
        print(f"   windows={result['windows']} fired={len(result['fired'])} "
              f"false_activations={result['false_activations']}")
        print(f"   fired commands: {result['fired']}")
        print(f"   gate states: {result['audit']['states']}")
        print(f"   audit chain valid: {result['audit']['chain_valid']} "
              f"(head {result['audit']['head'][:16]}...)\n")

        print("5. NeuroComm bridge (cheap-EEG concentration stream, Julian Weaver's paradigm):")
        neuro_gate = IdleGate(GateConfig())
        neuro_fires = 0
        rest_fires = 0
        for i, reading in enumerate(neurocomm.simulate_session()):
            prediction = neurocomm.from_brain_reading(reading)
            decision = neuro_gate.update(prediction, now_ms=i * WINDOW_MS)
            if decision.fired:
                neuro_fires += 1
                if reading["attention"] < 60 or reading["signal_quality"] >= 100:
                    rest_fires += 1
        print(f"   readings={i + 1} fired={neuro_fires} "
              f"fired_while_unfocused_or_poor_contact={rest_fires}\n")

        print("6. Usage and cleanup:")
        print("  ", json.dumps(client.usage()))
        client.delete_task_model(model["id"])
        print(f"   model deleted. total simulated spend: ${budget.spent_usd}")
    return 0


def cmd_calibrate(args) -> int:
    """Offline grid sweep: pick gate settings for a false-activation target."""
    results = calibrate.sweep(target_false_per_minute=args.target)
    best = calibrate.pick(results, target_false_per_minute=args.target)
    print(f"scenario: {results[0].windows} deterministic windows "
          f"(rest, weak, sustained, oscillating, runaway)")
    print(f"target: <= {args.target} false activations/minute\n")
    for r in sorted(results, key=lambda r: (r.false_activations_per_minute,
                                            r.mean_fire_latency_ms or 1e9))[:8]:
        c = r.config
        latency = f"{r.mean_fire_latency_ms:.0f} ms" if r.mean_fire_latency_ms is not None else "never fires"
        print(f"  enter={c.enter_probability:.2f} margin={c.min_margin:.2f} dwell={c.dwell_windows}  "
              f"false/min={r.false_activations_per_minute:.3f} latency={latency} "
              f"fired={r.fired} missed={r.missed_commands} blocked={r.blocked_windows}")
    if best is None:
        print("\nNo config met the target without missing commands.")
        return 1
    c = best.config
    print(f"\npicked: enter={c.enter_probability:.2f} margin={c.min_margin:.2f} "
          f"dwell={c.dwell_windows} -> {best.false_activations_per_minute:.3f} false/min, "
          f"{best.mean_fire_latency_ms:.0f} ms mean latency")
    return 0


def cmd_estimate(_args) -> int:
    """Live FREE dry runs only. Nothing is fitted or charged."""
    client = _live_client(Budget())  # $0.00 cap; estimates are free
    print("Dry run 1 - labeled motor imagery (synthetic trials, NOT real EEG):")
    print(json.dumps(client.estimate(synthetic.training_payload()), indent=2))
    print("\nDry run 2 - zero-shot resting state (eyes closed vs eyes open):")
    print(json.dumps(client.estimate(synthetic.zero_shot_estimate_payload()), indent=2))
    print(f"\nSession spend: ${client.budget.spent_usd} (estimates are free)")
    return 0


def cmd_usage(_args) -> int:
    client = _live_client(Budget())
    print(json.dumps(client.usage(), indent=2))
    return 0


def cmd_list(_args) -> int:
    client = _live_client(Budget())
    print(json.dumps(client.list_task_models(), indent=2))
    return 0


def cmd_demo(args) -> int:
    """Live PAID loop. Refuses to run without an explicit --allow-spend."""
    if args.allow_spend <= 0:
        raise SystemExit("demo spends real credit ($1.00 create + $0.003/window). "
                         "Re-run with --allow-spend USD (e.g. --allow-spend 2.00) to confirm.")
    budget = Budget()
    budget.allow_spend(str(args.allow_spend))
    client = _live_client(budget)
    print("Free dry run first:")
    print(json.dumps(client.estimate(synthetic.training_payload()), indent=2))
    model = client.create_task_model(synthetic.training_payload())
    print(f"\nmodel {model['id']} status={model['status']}")
    print(f"training_report={json.dumps(model['training_report'])}")
    truth = ["rest"] * 6 + ["left"] * 6 + ["rest"] * 6 + ["right"] * 6 + ["rest"] * 6
    audit = AuditLog()
    result = _run_gate_stream(client, model["id"], truth, audit, budget)
    print(f"\nwindows={result['windows']} fired={len(result['fired'])} "
          f"false_activations={result['false_activations']}")
    print(f"fired commands: {result['fired']}")
    print(f"audit chain valid: {result['audit']['chain_valid']}")
    client.delete_task_model(model["id"])
    print(f"\nmodel deleted. total spend this run: ${budget.spent_usd}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dydema_gate")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("simulate", help="offline full loop vs the fake gateway (no key, no money)")
    cal = sub.add_parser("calibrate", help="offline gate-config sweep vs a false-activation target")
    cal.add_argument("--target", type=float, default=0.2, help="max false activations per minute")
    sub.add_parser("estimate", help="live FREE dry-run estimates only")
    sub.add_parser("usage", help="live free usage read")
    sub.add_parser("list", help="live free task-model list")
    demo = sub.add_parser("demo", help="live PAID loop (needs --allow-spend)")
    demo.add_argument("--allow-spend", type=float, default=0.0,
                      help="USD cap for this run; 0 (default) refuses to run")
    args = parser.parse_args(argv)
    handlers = {"simulate": cmd_simulate, "calibrate": cmd_calibrate, "estimate": cmd_estimate,
                "usage": cmd_usage, "list": cmd_list, "demo": cmd_demo}
    try:
        return handlers[args.command](args)
    except DydemaError as exc:
        print(f"API error: {exc}", file=sys.stderr)
        if exc.alternatives:
            print(f"how to fix: {exc.alternatives}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
