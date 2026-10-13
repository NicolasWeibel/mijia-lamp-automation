import time
import unittest

import sleepnow
from mijialamp.i18n import language


class _Client:
    def __init__(self, *, delay=0.0, error=None, response=None):
        self.delay = delay
        self.error = error
        self.response = {"off": True} if response is None else response

    def request(self, command, timeout=1.0, **params):
        self.command = command
        self.params = params
        time.sleep(self.delay)
        if self.error:
            raise RuntimeError(self.error)
        return self.response


class SleepNowTests(unittest.TestCase):
    def test_confirmed_off_success(self):
        client = _Client()
        ok, error = sleepnow._confirmed_off(client, timeout=0.2)
        self.assertTrue(ok)
        self.assertIsNone(error)
        self.assertEqual(client.command, "suspend")
        self.assertGreater(client.params["not_after_monotonic"], time.monotonic())

    def test_confirmed_off_rejects_unconfirmed_result(self):
        with language("en"):
            ok, error = sleepnow._confirmed_off(_Client(response={"off": False}), timeout=0.2)
        self.assertFalse(ok)
        self.assertIn("did not confirm", error)

    def test_confirmed_off_error(self):
        ok, error = sleepnow._confirmed_off(_Client(error="boom"), timeout=0.2)
        self.assertFalse(ok)
        self.assertIn("boom", error)

    def test_confirmed_off_is_bounded(self):
        started = time.monotonic()
        with language("en"):
            ok, error = sleepnow._confirmed_off(_Client(delay=1.0), timeout=0.05)
        elapsed = time.monotonic() - started
        self.assertFalse(ok)
        self.assertIn("Timed out", error)
        self.assertLess(elapsed, 0.5)


if __name__ == "__main__":
    unittest.main()
