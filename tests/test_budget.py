import unittest

from dydema_gate.budget import Budget
from dydema_gate.errors import SpendRefused


class BudgetTest(unittest.TestCase):
    def test_default_cap_is_zero_and_blocks_paid(self):
        budget = Budget()
        self.assertEqual(str(budget.cap_usd), "0.00")
        with self.assertRaises(SpendRefused):
            budget.authorize("create", "POST /task-models")

    def test_free_kinds_always_pass_at_zero(self):
        budget = Budget()
        budget.authorize("free", "GET /v1/usage")  # no raise

    def test_cap_allows_until_spent(self):
        budget = Budget()
        budget.allow_spend("1.50")
        budget.authorize("create", "POST /task-models")
        budget.record("POST /task-models", "1.000")
        budget.authorize("predictions", "POST /predictions")  # 1.00 < 1.50 ok
        budget.record("POST /predictions", "0.501")
        with self.assertRaises(SpendRefused):
            budget.authorize("predictions", "POST /predictions")

    def test_ledger_tracks_every_recorded_call(self):
        budget = Budget()
        budget.record("POST /task-models", "1.000")
        budget.record("POST /predictions", "0.006")
        budget.record("GET /usage", None)
        self.assertEqual(str(budget.spent_usd), "1.006")
        self.assertEqual(len(budget.ledger), 3)

    def test_negative_cap_rejected(self):
        with self.assertRaises(ValueError):
            Budget().allow_spend("-1")


if __name__ == "__main__":
    unittest.main()
