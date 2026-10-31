import unittest

from dydema_gate.gate import GateConfig, IdleGate


def pred(left, right, rest):
    return {"probabilities": {"left": left, "right": right, "rest": rest}}


class AdversarialGateTest(unittest.TestCase):
    def test_oscillating_strong_labels_never_fire(self):
        gate = IdleGate(GateConfig())
        for i in range(20):
            p = pred(0.9, 0.05, 0.05) if i % 2 == 0 else pred(0.05, 0.9, 0.05)
            decision = gate.update(p, now_ms=i * 250)
            self.assertFalse(decision.fired)

    def test_perfect_tie_never_fires(self):
        gate = IdleGate(GateConfig())
        for i in range(10):
            decision = gate.update(pred(0.45, 0.45, 0.10), now_ms=i * 250)
            self.assertFalse(decision.fired)

    def test_dip_below_exit_mid_dwell_resets_candidate(self):
        gate = IdleGate(GateConfig())
        gate.update(pred(0.85, 0.05, 0.10), now_ms=0)
        gate.update(pred(0.85, 0.05, 0.10), now_ms=250)
        dip = gate.update(pred(0.50, 0.05, 0.45), now_ms=500)  # below exit: reset
        self.assertFalse(dip.fired)
        states = [gate.update(pred(0.85, 0.05, 0.10), now_ms=750 + i * 250).state for i in range(3)]
        self.assertEqual(states, ["candidate", "candidate", "fire"])  # full dwell again

    def test_drift_recovers_after_stream_settles(self):
        gate = IdleGate(GateConfig(drift_window=20, drift_js_threshold=0.3))
        t = 0
        for _ in range(20):
            gate.update(pred(0.7, 0.2, 0.1), now_ms=t); t += 250
        saw_block = False
        for _ in range(20):
            if gate.update(pred(0.05, 0.9, 0.05), now_ms=t).state == "blocked_drift":
                saw_block = True
            t += 250
        self.assertTrue(saw_block)
        # settle back to the baseline-ish mixture; drift must clear and gating resume
        recovered = False
        for _ in range(80):
            decision = gate.update(pred(0.7, 0.2, 0.1), now_ms=t); t += 250
            if decision.state != "blocked_drift":
                recovered = True
        self.assertTrue(recovered)

    def test_refractory_does_not_reattack_without_rest_rearm(self):
        gate = IdleGate(GateConfig(refractory_ms=500))
        t = 0
        for _ in range(3):
            gate.update(pred(0.85, 0.05, 0.10), now_ms=t); t += 250
        # sustained identical command long past the refractory window:
        # no rest window means no re-arm, so no second fire
        for _ in range(20):
            decision = gate.update(pred(0.85, 0.05, 0.10), now_ms=t); t += 250
            self.assertFalse(decision.fired)


if __name__ == "__main__":
    unittest.main()
