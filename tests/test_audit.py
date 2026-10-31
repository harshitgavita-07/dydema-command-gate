import unittest

from dydema_gate.audit import AuditLog


class AuditTest(unittest.TestCase):
    def test_chain_verifies(self):
        log = AuditLog()
        log.append({"state": "idle", "fired": False})
        log.append({"state": "fire", "fired": True, "command": "left", "usage_usd": "0.003"})
        self.assertTrue(log.verify())
        summary = log.summary()
        self.assertTrue(summary["chain_valid"])
        self.assertEqual(summary["fired"], 1)
        self.assertEqual(summary["entries"], 2)

    def test_tampering_breaks_chain(self):
        log = AuditLog()
        log.append({"state": "idle"})
        log.append({"state": "fire", "fired": True})
        log.entries[0]["state"] = "fire"  # tamper
        self.assertFalse(log.verify())


if __name__ == "__main__":
    unittest.main()
