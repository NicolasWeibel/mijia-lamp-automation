import unittest

from mijialamp.ipc import IPCError, PipeServer, decode_message, encode_message


class IPCTests(unittest.TestCase):
    def test_json_round_trip(self):
        original = {"command": "display", "on": True, "event": "test"}
        self.assertEqual(decode_message(encode_message(original)), original)

    def test_non_dict_rejected(self):
        with self.assertRaises(IPCError):
            decode_message(b"[]")

    def test_pipe_server_rejects_invalid_worker_limit(self):
        with self.assertRaises(IPCError):
            PipeServer(lambda _: None, authorized_user_sid="S-1-5-21-1", max_clients=0)


if __name__ == "__main__":
    unittest.main()
