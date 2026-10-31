import io
import unittest
from contextlib import redirect_stdout

from dydema_gate import cli


class SimulateTest(unittest.TestCase):
    def test_simulate_runs_clean(self):
        out = io.StringIO()
        with redirect_stdout(out):
            exit_code = cli.main(["simulate"])
        self.assertEqual(exit_code, 0)
        text = out.getvalue()
        self.assertIn("false_activations=0", text)
        self.assertIn("locked, as designed", text)
        self.assertIn("audit chain valid: True", text)
        self.assertIn("fired_while_unfocused_or_poor_contact=0", text)

    def test_demo_refuses_without_allow_spend(self):
        with self.assertRaises(SystemExit) as ctx:
            cli.main(["demo"])
        self.assertIn("--allow-spend", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
