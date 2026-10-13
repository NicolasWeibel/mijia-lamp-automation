import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from mijialamp.errors import CommunicationError
from mijialamp.miio_client import MiioLampClient


class FakeProtocol:
    def __init__(self, did=123456789):
        self.did = did
        self.discover_calls = []
        self._discovered = False
        self._device_id = b""
        self._device_ts = datetime.now()
        self._timeout = 5.0

    def discover(self, ip, *, timeout):
        self.discover_calls.append((ip, timeout))
        return SimpleNamespace(
            header=SimpleNamespace(
                value=SimpleNamespace(device_id=self.did.to_bytes(4, "big"), ts=datetime.now())
            )
        )


class FakeDevice:
    def __init__(self, protocol):
        self._protocol = protocol
        self.commands = []

    def send(self, command, parameters, retry_count):
        assert self._protocol._discovered
        self.commands.append((command, parameters, retry_count, self._protocol._timeout))


class CriticalOffTests(unittest.TestCase):
    def make_client(self, protocol):
        client = MiioLampClient({"lamp_ip": "192.168.1.100", "device_id": "123456789"}, None)
        device = FakeDevice(protocol)
        client._device = lambda _ip, _timeout: device
        return client, device

    def test_cached_header_sends_without_handshake(self):
        protocol = FakeProtocol()
        client, device = self.make_client(protocol)
        with patch("mijialamp.miio_client.time.monotonic", return_value=100.0):
            previous = FakeProtocol()
            previous._discovered = True
            previous._device_id = (123456789).to_bytes(4, "big")
            client._remember_critical_session(FakeDevice(previous), "192.168.1.100")
            client.set_power_critical_off(timeout=0.25)
        self.assertEqual(protocol.discover_calls, [])
        self.assertEqual(device.commands[0][:3], ("set_power", ["off"], 0))
        self.assertLessEqual(device.commands[0][3], 0.25)

    def test_unprimed_header_uses_one_bounded_handshake(self):
        protocol = FakeProtocol()
        client, device = self.make_client(protocol)
        client.set_power_critical_off(timeout=0.25)
        self.assertEqual(len(protocol.discover_calls), 1)
        self.assertGreater(protocol.discover_calls[0][1], 0)
        self.assertLessEqual(protocol.discover_calls[0][1], 0.25)
        self.assertEqual(device.commands[0][:3], ("set_power", ["off"], 0))

    def test_wrong_device_id_never_receives_off(self):
        protocol = FakeProtocol(did=123456788)
        client, device = self.make_client(protocol)
        with self.assertRaises(CommunicationError):
            client.set_power_critical_off(timeout=0.25)
        self.assertEqual(device.commands, [])

    def test_subnet_probe_uses_configured_timeout(self):
        protocol = FakeProtocol()
        client, _device = self.make_client(protocol)
        self.assertEqual(client._probe_handshake_did("192.168.1.42", 0.4), "123456789")
        self.assertEqual(protocol.discover_calls, [("192.168.1.42", 0.4)])


if __name__ == "__main__":
    unittest.main()
