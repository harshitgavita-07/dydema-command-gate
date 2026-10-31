import unittest

from dydema_gate.budget import Budget
from dydema_gate.client import DydemaClient
from dydema_gate.errors import DydemaError, SpendRefused
from dydema_gate.fake_gateway import FakeGateway
from dydema_gate import synthetic

NO_SLEEP = lambda s: None


class ClientTest(unittest.TestCase):
    def setUp(self):
        self.gateway = FakeGateway().__enter__()
        self.addCleanup(self.gateway.__exit__)
        self.budget = Budget()
        self.client = DydemaClient("dk_live_test", base_url=self.gateway.base_url,
                                   budget=self.budget, sleep=NO_SLEEP)

    def test_auth_required(self):
        bad = DydemaClient("not-a-key", base_url=self.gateway.base_url, sleep=NO_SLEEP)
        with self.assertRaises(DydemaError) as ctx:
            bad.usage()
        self.assertEqual(ctx.exception.code, "UNAUTHENTICATED")
        self.assertEqual(ctx.exception.status, 401)

    def test_revoked_key(self):
        bad = DydemaClient("dk_live_revoked1234567890_x", base_url=self.gateway.base_url,
                           sleep=NO_SLEEP)
        with self.assertRaises(DydemaError) as ctx:
            bad.usage()
        self.assertEqual(ctx.exception.code, "KEY_REVOKED")

    def test_dry_run_is_free_at_zero_cap(self):
        estimate = self.client.estimate(synthetic.training_payload())
        self.assertEqual(estimate["create_usd"], "1.00")
        self.assertEqual(str(self.budget.spent_usd), "0.000")

    def test_zero_shot_estimate(self):
        estimate = self.client.estimate(synthetic.zero_shot_estimate_payload())
        self.assertEqual(estimate["mode"], "zero_shot")
        self.assertIn("eyes_closed", estimate["classes"])

    def test_paid_create_blocked_at_zero_cap_without_hitting_server(self):
        hits = self.gateway.state.hits
        with self.assertRaises(SpendRefused):
            self.client.create_task_model(synthetic.training_payload())
        self.assertEqual(self.gateway.state.hits, hits)  # never left the machine

    def test_create_predict_delete_flow_and_costs(self):
        self.budget.allow_spend("2.00")
        model = self.client.create_task_model(synthetic.training_payload())
        self.assertTrue(model["id"].startswith("clf_"))
        self.assertEqual(str(self.budget.spent_usd), "1.000")
        response = self.client.predict(model["id"], synthetic.prediction_payload(["left"]))
        prediction = response["data"][0]
        self.assertEqual(prediction["label"], "left")
        self.assertGreater(prediction["probabilities"]["left"], 0.7)
        self.assertEqual(str(self.budget.spent_usd), "1.003")
        usage = self.client.usage()
        self.assertEqual(usage["month"]["windows"], "1")
        self.client.delete_task_model(model["id"])
        with self.assertRaises(DydemaError) as ctx:
            self.client.get_task_model(model["id"])
        self.assertEqual(ctx.exception.code, "CLASSIFIER_NOT_FOUND")

    def test_prediction_labels_match_stimulated_side(self):
        self.budget.allow_spend("2.00")
        model = self.client.create_task_model(synthetic.training_payload())
        for truth in ("left", "right", "rest"):
            response = self.client.predict(model["id"], synthetic.prediction_payload([truth]))
            self.assertEqual(response["data"][0]["label"], truth)

    def test_retry_after_503_succeeds_and_bills_once(self):
        self.budget.allow_spend("2.00")
        self.gateway.arm_error(503, "POOL_UNAVAILABLE", times=2)
        model = self.client.create_task_model(synthetic.training_payload())
        self.assertEqual(model["status"], "active")
        # two failed attempts + one success, but the create fee appears once
        self.assertEqual(str(self.budget.spent_usd), "1.000")

    def test_retry_429_rate_limited(self):
        self.gateway.arm_error(429, "RATE_LIMITED", times=1)
        usage = self.client.usage()
        self.assertIn("limits", usage)

    def test_no_retry_on_person_action_codes(self):
        self.gateway.arm_error(402, "INSUFFICIENT_CREDIT", times=3)
        hits = self.gateway.state.hits
        with self.assertRaises(DydemaError) as ctx:
            self.client.usage()
        self.assertEqual(ctx.exception.code, "INSUFFICIENT_CREDIT")
        self.assertEqual(self.gateway.state.hits, hits + 1)  # exactly one attempt

    def test_gives_up_after_max_attempts(self):
        self.gateway.arm_error(500, "INTERNAL", times=10)
        with self.assertRaises(DydemaError) as ctx:
            self.client.usage()
        self.assertEqual(ctx.exception.status, 500)

    def test_units_validation(self):
        payload = synthetic.training_payload()
        payload["units"] = "unknown"
        with self.assertRaises(DydemaError) as ctx:
            self.client.estimate(payload)
        self.assertEqual(ctx.exception.code, "UNITS_REQUIRED")

    def test_too_few_trials(self):
        payload = synthetic.training_payload(labels=["left", "right"])
        with self.assertRaises(DydemaError) as ctx:
            self.client.estimate(payload)
        self.assertEqual(ctx.exception.code, "TOO_FEW_TRIALS")

    def test_task_unsupported(self):
        payload = synthetic.training_payload()
        payload["description"] = "Emotion recognition from EEG"
        with self.assertRaises(DydemaError) as ctx:
            self.client.estimate(payload)
        self.assertEqual(ctx.exception.code, "TASK_UNSUPPORTED")


if __name__ == "__main__":
    unittest.main()
