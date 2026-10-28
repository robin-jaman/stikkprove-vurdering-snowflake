import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = {".py"}


def decode_bytes(data: bytes) -> str:
    if not data:
        return ""
    if data.startswith(b"\xff\xfe"):
        return data[2:].decode("utf-16-le")
    if data.startswith(b"\xfe\xff"):
        return data[2:].decode("utf-16-be")
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8")
    if len(data) >= 4 and data[1] == 0 and data[3] == 0 and data[0] != 0:
        return data.decode("utf-16-le")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252")


def ensure_utf8() -> None:
    if not os.access(ROOT, os.W_OK):
        return
    for path in ROOT.rglob("*.py"):
        if ".venv" in path.parts or ".git" in path.parts:
            continue
        original = path.read_bytes()
        if not original:
            continue
        encoded = decode_bytes(original).replace("\r\n", "\n").encode("utf-8")
        if encoded != original.replace(b"\r\n", b"\n"):
            path.write_bytes(encoded)
