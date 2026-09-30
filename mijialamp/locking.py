import os
import time
from pathlib import Path

from .errors import LockTimeoutError


class FileLock:
    """Small cross-process lock using the platform file-locking primitive."""

    def __init__(self, path: Path, timeout: float = 10.0, poll: float = 0.05):
        self.path = Path(path)
        self.timeout = float(timeout)
        self.poll = float(poll)
        self._fh = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + max(0.0, self.timeout)
        self._fh = open(self.path, "a+b")
        if self._fh.tell() == 0:
            self._fh.write(b"0")
            self._fh.flush()
        while True:
            try:
                self._lock_now()
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    self.release()
                    raise LockTimeoutError(f"Timeout acquiring lock: {self.path}")
                time.sleep(self.poll)

    def _lock_now(self):
        self._fh.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def release(self):
        if self._fh is None:
            return
        try:
            self._fh.seek(0)
            if os.name == "nt":
                import msvcrt

                try:
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl

                try:
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
        finally:
            self._fh.close()
            self._fh = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc, tb):
        self.release()
