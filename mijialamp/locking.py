import contextlib
import sys
import time
from pathlib import Path
from typing import BinaryIO

from .errors import LockTimeoutError


class FileLock:
    """Small cross-process lock using the platform file-locking primitive."""

    def __init__(self, path: Path, timeout: float = 10.0, poll: float = 0.05):
        self.path = Path(path)
        self.timeout = float(timeout)
        self.poll = float(poll)
        self._fh: BinaryIO | None = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + max(0.0, self.timeout)
        # The handle stays open until release() so the OS lock remains held.
        fh = open(self.path, "a+b")  # noqa: SIM115
        self._fh = fh
        if fh.tell() == 0:
            fh.write(b"0")
            fh.flush()
        while True:
            try:
                self._lock_now()
                return self
            except OSError as exc:
                if time.monotonic() >= deadline:
                    self.release()
                    raise LockTimeoutError(f"Timeout acquiring lock: {self.path}") from exc
                time.sleep(self.poll)

    def _lock_now(self):
        fh = self._fh
        if fh is None:
            raise RuntimeError("Lock file is not open")
        fh.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def release(self):
        fh = self._fh
        if fh is None:
            return
        try:
            fh.seek(0)
            if sys.platform == "win32":
                import msvcrt

                with contextlib.suppress(OSError):
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                with contextlib.suppress(OSError):
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()
            self._fh = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc, tb):
        self.release()
