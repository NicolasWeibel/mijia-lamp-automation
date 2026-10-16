import ctypes
import unittest

from mijialamp.console_display import (
    _CONSOLE_DISPLAY_GUID,
    _display_value,
    _PowerBroadcastSetting,
)


class ConsoleDisplayTests(unittest.TestCase):
    def test_display_power_values(self):
        setting = _PowerBroadcastSetting(_CONSOLE_DISPLAY_GUID, 4, 0)
        address = ctypes.addressof(setting)
        self.assertIs(_display_value(0x8013, address), False)
        setting.data = 1
        self.assertIs(_display_value(0x8013, address), True)
        setting.data = 2
        self.assertIs(_display_value(0x8013, address), True)
        setting.data = 3
        self.assertIsNone(_display_value(0x8013, address))

    def test_ignores_unrelated_and_malformed_events(self):
        setting = _PowerBroadcastSetting(_CONSOLE_DISPLAY_GUID, 4, 1)
        address = ctypes.addressof(setting)
        self.assertIsNone(_display_value(0x12, address))
        self.assertIsNone(_display_value(0x8013, None))
        setting.data_length = 0
        self.assertIsNone(_display_value(0x8013, address))
        setting.data_length = 4
        setting.guid.data1 ^= 1
        self.assertIsNone(_display_value(0x8013, address))


if __name__ == "__main__":
    unittest.main()
