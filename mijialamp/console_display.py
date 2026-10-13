"""Windows console display notifications for the Session 0 service.

PowerSettingRegisterNotification supplies the current value immediately after
registration. The callback only queues states; LAN control runs on a worker.
"""

from __future__ import annotations

import ctypes
import os
import queue
import threading


class _Guid(ctypes.Structure):
    _fields_ = [
        ("data1", ctypes.c_uint32),
        ("data2", ctypes.c_uint16),
        ("data3", ctypes.c_uint16),
        ("data4", ctypes.c_ubyte * 8),
    ]


_CONSOLE_DISPLAY_GUID = _Guid(
    0x6FE69556,
    0x704A,
    0x47A0,
    (ctypes.c_ubyte * 8)(0x8F, 0x24, 0xC2, 0x8D, 0x93, 0x6F, 0xDA, 0x47),
)
_CALLBACK = ctypes.WINFUNCTYPE if os.name == "nt" else ctypes.CFUNCTYPE
_CALLBACK_TYPE = _CALLBACK(ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p)


class _SubscribeParameters(ctypes.Structure):
    _fields_ = [("callback", _CALLBACK_TYPE), ("context", ctypes.c_void_p)]


class _PowerBroadcastSetting(ctypes.Structure):
    _fields_ = [("guid", _Guid), ("data_length", ctypes.c_uint32), ("data", ctypes.c_uint32)]


def _display_value(event_type: int, setting: int | None) -> bool | None:
    if event_type != 0x8013 or not setting:  # PBT_POWERSETTINGCHANGE
        return None
    value = ctypes.cast(setting, ctypes.POINTER(_PowerBroadcastSetting)).contents
    guid = value.guid
    if (
        guid.data1 != _CONSOLE_DISPLAY_GUID.data1
        or guid.data2 != _CONSOLE_DISPLAY_GUID.data2
        or guid.data3 != _CONSOLE_DISPLAY_GUID.data3
        or bytes(guid.data4) != bytes(_CONSOLE_DISPLAY_GUID.data4)
        or value.data_length != 4
    ):
        return None
    if value.data == 0:
        return False
    if value.data in (1, 2):  # ON or dimmed: the lock screen is still visible.
        return True
    return None


class ConsoleDisplayMonitor:
    def __init__(self, on_display, logger):
        self.on_display = on_display
        self.log = logger
        self._events: queue.Queue[bool | None] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._handle = ctypes.c_void_p()
        self._callback = None
        self._parameters = None
        self._api = None

    def _notify(self, _context, event_type, setting):
        try:
            state = _display_value(event_type, setting)
            if state is not None:
                self._events.put_nowait(state)
        except Exception as exc:
            self.log.warning("Console display notification ignored: %s", exc)
        return 0

    def _run(self):
        while True:
            state = self._events.get()
            if state is None:
                return
            try:
                self.log.info("Console display: %s", "on" if state else "off")
                self.on_display(state)
            except Exception as exc:
                self.log.warning("Console display sync failed: %s", exc)

    def start(self):
        if os.name != "nt":
            raise OSError("Console display notifications require Windows")
        self._api = ctypes.WinDLL("Powrprof.dll")
        register = self._api.PowerSettingRegisterNotification
        register.argtypes = [
            ctypes.POINTER(_Guid),
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        register.restype = ctypes.c_uint32
        self._callback = _CALLBACK_TYPE(self._notify)
        self._parameters = _SubscribeParameters(self._callback, None)
        self._worker = threading.Thread(target=self._run, name="MijiaLampConsoleDisplay", daemon=True)
        self._worker.start()
        result = register(
            ctypes.byref(_CONSOLE_DISPLAY_GUID),
            2,  # DEVICE_NOTIFY_CALLBACK
            ctypes.cast(ctypes.byref(self._parameters), ctypes.c_void_p),
            ctypes.byref(self._handle),
        )
        if result:
            self._events.put(None)
            self._worker.join(timeout=2)
            raise OSError(result, "PowerSettingRegisterNotification failed")

    def stop(self):
        if self._handle.value and self._api is not None:
            unregister = self._api.PowerSettingUnregisterNotification
            unregister.argtypes = [ctypes.c_void_p]
            unregister.restype = ctypes.c_uint32
            result = unregister(self._handle)
            if result:
                self.log.warning("PowerSettingUnregisterNotification failed: %s", result)
            self._handle = ctypes.c_void_p()
        self._events.put(None)
        if self._worker:
            self._worker.join(timeout=2)
        self._callback = None
        self._parameters = None
