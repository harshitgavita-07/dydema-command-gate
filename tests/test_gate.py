import unittest

from dydema_gate.gate import GateConfig, IdleGate


def pred(left, right, rest):
    return {"probabilities": {"left": left, "right": right, "rest": rest}}


class GateTest(unittest.TestCase):
    def test_sustained_command_fires_after_dwell(self):
        gate = IdleGate(GateConfig())
        states = [gate.update(pred(0.85, 0.05, 0.10), now_ms=i * 250).state for i in range(4)]
        self.assertEqual(states[:3], ["candidate", "candidate", "fire"])
        self.assertEqual(states[3], "refractory")

    def test_rest_never_fires(self):
        gate = IdleGate(GateConfig())
        for i in range(10):
            decision = gate.update(pred(0.10, 0.05, 0.85), now_ms=i * 250)
            self.assertFalse(decision.fired)

    def test_weak_evidence_does_not_accumulate(self):
        gate = IdleGate(GateConfig())
        for i in range(10):
            decision = gate.update(pred(0.65, 0.20, 0.15), now_ms=i * 250)
            self.assertFalse(decision.fired)

    def test_refractory_suppresses_repeat(self):
        gate = IdleGate(GateConfig(refractory_ms=900))
        t = 0
        for _ in range(3):
            gate.update(pred(0.85, 0.05, 0.10), now_ms=t); t += 250
        decision = gate.update(pred(0.85, 0.05, 0.10), now_ms=t)
        self.assertEqual(decision.state, "refractory")
        self.assertFalse(decision.fired)

    def test_rest_rearms(self):
        gate = IdleGate(GateConfig(refractory_ms=10_000))
        t = 0
        for _ in range(3):
            gate.update(pred(0.85, 0.05, 0.10), now_ms=t); t += 250
        gate.update(pred(0.10, 0.05, 0.85), now_ms=t); t += 250  # rest re-arms
        states = [gate.update(pred(0.85, 0.05, 0.10), now_ms=t + i * 250).state for i in range(3)]
        self.assertEqual(states[-1], "fire")

    def test_drift_blocks_runaway_stream(self):
        gate = IdleGate(GateConfig(drift_window=20, drift_js_threshold=0.3))
        t = 0
        for _ in range(20):
            gate.update(pred(0.7, 0.2, 0.1), now_ms=t); t += 250  # mixed baseline
        blocked = 0
        for _ in range(20):
            decision = gate.update(pred(0.05, 0.9, 0.05), now_ms=t); t += 250
            if decision.state == "blocked_drift":
                blocked += 1
        self.assertGreater(blocked, 0)

    def test_probabilities_are_validated(self):
        gate = IdleGate(GateConfig())
        with self.assertRaises(ValueError):
            gate.update({"probabilities": {"left": 0.9, "right": 0.9}}, now_ms=0)
        with self.assertRaises(ValueError):
            gate.update({"probabilities": {"left": 1.0}}, now_ms=0)
        with self.assertRaises(ValueError):
            gate.update({"probabilities": {"left": "high", "right": 0.1}}, now_ms=0)


if __name__ == "__main__":
    unittest.main()
