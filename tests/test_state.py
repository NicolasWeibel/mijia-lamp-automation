import json
import tempfile
import unittest
from pathlib import Path

from mijialamp.state import StateStore


class StateStoreTests(unittest.TestCase):
    def test_atomic_update_and_read(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = StateStore(root / "runtime.json", root / "runtime.lock")
            store.update(display_on=True, marker="one")
            store.update(manual_off_active=True, marker="two")
            state = store.read()
            self.assertTrue(state["display_on"])
            self.assertTrue(state["manual_off_active"])
            self.assertEqual(state["marker"], "two")
            with open(root / "runtime.json", encoding="utf-8") as fh:
                json.load(fh)
            self.assertEqual(list(root.glob(".*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
