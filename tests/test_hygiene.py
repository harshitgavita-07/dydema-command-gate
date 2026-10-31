import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY_PATTERN = re.compile(r"dk_live_[A-Za-z0-9]{16}_[A-Za-z0-9]{48}")


class HygieneTest(unittest.TestCase):
    def test_env_is_gitignored(self):
        with open(os.path.join(ROOT, ".gitignore")) as handle:
            lines = [line.strip() for line in handle]
        self.assertIn(".env", lines)

    def test_env_example_has_no_real_key(self):
        with open(os.path.join(ROOT, ".env.example")) as handle:
            content = handle.read()
        self.assertIn("DYDEMA_API_KEY", content)
        self.assertIsNone(KEY_PATTERN.search(content))

    def test_no_real_key_anywhere_in_repo(self):
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__"}]
            for filename in filenames:
                path = os.path.join(dirpath, filename)
                with open(path, "rb") as handle:
                    content = handle.read().decode("utf-8", errors="ignore")
                self.assertIsNone(KEY_PATTERN.search(content), f"key material in {path}")


if __name__ == "__main__":
    unittest.main()
