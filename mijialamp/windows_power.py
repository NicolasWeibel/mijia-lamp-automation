from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

SE_PRIVILEGE_ENABLED = 0x00000002
TOKEN_ADJUST_PRIVILEGES = 0x0020
TOKEN_QUERY = 0x0008
ERROR_NOT_ALL_ASSIGNED = 1300


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Luid", LUID), ("Attributes", wintypes.DWORD)]


class TOKEN_PRIVILEGES(ctypes.Structure):
    _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Privileges", LUID_AND_ATTRIBUTES * 1)]


def _windows_security_apis():
    """Return Win32 libraries with pointer-safe prototypes for x64 Windows."""
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.LookupPrivilegeValueW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        ctypes.POINTER(LUID),
    ]
    advapi32.LookupPrivilegeValueW.restype = wintypes.BOOL
    advapi32.AdjustTokenPrivileges.argtypes = [
        wintypes.HANDLE,
        wintypes.BOOL,
        ctypes.POINTER(TOKEN_PRIVILEGES),
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    advapi32.AdjustTokenPrivileges.restype = wintypes.BOOL
    return advapi32, kernel32


def enable_shutdown_privilege() -> None:
    if os.name != "nt":
        raise OSError("SE_SHUTDOWN_NAME sólo existe en Windows")
    advapi32, kernel32 = _windows_security_apis()
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, ctypes.byref(token)
    ):
        raise OSError(ctypes.get_last_error(), "OpenProcessToken falló")
    try:
        luid = LUID()
        if not advapi32.LookupPrivilegeValueW(None, "SeShutdownPrivilege", ctypes.byref(luid)):
            raise OSError(ctypes.get_last_error(), "LookupPrivilegeValueW falló")
        tp = TOKEN_PRIVILEGES()
        tp.PrivilegeCount = 1
        tp.Privileges[0].Luid = luid
        tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED
        ctypes.set_last_error(0)
        if not advapi32.AdjustTokenPrivileges(token, False, ctypes.byref(tp), 0, None, None):
            raise OSError(ctypes.get_last_error(), "AdjustTokenPrivileges falló")
        err = ctypes.get_last_error()
        if err == ERROR_NOT_ALL_ASSIGNED:
            raise PermissionError("El proceso no posee SeShutdownPrivilege")
    finally:
        kernel32.CloseHandle(token)


def suspend_windows(*, hibernate: bool = False) -> None:
    enable_shutdown_privilege()
    powrprof = ctypes.WinDLL("PowrProf", use_last_error=True)
    powrprof.SetSuspendState.argtypes = [ctypes.c_bool, ctypes.c_bool, ctypes.c_bool]
    powrprof.SetSuspendState.restype = ctypes.c_bool
    if not powrprof.SetSuspendState(bool(hibernate), False, False):
        raise OSError(ctypes.get_last_error(), "SetSuspendState falló")
