from __future__ import annotations

import json
import os
import threading
from typing import Callable

from .errors import MijiaLampError

PIPE_NAME = r"\\.\pipe\MijiaLamp-v3"
PORTABLE_PIPE_NAME = r"\\.\pipe\MijiaLamp-Portable-v3"
_MAX_MESSAGE = 64 * 1024
_PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
_DEFAULT_MAX_CLIENTS = 16


class IPCError(MijiaLampError):
    pass


def build_pipe_sddl(authorized_user_sid: str, server_sid: str | None = None) -> str:
    """Least-privilege ACL for a local pipe.

    Service mode passes its *service SID* so other processes sharing the broad
    ``LocalService`` account are not implicitly trusted. Portable mode needs only the
    exact interactive user plus SYSTEM/Administrators for recovery/diagnostics.
    """
    user_sid = str(authorized_user_sid).strip()
    if not user_sid.upper().startswith("S-1-"):
        raise IPCError("SID autorizado inválido")
    aces = ["(A;;GA;;;SY)", "(A;;GA;;;BA)"]
    if server_sid is not None:
        service_sid = str(server_sid).strip()
        if not service_sid.upper().startswith("S-1-"):
            raise IPCError("Service SID inválido")
        aces.append(f"(A;;GA;;;{service_sid})")
    aces.append(f"(A;;GRGW;;;{user_sid})")
    return "D:P" + "".join(aces)


def encode_message(payload: dict) -> bytes:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    if len(raw) > _MAX_MESSAGE:
        raise IPCError("Mensaje IPC demasiado grande")
    return raw


def decode_message(raw: bytes) -> dict:
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise IPCError("Mensaje IPC inválido") from exc
    if not isinstance(data, dict):
        raise IPCError("El mensaje IPC debe ser un objeto JSON")
    return data


class PipeClient:
    def __init__(self, pipe_name: str = PIPE_NAME):
        self.pipe_name = pipe_name

    def _open(self, timeout: float):
        import win32file
        import win32pipe

        win32pipe.WaitNamedPipe(self.pipe_name, max(1, int(timeout * 1000)))
        handle = win32file.CreateFile(
            self.pipe_name,
            win32file.GENERIC_READ | win32file.GENERIC_WRITE,
            0,
            None,
            win32file.OPEN_EXISTING,
            0,
            None,
        )
        win32pipe.SetNamedPipeHandleState(handle, win32pipe.PIPE_READMODE_MESSAGE, None, None)
        return handle

    def request(self, command: str, *, timeout: float = 5.0, **params):
        """Request/reply IPC.

        ``timeout`` bounds waiting for an available pipe instance. Windows' synchronous
        ``ReadFile`` itself has no per-call timeout, so this method is intended for CLI/tray
        operations where a reply is actually required. Safety-critical power events use
        :meth:`notify`, which writes one small message and never waits for a response.
        """
        if os.name != "nt":
            raise IPCError("Named Pipes de MijiaLamp sólo están disponibles en Windows")
        import win32file

        try:
            handle = self._open(timeout)
            try:
                win32file.WriteFile(handle, encode_message({"command": command, **params}))
                _, raw = win32file.ReadFile(handle, _MAX_MESSAGE)
            finally:
                win32file.CloseHandle(handle)
        except Exception as exc:
            raise IPCError(f"No se pudo comunicar con MijiaLampService: {exc}") from exc

        response = decode_message(raw)
        if not response.get("ok", False):
            raise IPCError(str(response.get("error", "Error IPC desconocido")))
        return response.get("result")

    def notify(self, command: str, *, timeout: float = 0.5, **params) -> None:
        """Send a one-way local event without waiting for the service handler.

        This is used by Suspend/Display/WTS/Presence paths. The message is tiny compared
        with the pipe buffer, so once ``WriteFile`` completes the service owns the event;
        the caller can immediately return to Windows' message loop.
        """
        if os.name != "nt":
            raise IPCError("Named Pipes de MijiaLamp sólo están disponibles en Windows")
        import win32file

        try:
            handle = self._open(timeout)
            try:
                win32file.WriteFile(
                    handle,
                    encode_message({"command": command, "_oneway": True, **params}),
                )
            finally:
                win32file.CloseHandle(handle)
        except Exception as exc:
            raise IPCError(f"No se pudo notificar a MijiaLampService: {exc}") from exc


class PipeServer:
    """Local authenticated request/reply pipe, concurrent across client connections."""

    def __init__(
        self,
        handler: Callable[[dict], object],
        *,
        authorized_user_sid: str,
        pipe_name: str = PIPE_NAME,
        logger=None,
        max_clients: int = _DEFAULT_MAX_CLIENTS,
        server_sid: str | None = None,
    ):
        if int(max_clients) < 1:
            raise IPCError("max_clients debe ser >= 1")
        self.handler = handler
        self.authorized_user_sid = authorized_user_sid
        self.pipe_name = pipe_name
        self.log = logger
        self.max_clients = int(max_clients)
        self.server_sid = server_sid
        self._stop = threading.Event()
        self._slots = threading.BoundedSemaphore(self.max_clients)

    def stop(self) -> None:
        self._stop.set()
        if os.name == "nt":
            try:
                PipeClient(self.pipe_name).notify("_wake", timeout=0.2)
            except Exception:
                pass

    def _security_attributes(self):
        import pywintypes
        import win32security

        # SYSTEM/Administrators plus (in Service mode) the exact Service SID: full.
        # Exactly the installer-selected interactive user: read/write. No broad
        # LocalService or Interactive Users ACE.
        sddl = build_pipe_sddl(self.authorized_user_sid, self.server_sid)
        sd = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
            sddl, win32security.SDDL_REVISION_1
        )
        sa = pywintypes.SECURITY_ATTRIBUTES()
        sa.SECURITY_DESCRIPTOR = sd
        return sa

    @staticmethod
    def _close(handle) -> None:
        import win32file
        import win32pipe

        try:
            win32pipe.DisconnectNamedPipe(handle)
        except Exception:
            pass
        try:
            win32file.CloseHandle(handle)
        except Exception:
            pass

    def _reject_busy(self, handle) -> None:
        import win32file

        try:
            win32file.WriteFile(
                handle,
                encode_message(
                    {
                        "ok": False,
                        "error": "MijiaLampService está ocupado; reintentá en unos segundos",
                    }
                ),
            )
        except Exception:
            pass
        finally:
            self._close(handle)

    def _serve_connection(self, handle) -> None:
        import win32file

        try:
            _, raw = win32file.ReadFile(handle, _MAX_MESSAGE)
            request = decode_message(raw)
            oneway = bool(request.pop("_oneway", False))
            if request.get("command") == "_wake" and self._stop.is_set():
                result = None
            else:
                result = self.handler(request)
            if not oneway:
                win32file.WriteFile(handle, encode_message({"ok": True, "result": result}))
        except Exception as exc:
            # One-way clients intentionally close after writing; handler errors still belong
            # in the service log, but a broken response pipe is not itself noteworthy.
            if not self._stop.is_set() and self.log:
                self.log.error("IPC command failed: %s", exc, exc_info=True)
            try:
                win32file.WriteFile(
                    handle,
                    encode_message({"ok": False, "error": f"{type(exc).__name__}: {exc}"}),
                )
            except Exception:
                pass
        finally:
            self._close(handle)
            self._slots.release()

    def serve_forever(self) -> None:
        if os.name != "nt":
            raise IPCError("PipeServer sólo está disponible en Windows")
        import win32file
        import win32pipe

        mode = (
            win32pipe.PIPE_TYPE_MESSAGE
            | win32pipe.PIPE_READMODE_MESSAGE
            | win32pipe.PIPE_WAIT
            | getattr(win32pipe, "PIPE_REJECT_REMOTE_CLIENTS", _PIPE_REJECT_REMOTE_CLIENTS)
        )
        while not self._stop.is_set():
            handle = win32pipe.CreateNamedPipe(
                self.pipe_name,
                win32pipe.PIPE_ACCESS_DUPLEX,
                mode,
                win32pipe.PIPE_UNLIMITED_INSTANCES,
                _MAX_MESSAGE,
                _MAX_MESSAGE,
                0,
                self._security_attributes(),
            )
            owned = True
            slot_acquired = False
            try:
                try:
                    win32pipe.ConnectNamedPipe(handle, None)
                except Exception as exc:
                    # ERROR_PIPE_CONNECTED (535) is harmless if a permitted local client won
                    # the race between CreateNamedPipe and ConnectNamedPipe. Any other error
                    # means this pipe instance is not safe to hand to a worker.
                    if getattr(exc, "winerror", None) != 535:
                        raise

                if not self._slots.acquire(blocking=False):
                    self._reject_busy(handle)
                    owned = False
                    continue
                slot_acquired = True

                threading.Thread(
                    target=self._serve_connection,
                    args=(handle,),
                    name="MijiaLampPipeClient",
                    daemon=True,
                ).start()
                # Worker owns both the handle and the semaphore slot from here.
                owned = False
                slot_acquired = False
            finally:
                if slot_acquired:
                    self._slots.release()
                if owned:
                    try:
                        win32file.CloseHandle(handle)
                    except Exception:
                        pass
