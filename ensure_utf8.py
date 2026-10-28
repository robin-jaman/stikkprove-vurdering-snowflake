from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXT = {".py", ".txt", ".ps1", ".toml", ".md", ".bat", ".json", ".mdc", ".example"}


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


def main() -> None:
    changed = 0
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in EXT:
            continue
        if ".venv" in path.parts or ".git" in path.parts:
            continue
        original = path.read_bytes()
        text = decode_bytes(original)
        encoded = text.replace("\r\n", "\n").encode("utf-8")
        if encoded != original.replace(b"\r\n", b"\n"):
            path.write_bytes(encoded.replace(b"\n", b"\r\n") if False else encoded)
            changed += 1
            print("UTF-8:", path)
    print("Ferdig. Oppdaterte", changed, "filer.")


if __name__ == "__main__":
    main()
