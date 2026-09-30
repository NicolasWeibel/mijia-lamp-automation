import time
import unittest

import sleepnow


class _Client:
    def __init__(self, *, delay=0.0, error=None):
        self.delay = delay
        self.error = error

    def request(self, command, timeout=1.0):
        self.command = command
        time.sleep(self.delay)
        if self.error:
            raise RuntimeError(self.error)
        return {"ok": True}


class SleepNowTests(unittest.TestCase):
    def test_confirmed_off_success(self):
        client = _Client()
        ok, error = sleepnow._confirmed_off(client, timeout=0.2)
        self.assertTrue(ok)
        self.assertIsNone(error)
        self.assertEqual(client.command, "suspend")

    def test_confirmed_off_error(self):
        ok, error = sleepnow._confirmed_off(_Client(error="boom"), timeout=0.2)
        self.assertFalse(ok)
        self.assertIn("boom", error)

    def test_confirmed_off_is_bounded(self):
        started = time.monotonic()
        ok, error = sleepnow._confirmed_off(_Client(delay=1.0), timeout=0.05)
        elapsed = time.monotonic() - started
        self.assertFalse(ok)
        self.assertIn("timeout", error)
        self.assertLess(elapsed, 0.5)


if __name__ == "__main__":
    unittest.main()
