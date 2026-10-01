from __future__ import annotations

import base64
import contextlib
import ctypes
import json
import os
import re
from ctypes import wintypes
from pathlib import Path

from .errors import SecretError
from .paths import TOKEN_PATH
from .util import atomic_write_json

_TOKEN_RE = re.compile(r"^[0-9a-fA-F]{32}$")
# Keep the v2 entropy for seamless migration of existing DPAPI blobs.
# Changing this value would make already-installed tokens unreadable.
_ENTROPY = b"MijiaLamp-v2-token"
_CRYPTPROTECT_LOCAL_MACHINE = 0x4
SCOPE_CURRENT_USER = "current-user"
SCOPE_LOCAL_MACHINE = "local-machine"
_LEGACY_MACHINE_SCOPE = "dpapi-local-machine-service-owned"


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes):
    buf = ctypes.create_string_buffer(data)
    return DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte))), buf


def _require_windows() -> None:
    if os.name != "nt":
        raise SecretError("DPAPI sólo está disponible en Windows")


def _normalize_scope(scope: str) -> str:
    value = str(scope).strip().lower()
    if value == _LEGACY_MACHINE_SCOPE:
        return SCOPE_LOCAL_MACHINE
    if value not in {SCOPE_CURRENT_USER, SCOPE_LOCAL_MACHINE}:
        raise SecretError(f"Scope DPAPI no soportado: {scope!r}")
    return value


def _protect(raw: bytes, *, scope: str) -> bytes:
    _require_windows()
    normalized = _normalize_scope(scope)
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(DATA_BLOB),
        wintypes.LPCWSTR,
        ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DATA_BLOB),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    in_blob, in_buf = _blob(raw)
    entropy_blob, entropy_buf = _blob(_ENTROPY)
    out_blob = DATA_BLOB()
    flags = _CRYPTPROTECT_LOCAL_MACHINE if normalized == SCOPE_LOCAL_MACHINE else 0
    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        "MijiaLamp token",
        ctypes.byref(entropy_blob),
        None,
        None,
        flags,
        ctypes.byref(out_blob),
    )
    # Keep buffers alive until CryptProtectData returns.
    _ = in_buf, entropy_buf
    if not ok:
        raise SecretError(f"CryptProtectData falló: {ctypes.get_last_error()}")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out_blob.pbData, ctypes.c_void_p))


def _unprotect(cipher: bytes, *, scope: str) -> bytes:
    _require_windows()
    normalized = _normalize_scope(scope)
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p,
        ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    in_blob, in_buf = _blob(cipher)
    entropy_blob, entropy_buf = _blob(_ENTROPY)
    out_blob = DATA_BLOB()
    # CryptUnprotectData does not require the same LOCAL_MACHINE flag. The scope is
    # encoded in the protected blob itself; we still validate/retain it in metadata so
    # portable and service installations cannot silently mix secret ownership models.
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        ctypes.byref(entropy_blob),
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    _ = normalized, in_buf, entropy_buf
    if not ok:
        raise SecretError(f"CryptUnprotectData falló: {ctypes.get_last_error()}")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out_blob.pbData, ctypes.c_void_p))


def validate_token(token: str) -> str:
    token = str(token).strip()
    if not _TOKEN_RE.fullmatch(token):
        raise SecretError("El token debe contener exactamente 32 caracteres hexadecimales")
    return token.lower()


def token_metadata(path: Path = TOKEN_PATH) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        if not isinstance(payload, dict):
            raise ValueError("secret root is not an object")
        scope = _normalize_scope(str(payload.get("scope", _LEGACY_MACHINE_SCOPE)))
        version = int(payload.get("version", 1))
        return {"version": version, "scope": scope}
    except FileNotFoundError as exc:
        raise SecretError("No hay token configurado") from exc
    except SecretError:
        raise
    except Exception as exc:
        raise SecretError("El metadata del token almacenado es inválido") from exc


def token_exists(path: Path = TOKEN_PATH, *, expected_scope: str | None = None) -> bool:
    if not Path(path).is_file():
        return False
    if expected_scope is None:
        return True
    try:
        return token_metadata(path)["scope"] == _normalize_scope(expected_scope)
    except SecretError:
        return False


def store_token(
    token: str,
    path: Path = TOKEN_PATH,
    *,
    scope: str = SCOPE_LOCAL_MACHINE,
) -> None:
    token = validate_token(token)
    normalized = _normalize_scope(scope)
    encrypted = _protect(token.encode("ascii"), scope=normalized)
    payload = {
        "version": 3,
        "scope": normalized,
        "ciphertext_b64": base64.b64encode(encrypted).decode("ascii"),
    }
    atomic_write_json(path, payload)


def load_token(
    path: Path = TOKEN_PATH,
    *,
    expected_scope: str | None = None,
) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        scope = _normalize_scope(str(payload.get("scope", _LEGACY_MACHINE_SCOPE)))
        if expected_scope is not None and scope != _normalize_scope(expected_scope):
            raise SecretError(
                f"El token usa scope DPAPI {scope!r}; se esperaba {_normalize_scope(expected_scope)!r}"
            )
        cipher = base64.b64decode(payload["ciphertext_b64"], validate=True)
        token = _unprotect(cipher, scope=scope).decode("ascii")
        return validate_token(token)
    except SecretError:
        raise
    except FileNotFoundError as exc:
        raise SecretError("No hay token configurado. Ejecutá el importador correspondiente") from exc
    except Exception as exc:
        raise SecretError("No se pudo leer/descifrar el token almacenado") from exc


def migrate_token_scope(
    *,
    path: Path = TOKEN_PATH,
    target_scope: str,
) -> bool:
    """Re-encrypt an existing token under another DPAPI scope.

    This is intentionally explicit. Service installation may promote a portable
    CurrentUser blob to LocalMachine while still running under that same user during
    the elevated setup phase. It never prints or returns the token.
    """
    target = _normalize_scope(target_scope)
    if not token_exists(path):
        return False
    meta = token_metadata(path)
    if meta["scope"] == target:
        return False
    token = load_token(path)
    store_token(token, path, scope=target)
    return True


def clear_token(path: Path = TOKEN_PATH) -> None:
    with contextlib.suppress(FileNotFoundError):
        Path(path).unlink()
