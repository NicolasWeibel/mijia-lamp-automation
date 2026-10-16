import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import mijialamp.ipc as ipc
from mijialamp.ipc import IPCError, PipeClient, PipeServer, decode_message, encode_message


class WindowsPipeError(OSError):
    def __init__(self, winerror):
        super().__init__(winerror, "test pipe error")
        self.winerror = winerror


class PipeConnectionTests(unittest.TestCase):
    def setUp(self):
        self.clock = 0.0
        self.file = SimpleNamespace(
            GENERIC_READ=1,
            GENERIC_WRITE=2,
            OPEN_EXISTING=3,
            CreateFile=Mock(return_value="handle"),
            WriteFile=Mock(),
            CloseHandle=Mock(),
        )
        self.pipe = SimpleNamespace(
            PIPE_READMODE_MESSAGE=2,
            WaitNamedPipe=Mock(side_effect=lambda *_args: self.advance(0.005)),
            SetNamedPipeHandleState=Mock(),
        )
        self.client = PipeClient()
        for context in (
            patch.dict("sys.modules", {"win32file": self.file, "win32pipe": self.pipe}),
            patch.object(ipc.time, "monotonic", side_effect=lambda: self.clock),
            patch.object(ipc.time, "sleep", side_effect=self.advance),
        ):
            context.start()
            self.addCleanup(context.stop)

    def advance(self, seconds):
        self.clock += seconds

    def test_busy_race_retries_connection_without_sending_duplicate_event(self):
        self.file.CreateFile.side_effect = [WindowsPipeError(231), "handle"]
        with patch.object(ipc.os, "name", "nt"):
            self.client.notify("display", timeout=0.5, on=True)
        self.assertEqual(self.file.CreateFile.call_count, 2)
        waits = [call.args[1] for call in self.pipe.WaitNamedPipe.call_args_list]
        self.assertEqual(waits[0], 500)
        self.assertLess(waits[1], waits[0])
        self.pipe.SetNamedPipeHandleState.assert_called_once_with("handle", 2, None, None)
        self.file.WriteFile.assert_called_once()
        self.assertEqual(
            decode_message(self.file.WriteFile.call_args.args[1]),
            {"command": "display", "_oneway": True, "on": True},
        )
        self.file.CloseHandle.assert_called_once_with("handle")

    def test_persistent_busy_race_stops_at_original_deadline(self):
        error = WindowsPipeError(231)
        self.file.CreateFile.side_effect = error
        with self.assertRaises(WindowsPipeError) as caught:
            self.client._open(0.03)
        self.assertIs(caught.exception, error)
        self.assertGreater(self.file.CreateFile.call_count, 1)
        self.assertAlmostEqual(self.clock, 0.03)
        self.assertLessEqual(self.pipe.WaitNamedPipe.call_args.args[1], 30)
        self.file.WriteFile.assert_not_called()
        self.file.CloseHandle.assert_not_called()

    def test_access_denied_is_not_retried(self):
        error = WindowsPipeError(5)
        self.file.CreateFile.side_effect = error
        with self.assertRaises(WindowsPipeError) as caught:
            self.client._open(0.5)
        self.assertIs(caught.exception, error)
        self.file.CreateFile.assert_called_once()
        self.file.CloseHandle.assert_not_called()

    def test_missing_pipe_and_wait_timeout_are_not_retried(self):
        for code in (2, 121):
            with self.subTest(code=code):
                self.pipe.WaitNamedPipe.reset_mock()
                self.pipe.WaitNamedPipe.side_effect = WindowsPipeError(code)
                with self.assertRaises(WindowsPipeError):
                    self.client._open(0.5)
                self.pipe.WaitNamedPipe.assert_called_once()
                self.file.CreateFile.assert_not_called()

    def test_handle_is_closed_if_message_mode_configuration_fails(self):
        error = WindowsPipeError(5)
        self.pipe.SetNamedPipeHandleState.side_effect = error
        with self.assertRaises(WindowsPipeError) as caught:
            self.client._open(0.5)
        self.assertIs(caught.exception, error)
        self.file.CloseHandle.assert_called_once_with("handle")


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
