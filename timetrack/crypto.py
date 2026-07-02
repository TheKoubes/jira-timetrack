"""At-rest protection of secrets (API tokens) via Windows DPAPI.

Tokens are stored as ``DPAPI:<base64>`` — encrypted to the current Windows
user, so the file can't be copied to another account/machine and reused.
Reading falls back to plaintext, so tokens saved before encryption keep
working until the next save re-encrypts them.
"""

import base64
import ctypes
from ctypes import wintypes
from pathlib import Path

PREFIX = "DPAPI:"

crypt32 = ctypes.windll.crypt32
kernel32 = ctypes.windll.kernel32


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _in_blob(data: bytes) -> _Blob:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))


def _take(blob: _Blob) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        kernel32.LocalFree(blob.pbData)


def protect(text: str) -> bytes:
    blob_in = _in_blob(text.encode("utf-8"))
    blob_out = _Blob()
    if not crypt32.CryptProtectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise OSError("CryptProtectData selhalo")
    return _take(blob_out)


def unprotect(blob: bytes) -> str:
    blob_in = _in_blob(blob)
    blob_out = _Blob()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise OSError("CryptUnprotectData selhalo")
    return _take(blob_out).decode("utf-8")


def read_secret(path: Path) -> str:
    """Read a token from *path*, decrypting DPAPI or returning plaintext."""
    if not path.exists():
        return ""
    raw = path.read_text(encoding="utf-8").strip()
    if raw.startswith(PREFIX):
        return unprotect(base64.b64decode(raw[len(PREFIX):]))
    return raw


def write_secret(path: Path, token: str) -> None:
    """Encrypt *token* with DPAPI and write it to *path* (empty = remove)."""
    token = token.strip()
    if not token:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = PREFIX + base64.b64encode(protect(token)).decode("ascii")
    path.write_text(encoded, encoding="utf-8")
