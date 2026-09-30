import unittest

from mijialamp.util import redact_secrets


class SecurityTests(unittest.TestCase):
    def test_token_like_hex_is_redacted(self):
        token = "a" * 32
        self.assertNotIn(token, redact_secrets(f"failed token={token}"))
        self.assertIn("<redacted-token>", redact_secrets(token))


if __name__ == "__main__":
    unittest.main()
