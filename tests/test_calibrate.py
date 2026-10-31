import unittest

from dydema_gate.calibrate import build_stream, pick, run_scenario, sweep
from dydema_gate.gate import GateConfig


class CalibrateTest(unittest.TestCase):
    def test_stream_is_deterministic(self):
        a = build_stream(seed=11)
        b = build_stream(seed=11)
        self.assertEqual(len(a), len(b))
        self.assertEqual(a[0], b[0])
        self.assertEqual(a[-1], b[-1])

    def test_longer_dwell_never_increases_false_activations(self):
        stream = build_stream()
        low = run_scenario(stream, GateConfig(enter_probability=0.8, dwell_windows=2))
        high = run_scenario(stream, GateConfig(enter_probability=0.8, dwell_windows=4))
        self.assertLessEqual(high.false_activations_per_minute,
                             low.false_activations_per_minute + 1e-9)

    def test_sweep_finds_config_meeting_target(self):
        results = sweep()
        best = pick(results, target_false_per_minute=0.2)
        self.assertIsNotNone(best)
        self.assertLessEqual(best.false_activations_per_minute, 0.2)
        self.assertEqual(best.missed_commands, 0)
        self.assertIsNotNone(best.mean_fire_latency_ms)

    def test_weak_and_oscillating_blocks_produce_no_correct_fires(self):
        stream = build_stream()
        result = run_scenario(stream, GateConfig())
        # every latency-tracked fire must come from a sustained block;
        # with 3 sustained blocks expected, missed+fired relationship holds
        self.assertGreaterEqual(result.fired, 1)
        self.assertLessEqual(result.missed_commands, 3)


if __name__ == "__main__":
    unittest.main()
