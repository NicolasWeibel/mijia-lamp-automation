import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mijialamp.errors import ConfigError
from mijialamp.ipc import build_pipe_sddl
from mijialamp.service_meta import load_authorized_user_sid


class ServiceSecurityTests(unittest.TestCase):
    def test_pipe_acl_is_bound_to_specific_user(self):
        sid = "S-1-5-21-100-200-300-1001"
        service_sid = "S-1-5-80-111-222-333-444-555"
        sddl = build_pipe_sddl(sid, service_sid)
        self.assertIn(sid, sddl)
        self.assertIn(service_sid, sddl)
        self.assertNotIn(";;;IU)", sddl)
        self.assertNotIn(";;;LS)", sddl)
        self.assertIn(";;;BA)", sddl)

    def test_service_meta_sid_validation(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "service_meta.json"
            path.write_text(json.dumps({"authorized_user_sid": "S-1-5-21-1-2-3-1001"}))
            with patch("mijialamp.service_meta.SERVICE_META_PATH", path):
                self.assertEqual(load_authorized_user_sid(), "S-1-5-21-1-2-3-1001")
            path.write_text(json.dumps({"authorized_user_sid": "not-a-sid"}))
            with patch("mijialamp.service_meta.SERVICE_META_PATH", path), self.assertRaises(ConfigError):
                load_authorized_user_sid()


if __name__ == "__main__":
    unittest.main()
