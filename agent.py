from __future__ import annotations

import ctypes
import os
import threading
import time
import uuid
from ctypes import wintypes

from mijialamp.config import load_config
from mijialamp.ipc import IPCError, PipeClient
from mijialamp.locking import FileLock
from mijialamp.logging_setup import configure_logging
from mijialamp.paths import AGENT_LOCK_PATH, CONFIG_PATH, LOG_DIR, ensure_agent_dirs

WM_POWERBROADCAST = 0x0218
WM_WTSSESSION_CHANGE = 0x02B1
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
PBT_APMSUSPEND = 0x0004
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMEAUTOMATIC = 0x0012
PBT_POWERSETTINGCHANGE = 0x8013
DEVICE_NOTIFY_WINDOW_HANDLE = 0
NOTIFY_FOR_THIS_SESSION = 0

WTS_CONSOLE_CONNECT = 0x1
WTS_CONSOLE_DISCONNECT = 0x2
WTS_REMOTE_CONNECT = 0x3
WTS_REMOTE_DISCONNECT = 0x4
WTS_SESSION_LOGON = 0x5
WTS_SESSION_LOGOFF = 0x6
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8

GUID_SESSION_DISPLAY_STATUS = "2B84C20E-AD23-4DDF-93DB-05FFBD7EFCA5"
GUID_SESSION_USER_PRESENCE = "3C0F4548-C03F-4C4D-B9F2-237EDE686376"

HANDLE = wintypes.HANDLE
HWND = wintypes.HWND
UINT = wintypes.UINT
DWORD = wintypes.DWORD
WORD = wintypes.WORD
BOOL = wintypes.BOOL
WPARAM = wintypes.WPARAM
LPARAM = wintypes.LPARAM
LONG = wintypes.LONG
LPCWSTR = wintypes.LPCWSTR
HINSTANCE = getattr(wintypes, "HINSTANCE", HANDLE)
HICON = getattr(wintypes, "HICON", HANDLE)
HCURSOR = getattr(wintypes, "HCURSOR", HANDLE)
HBRUSH = getattr(wintypes, "HBRUSH", HANDLE)
HMENU = getattr(wintypes, "HMENU", HANDLE)
HMODULE = getattr(wintypes, "HMODULE", HANDLE)
LPVOID = getattr(wintypes, "LPVOID", ctypes.c_void_p)
ATOM = getattr(wintypes, "ATOM", WORD)
LRESULT = ctypes.c_ssize_t


if hasattr(wintypes, "MSG"):
    MSG = wintypes.MSG
else:
    class POINT(ctypes.Structure):
        _fields_ = [("x", LONG), ("y", LONG)]

    class MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", HWND), ("message", UINT), ("wParam", WPARAM),
            ("lParam", LPARAM), ("time", DWORD), ("pt", POINT),
        ]


class GUID(ctypes.Structure):
    _fields_ = [("Data1", DWORD), ("Data2", WORD), ("Data3", WORD), ("Data4", ctypes.c_ubyte * 8)]


class POWERBROADCAST_SETTING(ctypes.Structure):
    _fields_ = [("PowerSetting", GUID), ("DataLength", DWORD), ("Data", ctypes.c_ubyte * 1)]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", UINT), ("lpfnWndProc", ctypes.c_void_p), ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int), ("hInstance", HINSTANCE), ("hIcon", HICON),
        ("hCursor", HCURSOR), ("hbrBackground", HBRUSH), ("lpszMenuName", LPCWSTR),
        ("lpszClassName", LPCWSTR),
    ]


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", UINT), ("dwTime", DWORD)]


def make_guid(value: str) -> GUID:
    u = uuid.UUID(value)
    return GUID(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))


def _guid_text(guid: GUID) -> str:
    return str(uuid.UUID(bytes_le=bytes(ctypes.string_at(ctypes.byref(guid), 16))))


class TrayUI:
    def __init__(self, cfg: dict, client, log, on_exit, *, backend_label: str = "Service"):
        self.cfg = cfg
        self.backend_label = backend_label
        self.client = client
        self.log = log
        self.on_exit = on_exit
        self.icon = None
        self._stop = threading.Event()
        self._last_error_key = None
        self._poll_failures = 0
        self._last_poll_warning_at = 0.0
        self._service_down_notified = False

    @staticmethod
    def _image(mode: str = "auto"):
        from PIL import Image, ImageDraw

        fills = {
            "on": (245, 196, 66, 255),
            "off": (145, 145, 145, 255),
            "paused": (87, 148, 242, 255),
            "error": (220, 72, 72, 255),
            "auto": (245, 196, 66, 255),
        }
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse((15, 7, 49, 41), fill=fills.get(mode, fills["auto"]), outline=(90, 90, 90, 255), width=3)
        draw.rounded_rectangle((23, 37, 41, 54), radius=3, fill=(120, 120, 120, 255))
        draw.rectangle((25, 53, 39, 58), fill=(80, 80, 80, 255))
        return img

    def _call(self, command: str, **kwargs):
        try:
            return self.client.request(command, timeout=6, **kwargs)
        except Exception as exc:
            self.log.error("Tray action %s failed: %s", command, exc)
            if self.icon:
                try:
                    self.icon.notify(str(exc), "MijiaLamp")
                except Exception:
                    pass
            return None

    def _call_async(self, command: str, **kwargs) -> None:
        threading.Thread(
            target=self._call,
            args=(command,),
            kwargs=kwargs,
            name=f"MijiaLampTray-{command}",
            daemon=True,
        ).start()

    def start(self):
        if not bool(self.cfg.get("tray_enabled", True)):
            return
        try:
            import pystray
        except Exception as exc:
            self.log.warning("Tray deshabilitado: pystray no disponible: %s", exc)
            return

        menu = pystray.Menu(
            pystray.MenuItem("Encender", lambda *_: self._call_async("manual-on")),
            pystray.MenuItem("Apagar", lambda *_: self._call_async("manual-off")),
            pystray.MenuItem("Automático", lambda *_: self._call_async("resume-automation")),
            pystray.MenuItem("Pausar 1 hora", lambda *_: self._call_async("pause", seconds=3600)),
            pystray.MenuItem("Pausar hasta mañana", lambda *_: self._call_async("pause-until-tomorrow")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Sincronizar",
                lambda *_: self._call_async("sync", reason="tray-sync", force=True),
            ),
            pystray.MenuItem("Abrir logs", lambda *_: os.startfile(str(LOG_DIR))),
            pystray.MenuItem("Abrir configuración", lambda *_: os.startfile(str(CONFIG_PATH))),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Salir del agente", lambda *_: self.on_exit()),
        )
        self.icon = pystray.Icon("MijiaLamp", self._image("auto"), "MijiaLamp", menu)
        try:
            self.icon.run_detached()
        except Exception:
            threading.Thread(target=self.icon.run, name="MijiaLampTray", daemon=True).start()
        threading.Thread(target=self._poll, name="MijiaLampTrayStatus", daemon=True).start()

    def _poll(self):
        while not self._stop.wait(5):
            if not self.icon:
                return
            try:
                result = self.client.request("status", timeout=2, physical=False)
                if self._poll_failures:
                    self.log.info("Tray recuperó comunicación con %s", self.backend_label)
                self._poll_failures = 0
                self._service_down_notified = False
                state = result.get("state", {})
                desired = result.get("desired", {})
                physical = state.get("last_physical") or {}
                paused = float(state.get("automation_paused_until", 0) or 0) != 0
                err = state.get("last_error")
                power = str(physical.get("power") or desired.get("power") or "?").lower()
                title = f"MijiaLamp · {power.upper()}"
                if power == "on":
                    if physical.get("kelvin"):
                        title += f" · {physical['kelvin']}K"
                    if physical.get("brightness") is not None:
                        title += f" · {physical['brightness']}%"
                if desired.get("profile"):
                    title += f" · {desired['profile']}"
                if paused:
                    title += " · PAUSADO"
                self.icon.title = title[:127]
                mode = "error" if err else ("paused" if paused else ("on" if power == "on" else "off"))
                try:
                    self.icon.icon = self._image(mode)
                except Exception:
                    pass

                if bool(self.cfg.get("notifications_enabled", True)):
                    first = float(state.get("first_failure_at", 0) or 0)
                    threshold = float(self.cfg.get("notify_after_failure_seconds", 900))
                    if err and first and time.time() - first >= threshold:
                        key = (err.get("at"), err.get("type"), err.get("message"))
                        if key != self._last_error_key:
                            self._last_error_key = key
                            self.icon.notify(str(err.get("message", "Error persistente")), "MijiaLamp necesita atención")
            except Exception as exc:
                self._poll_failures += 1
                now = time.monotonic()
                if self._poll_failures == 1 or now - self._last_poll_warning_at >= 60:
                    self._last_poll_warning_at = now
                    self.log.warning("Tray no puede consultar %s: %s", self.backend_label, exc)
                if self.icon:
                    try:
                        self.icon.title = f"MijiaLamp · {self.backend_label.upper()} OFFLINE"
                        self.icon.icon = self._image("error")
                        if (
                            bool(self.cfg.get("notifications_enabled", True))
                            and self._poll_failures >= 6
                            and not self._service_down_notified
                        ):
                            self._service_down_notified = True
                            self.icon.notify(
                                f"{self.backend_label} no responde desde hace ~30 segundos.",
                                "MijiaLamp necesita atención",
                            )
                    except Exception:
                        # Tray backends are best-effort; file/Event Viewer logging remains authoritative.
                        pass

    def stop(self):
        self._stop.set()
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass


class LampAgent:
    def __init__(
        self,
        *,
        client=None,
        cfg: dict | None = None,
        log=None,
        backend_label: str = "Service",
        suspend_handler=None,
    ):
        ensure_agent_dirs()
        self.cfg = cfg or load_config()
        self.log = log or configure_logging("agent", self.cfg, console=False, event_log=True)
        self.client = client or PipeClient()
        self.backend_label = backend_label
        self.suspend_handler = suspend_handler
        self.guard = threading.RLock()
        self.pending_off_generation = 0
        self.suppress_off_until = time.monotonic() + float(self.cfg.get("suppress_off_after_start_seconds", 10))
        self.last_display_state = None
        self.last_display_event_at = 0.0
        self.current_display_on: bool | None = None
        self.current_session_locked: bool | None = None
        self.current_presence: str | None = None
        self.stop_event = threading.Event()
        self._heartbeat_failures = 0
        self.hwnd = None
        self.tray = TrayUI(
            self.cfg, self.client, self.log, self.request_exit, backend_label=self.backend_label
        )

    def _run_async(self, label, func):
        def worker():
            try:
                func()
            except Exception as exc:
                self.log.error("Acción async %s falló: %s", label, exc, exc_info=True)
        threading.Thread(target=worker, name=f"MijiaLamp-{label}", daemon=True).start()

    def _request(self, command: str, *, timeout: float = 4, **params):
        return self.client.request(command, timeout=timeout, **params)

    def _notify(self, command: str, *, timeout: float = 0.5, **params) -> None:
        self.client.notify(command, timeout=timeout, **params)

    def _debounced(self, state: str) -> bool:
        now = time.monotonic()
        with self.guard:
            duplicate = self.last_display_state == state and now - self.last_display_event_at < float(
                self.cfg.get("display_event_debounce_seconds", 2.0)
            )
            self.last_display_state = state
            self.last_display_event_at = now
        if duplicate:
            self.log.info("Evento display %s duplicado; coalescido", state)
        return duplicate

    def display_on(self, source: str):
        if self._debounced("on"):
            return
        with self.guard:
            self.pending_off_generation += 1
            self.current_display_on = True
        self._run_async(
            "display-on",
            lambda: self._notify("display", on=True, pending=False, event=f"display-on:{source}"),
        )

    def display_off(self, source: str):
        if self._debounced("off"):
            return
        now = time.monotonic()
        with self.guard:
            if now < self.suppress_off_until:
                self.log.info("Display OFF ignorado dentro del período de gracia")
                return
            self.pending_off_generation += 1
            generation = self.pending_off_generation
            self.current_display_on = False
        self._run_async(
            "display-off-pending",
            lambda: self._notify("display", on=False, pending=True, event=f"display-off-pending:{source}"),
        )

        def confirm():
            time.sleep(float(self.cfg.get("display_off_confirm_seconds", 5)))
            with self.guard:
                if generation != self.pending_off_generation or time.monotonic() < self.suppress_off_until:
                    return
            self._notify("display", on=False, pending=False, event=f"display-off:{source}")

        self._run_async("display-off-confirm", confirm)

    def suspend(self):
        with self.guard:
            self.pending_off_generation += 1

        # Portable runs the controller in this process, so do the critical OFF directly
        # instead of queueing it behind Named Pipe workers. This is intentionally
        # synchronous: Windows may tear Wi-Fi down immediately after PBT_APMSUSPEND.
        if self.suspend_handler is not None:
            try:
                self.suspend_handler()
            except Exception as exc:
                self.log.warning("Suspend OFF crítico no pudo completarse: %s", exc)
            return

        # Service mode has an independent SERVICE_CONTROL_POWEREVENT path. The agent's
        # one-way hint is only a fast backup; attach a short monotonic deadline so a
        # message queued before sleep can never execute as a stale OFF after Resume.
        deadline = time.monotonic() + float(self.cfg.get("suspend_event_deadline_seconds", 0.75))
        try:
            self._notify(
                "suspend",
                timeout=0.20,
                not_after_monotonic=deadline,
                source="interactive-agent",
            )
        except Exception as exc:
            self.log.warning("Suspend OFF vía agente no pudo encolarse: %s", exc)

    def resume(self, automatic: bool):
        with self.guard:
            self.pending_off_generation += 1
            self.suppress_off_until = time.monotonic() + float(self.cfg.get("suppress_off_after_resume_seconds", 10))
        command = "resume-auto" if automatic else "resume-user"
        self._run_async(command, lambda: self._notify(command, timeout=0.5))

    def session_change(self, code: int):
        if code == WTS_SESSION_LOCK:
            with self.guard:
                self.pending_off_generation += 1
                self.current_session_locked = True
            self._run_async(
                "session-lock",
                lambda: self._notify("session", locked=True, event="session-lock"),
            )
        elif code in (WTS_SESSION_UNLOCK, WTS_SESSION_LOGON, WTS_CONSOLE_CONNECT):
            with self.guard:
                self.current_session_locked = False
                self.current_presence = "present"
            self._run_async(
                "session-unlock",
                lambda: self._notify("session", locked=False, event="session-unlock"),
            )
            # WTS unlock/logon is also a concrete local-presence signal. Publish it now
            # instead of waiting up to one heartbeat interval for presence policy to recover.
            self._run_async(
                "session-presence",
                lambda: self._notify("presence", presence="present"),
            )
        elif code == WTS_REMOTE_CONNECT:
            # A remote user is not physical presence at the lamp. When remote sessions
            # are explicitly allowed, treat the session as active instead.
            ignore_remote = bool(self.cfg.get("ignore_remote_sessions", True))
            with self.guard:
                self.current_session_locked = True if ignore_remote else False
                self.current_presence = "not_present" if ignore_remote else "present"
            self._run_async(
                "remote-connect",
                lambda: self._notify(
                    "session",
                    locked=ignore_remote,
                    event="remote-connect",
                ),
            )
            self._run_async(
                "remote-presence",
                lambda: self._notify(
                    "presence",
                    presence="not_present" if ignore_remote else "present",
                ),
            )
        elif code in (
            WTS_SESSION_LOGOFF,
            WTS_REMOTE_DISCONNECT,
            WTS_CONSOLE_DISCONNECT,
        ):
            with self.guard:
                self.current_session_locked = True
                self.current_presence = "not_present"
            self._run_async(
                "session-away",
                lambda: self._notify("session", locked=True, event="session-away"),
            )
            self._run_async(
                "away-presence",
                lambda: self._notify("presence", presence="not_present"),
            )

    def presence(self, value: int):
        mapping = {0: "present", 1: "not_present", 2: "inactive"}
        if value in mapping:
            presence = mapping[value]
            with self.guard:
                self.current_presence = presence
            self._run_async("presence", lambda: self._notify("presence", presence=presence))

    def _heartbeat_loop(self):
        while not self.stop_event.wait(15):
            with self.guard:
                display = self.current_display_on
                locked = self.current_session_locked
                presence = self.current_presence
            try:
                self._notify(
                    "agent-heartbeat",
                    timeout=0.5,
                    display_on=display,
                    session_locked=locked,
                    user_presence=presence,
                )
                if self._heartbeat_failures:
                    self.log.info("Heartbeat recuperó comunicación con MijiaLampService")
                self._heartbeat_failures = 0
            except Exception as exc:
                # A service restart is expected to create a brief gap; log the first miss and
                # then rate-limit to one warning per minute instead of hiding it or spamming.
                self._heartbeat_failures += 1
                if self._heartbeat_failures == 1 or self._heartbeat_failures % 4 == 0:
                    self.log.warning("Heartbeat no pudo alcanzar el servicio: %s", exc)

    def request_exit(self):
        if self.hwnd:
            try:
                user32 = ctypes.WinDLL("user32", use_last_error=True)
                user32.PostMessageW.argtypes = [HWND, UINT, WPARAM, LPARAM]
                user32.PostMessageW.restype = BOOL
                user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
            except Exception:
                pass

    @staticmethod
    def _recent_user_input(user32, kernel32, *, within_seconds: float = 45.0) -> bool:
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not user32.GetLastInputInfo(ctypes.byref(info)):
            return False
        # dwTime is a 32-bit tick count and wraps. Masking preserves correct short deltas.
        now = int(kernel32.GetTickCount64()) & 0xFFFFFFFF
        elapsed_ms = (now - int(info.dwTime)) & 0xFFFFFFFF
        return elapsed_ms <= int(max(0.0, within_seconds) * 1000)

    @staticmethod
    def _initial_lock_state(user32) -> bool | None:
        DESKTOP_READOBJECTS = 0x0001
        UOI_NAME = 2
        user32.OpenInputDesktop.restype = HANDLE
        desktop = user32.OpenInputDesktop(0, False, DESKTOP_READOBJECTS)
        if not desktop:
            return None
        try:
            needed = DWORD(0)
            user32.GetUserObjectInformationW(desktop, UOI_NAME, None, 0, ctypes.byref(needed))
            if not needed.value:
                return None
            buf = ctypes.create_unicode_buffer(max(2, needed.value // ctypes.sizeof(ctypes.c_wchar)))
            if not user32.GetUserObjectInformationW(desktop, UOI_NAME, buf, needed.value, ctypes.byref(needed)):
                return None
            return buf.value.lower() != "default"
        finally:
            user32.CloseDesktop(desktop)

    def run(self):
        if os.name != "nt":
            raise RuntimeError("agent.py sólo está soportado en Windows")
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
        self.log.info("MijiaLamp agent v3 iniciando")
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HWND, UINT, WPARAM, LPARAM)

        # Explicit prototypes are essential on 64-bit Windows: ctypes otherwise
        # assumes c_int return values and can truncate HWND/HANDLE values.
        user32.DefWindowProcW.argtypes = [HWND, UINT, WPARAM, LPARAM]
        user32.DefWindowProcW.restype = LRESULT
        user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
        user32.RegisterClassW.restype = ATOM
        user32.CreateWindowExW.argtypes = [
            DWORD, LPCWSTR, LPCWSTR, DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, HWND, HMENU, HINSTANCE, LPVOID,
        ]
        user32.CreateWindowExW.restype = HWND
        user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), HWND, UINT, UINT]
        user32.GetMessageW.restype = ctypes.c_int
        user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
        user32.TranslateMessage.restype = BOOL
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
        user32.DispatchMessageW.restype = LRESULT
        user32.DestroyWindow.argtypes = [HWND]
        user32.DestroyWindow.restype = BOOL
        user32.PostQuitMessage.argtypes = [ctypes.c_int]
        user32.PostQuitMessage.restype = None
        user32.RegisterPowerSettingNotification.argtypes = [
            HANDLE, ctypes.POINTER(GUID), DWORD
        ]
        user32.RegisterPowerSettingNotification.restype = HANDLE
        user32.UnregisterPowerSettingNotification.argtypes = [HANDLE]
        user32.UnregisterPowerSettingNotification.restype = BOOL
        user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        user32.GetSystemMetrics.restype = ctypes.c_int
        user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
        user32.GetLastInputInfo.restype = BOOL
        user32.OpenInputDesktop.argtypes = [DWORD, BOOL, DWORD]
        user32.OpenInputDesktop.restype = HANDLE
        user32.GetUserObjectInformationW.argtypes = [
            HANDLE, ctypes.c_int, LPVOID, DWORD, ctypes.POINTER(DWORD)
        ]
        user32.GetUserObjectInformationW.restype = BOOL
        user32.CloseDesktop.argtypes = [HANDLE]
        user32.CloseDesktop.restype = BOOL

        kernel32.GetModuleHandleW.argtypes = [LPCWSTR]
        kernel32.GetModuleHandleW.restype = HMODULE
        kernel32.GetTickCount64.argtypes = []
        kernel32.GetTickCount64.restype = ctypes.c_ulonglong

        wtsapi32.WTSRegisterSessionNotification.argtypes = [HWND, DWORD]
        wtsapi32.WTSRegisterSessionNotification.restype = BOOL
        wtsapi32.WTSUnRegisterSessionNotification.argtypes = [HWND]
        wtsapi32.WTSUnRegisterSessionNotification.restype = BOOL

        if bool(self.cfg.get("ignore_remote_sessions", True)) and user32.GetSystemMetrics(0x1000):
            self.log.info("Sesión remota detectada; agente interactivo omitido por configuración")
            return

        def wndproc(hwnd, msg, wparam, lparam):
            try:
                if msg == WM_POWERBROADCAST:
                    if wparam == PBT_APMSUSPEND:
                        self.log.info("Windows event: suspend")
                        self.suspend()
                        return 1
                    if wparam == PBT_APMRESUMESUSPEND:
                        self.log.info("Windows event: resume-user")
                        self.resume(False)
                        return 1
                    if wparam == PBT_APMRESUMEAUTOMATIC:
                        self.log.info("Windows event: resume-automatic")
                        self.resume(True)
                        return 1
                    if wparam == PBT_POWERSETTINGCHANGE and lparam:
                        setting = ctypes.cast(lparam, ctypes.POINTER(POWERBROADCAST_SETTING)).contents
                        value = int(setting.Data[0])
                        source = _guid_text(setting.PowerSetting).lower()
                        self.log.info("Power setting %s value=%s", source, value)
                        if source == GUID_SESSION_DISPLAY_STATUS.lower():
                            if value == 0:
                                self.display_off(source)
                            elif value in (1, 2):
                                self.display_on(source)
                        elif source == GUID_SESSION_USER_PRESENCE.lower():
                            self.presence(value)
                        return 1
                if msg == WM_WTSSESSION_CHANGE:
                    self.log.info("WTS session event=%s session=%s", int(wparam), int(lparam))
                    self.session_change(int(wparam))
                    return 0
                if msg == WM_CLOSE:
                    user32.DestroyWindow(hwnd)
                    return 0
                if msg == WM_DESTROY:
                    user32.PostQuitMessage(0)
                    return 0
            except Exception as exc:
                self.log.error("Error procesando evento Windows: %s", exc, exc_info=True)
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        wndproc_ref = WNDPROC(wndproc)
        hinst = kernel32.GetModuleHandleW(None)
        class_name = "MijiaLampV3HiddenWindow"
        wc = WNDCLASSW()
        wc.lpfnWndProc = ctypes.cast(wndproc_ref, ctypes.c_void_p).value
        wc.hInstance = hinst
        wc.lpszClassName = class_name
        atom = user32.RegisterClassW(ctypes.byref(wc))
        if not atom and ctypes.get_last_error() != 1410:
            raise OSError(ctypes.get_last_error(), "RegisterClassW falló")
        hwnd = user32.CreateWindowExW(0, class_name, class_name, 0, 0, 0, 0, 0, 0, 0, hinst, None)
        if not hwnd:
            raise OSError(ctypes.get_last_error(), "CreateWindowExW falló")
        self.hwnd = hwnd

        registrations = []
        for guid_text, required in (
            (GUID_SESSION_DISPLAY_STATUS, True),
            (GUID_SESSION_USER_PRESENCE, False),
        ):
            guid = make_guid(guid_text)
            handle = user32.RegisterPowerSettingNotification(
                hwnd, ctypes.byref(guid), DEVICE_NOTIFY_WINDOW_HANDLE
            )
            if not handle:
                error = ctypes.get_last_error()
                if required:
                    raise OSError(error, f"No pude registrar {guid_text}")
                self.log.warning(
                    "User Presence no disponible (error=%s); continúo con Display + WTS",
                    error,
                )
                continue
            registrations.append((guid, handle))

        if not wtsapi32.WTSRegisterSessionNotification(hwnd, NOTIFY_FOR_THIS_SESSION):
            self.log.warning("WTSRegisterSessionNotification falló: %s", ctypes.get_last_error())

        self.tray.start()
        locked = self._initial_lock_state(user32)
        recent_input = self._recent_user_input(user32, kernel32)
        # Do not blindly invent display=ON when the agent starts. A recent local input event
        # is a real interactive signal and is only used as the one-time initial hint.
        inferred_display = True if locked is False and recent_input else None
        inferred_presence = "present" if locked is False and recent_input else None
        with self.guard:
            self.current_session_locked = locked
            self.current_display_on = inferred_display
            self.current_presence = inferred_presence
        self._run_async(
            "agent-start",
            lambda: self._notify(
                "agent-start",
                session_locked=locked,
                display_on=inferred_display,
                user_presence=inferred_presence,
            ),
        )

        threading.Thread(
            target=self._heartbeat_loop, name="MijiaLampAgentHeartbeat", daemon=True
        ).start()

        msg = MSG()
        while user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        self.stop_event.set()
        try:
            wtsapi32.WTSUnRegisterSessionNotification(hwnd)
        except Exception:
            pass
        for _guid, handle in registrations:
            try:
                user32.UnregisterPowerSettingNotification(handle)
            except Exception:
                pass
        self.tray.stop()
        self.log.info("MijiaLamp agent detenido")


def main() -> int:
    ensure_agent_dirs()
    cfg = load_config()
    log = configure_logging("agent", cfg, console=False, event_log=True)
    try:
        with FileLock(AGENT_LOCK_PATH, timeout=0.1):
            LampAgent().run()
        return 0
    except IPCError as exc:
        log.error("El servicio no está disponible: %s", exc)
        return 3
    except Exception as exc:
        log.error("Agent terminó con error: %s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
