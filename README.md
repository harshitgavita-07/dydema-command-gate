# Dydema Command Gate

A live trust layer between [Dydema's Wizard EEG API](https://developers.dydema.com/docs) and real-world commands - plus a spend guard that defaults to **$0.00**, so the tool cannot spend your money unless you explicitly let it.

Dydema's own docs are careful about the boundary: the API returns a label and class probabilities for every window, and the hosted model never decides when *not* to act. This repo is the missing application-side policy, wired to the real API: predictions stream through a command gate (confidence threshold, winner margin, dwell, refractory, rest re-arm, drift blocking) before anything is allowed to fire, and every decision lands in a SHA-256 hash-chained audit log next to what the call cost.

It is a prototype, not a claim that Wizard is inaccurate, not a medical or clinical tool, and not an official Dydema integration. Companion to [dydema-idle-gate](https://github.com/harshitgavita-07/dydema-idle-gate), which proved the gate policy offline; this repo takes it live.

## The $0.00 posture

- Every `GET` and every `dry_run` estimate is free, always allowed.
- Anything that costs money (create, trials, fit, predictions) is refused **locally, before it leaves the machine**, until you run with `--allow-spend USD`.
- Every response's `X-Usage-Usd` header is recorded, so the running total is real, not estimated.

```
2. Create with the default $0.00 cap:
   locked, as designed: blocked POST /task-models: session spend $0.000 has reached
   the $0.00 cap (default $0.00). Pass --allow-spend USD to raise it.
```

## What it does

- **Zero-dependency API client** for the whole documented public surface (`/v1/task-models` + sub-routes, `/v1/usage`), with `Idempotency-Key` retries exactly per the docs: 409/5xx and 429 `RATE_LIMITED`/`CONCURRENCY_LIMITED` retry after `Retry-After` or exponential backoff (max 5 attempts); every other 4xx raises immediately with the documented `code`, `message` and `alternatives`.
- **Free live mode**: `estimate` runs real dry runs against the live API - labeled motor imagery and the zero-shot resting task (eyes closed vs eyes open) - plus `usage` and `list`. Nothing is fitted or charged.
- **Offline simulate mode**: a built-in fake gateway speaks the exact documented routes, error shapes, idempotency rules and usage headers, so the full create → predict → gate → audit loop runs with no key and no money.
- **Command gate**: sustained-evidence firing, abstention on rest/idle/neutral, refractory latch against repeated commands, Jensen-Shannon drift blocking, and a tamper-evident audit chain that records what was *not* done and why.
- **NeuroComm bridge**: an adapter for cheap-EEG concentration streams in the style of Julian Weaver's [NeuroComm](https://github.com/weavejul/NeuroComm) (hacked MindFlex → band strengths → yes/no by concentration). NeuroComm ships no license, so none of its code is copied; this is a clean-room implementation of the published idea, credited, mapping eSense attention/meditation/signal-quality readings to the same prediction shape the gate consumes. Poor headset contact forces abstention.

## Quickstart

```sh
python -m unittest discover -s tests -v   # 38 tests, no key needed
python -m dydema_gate.cli simulate        # full loop vs the fake gateway, no money
```

Live free estimates (needs a key):

```sh
cp .env.example .env   # paste your dk_live_ key; .env is gitignored
python -m dydema_gate.cli estimate
python -m dydema_gate.cli usage
```

Live paid loop (real credit: $1.00 create + $0.003/window, model deleted at the end):

```sh
python -m dydema_gate.cli demo --allow-spend 2.00
```

## Simulated run (latest)

- 58 prediction windows: 3 correct fired commands (left, right, right), **0 false activations**
- A 24-window runaway right-command stream fired once, then the refractory latch suppressed the rest
- NeuroComm session (73 readings: rest → weak focus → strong focus → noisy rest → headset off): fired once, during the strong-focus block only
- Audit chain valid; simulated spend $1.174 tracked from `X-Usage-Usd`

## Why the gate is needed

Wizard is a model API: it classifies whatever window you send, including windows where the wearer is at rest, distracted, or the headset slipped. Any app that turns every returned class into a keypress, device command or agent tool call will eventually act on garbage. The gate's job is the other half of the interface - knowing when not to act - and the audit log's job is proving it afterward.

## Layout

```
dydema_gate/
  client.py        zero-dependency Wizard API client (idempotent retries, error taxonomy)
  budget.py        spend guard, $0.00 default
  gate.py          command gate policy (from dydema-idle-gate, MIT, same author)
  adapter.py       Dydema response validation
  audit.py         hash-chained decision + cost log
  synthetic.py     synthetic trials for demos/tests (NOT real EEG)
  neurocomm.py     clean-room cheap-EEG bridge (credit: weavejul/NeuroComm)
  fake_gateway.py  local fake of the documented API for tests and offline demo
  cli.py           simulate / estimate / usage / list / demo
tests/             38 tests, all against the fake gateway, no key needed
```

## Sources

- API behavior: https://developers.dydema.com/docs and https://developers.dydema.com/llms.txt
- Gate policy: https://github.com/harshitgavita-07/dydema-idle-gate
- Cheap-EEG paradigm: https://github.com/weavejul/NeuroComm (no license; idea credited, no code copied)

MIT License (see LICENSE). Research use only; not a medical device.
