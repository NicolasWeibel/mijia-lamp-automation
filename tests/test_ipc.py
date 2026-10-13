import unittest
from types import SimpleNamespace
from unittest.mock import patch

import mijialamp.ipc as ipc
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

    def test_listener_recovers_after_client_disconnects_before_connect(self):
        server = PipeServer(lambda _: None, authorized_user_sid="S-1-5-21-1")
        server._security_attributes = lambda: None
        created = []
        closed = []

        class NoDataError(Exception):
            winerror = 232

        def create_pipe(*_args):
            created.append(len(created) + 1)
            return created[-1]

        def connect_pipe(_handle, _overlapped):
            if len(created) == 2:
                server._stop.set()
            raise NoDataError("client closed")

        fake_pipe = SimpleNamespace(
            PIPE_TYPE_MESSAGE=1,
            PIPE_READMODE_MESSAGE=2,
            PIPE_WAIT=4,
            PIPE_ACCESS_DUPLEX=8,
            PIPE_UNLIMITED_INSTANCES=255,
            CreateNamedPipe=create_pipe,
            ConnectNamedPipe=connect_pipe,
        )
        fake_file = SimpleNamespace(CloseHandle=closed.append)
        with (
            patch.object(ipc.os, "name", "nt"),
            patch.dict("sys.modules", {"win32file": fake_file, "win32pipe": fake_pipe}),
        ):
            server.serve_forever()
        self.assertEqual(created, [1, 2])
        self.assertEqual(closed, [1, 2])


if __name__ == "__main__":
    unittest.main()
