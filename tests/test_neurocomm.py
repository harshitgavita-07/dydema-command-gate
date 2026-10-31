import unittest

from dydema_gate import neurocomm
from dydema_gate.gate import GateConfig, IdleGate

WINDOW_MS = 250


class NeuroCommTest(unittest.TestCase):
    def test_concentrated_reading_favors_command(self):
        prediction = neurocomm.from_brain_reading(
            {"signal_quality": 0, "attention": 95, "meditation": 10})
        self.assertGreater(prediction["probabilities"]["concentrate"], 0.8)

    def test_unconcentrated_reading_favors_rest(self):
        prediction = neurocomm.from_brain_reading(
            {"signal_quality": 0, "attention": 20, "meditation": 80})
        self.assertGreater(prediction["probabilities"]["rest"], 0.7)

    def test_poor_contact_forces_abstention(self):
        prediction = neurocomm.from_brain_reading(
            {"signal_quality": 200, "attention": 100, "meditation": 0})
        self.assertGreater(prediction["probabilities"]["rest"], 0.9)

    def test_validation(self):
        with self.assertRaises(ValueError):
            neurocomm.from_brain_reading({"signal_quality": 0, "attention": 120, "meditation": 0})
        with self.assertRaises(ValueError):
            neurocomm.from_brain_reading({"attention": 50, "meditation": 50})
        with self.assertRaises(ValueError):
            neurocomm.from_brain_reading({"signal_quality": 201, "attention": 50, "meditation": 50})

    def test_session_replay_fires_only_when_focused(self):
        gate = IdleGate(GateConfig())
        fired_when_unfocused = 0
        fired_total = 0
        for i, reading in enumerate(neurocomm.simulate_session()):
            prediction = neurocomm.from_brain_reading(reading)
            decision = gate.update(prediction, now_ms=i * WINDOW_MS)
            if decision.fired:
                fired_total += 1
                if reading["attention"] < 60 or reading["signal_quality"] >= 100:
                    fired_when_unfocused += 1
        self.assertGreaterEqual(fired_total, 1)  # the strong-focus block fires
        self.assertEqual(fired_when_unfocused, 0)  # never during rest or poor contact


if __name__ == "__main__":
    unittest.main()
