"""Build an amoCRM private widget archive using only the Python standard library."""

import argparse
import json
import re
import struct
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

BASE = Path(__file__).resolve().parent
SOURCE = BASE / "widget"
LOGOS = {
    "logo_main.png": (400, 272),
    "logo_small.png": (108, 108),
    "logo.png": (130, 100),
    "logo_medium.png": (240, 84),
    "logo_min.png": (84, 84),
}


def json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def build(support_email: str | None) -> Path:
    manifest = json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))
    if support_email:
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", support_email):
            raise ValueError("Supply a valid --support-email address.")
        manifest["widget"]["support"] = {"email": support_email}

    files = ["script.js", "style.css"]
    for locale in manifest["widget"]["locale"]:
        name = f"i18n/{locale}.json"
        json.loads((SOURCE / name).read_text(encoding="utf-8"))
        files.append(name)
        files.extend(path.lstrip("/") for path in manifest["tour"]["tour_images"][locale])
    files.extend(f"images/{name}" for name in LOGOS)

    for name, dimensions in LOGOS.items():
        data = (SOURCE / "images" / name).read_bytes()
        if data[:8] != b"\x89PNG\r\n\x1a\n" or struct.unpack(">II", data[16:24]) != dimensions:
            raise ValueError(f"Invalid PNG dimensions: {name}; expected {dimensions}")
        if len(data) > 300 * 1024:
            raise ValueError(f"Logo exceeds 300 KB: {name}")

    # Explicit allowlist keeps build scripts, caches and local config out of the archive.
    payloads = {name: (SOURCE / name).read_bytes() for name in sorted(set(files))}
    for name, data in payloads.items():
        if name.endswith((".json", ".js", ".css")):
            data.decode("utf-8")
            if data.startswith(b"\xef\xbb\xbf"):
                raise ValueError(f"UTF-8 BOM is not allowed: {name}")

    destination = BASE / "widget.zip"
    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json_bytes(manifest))
        for name, data in payloads.items():
            archive.writestr(name, data)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--support-email", help="Contact of the person maintaining this private integration")
    args = parser.parse_args()
    output = build(args.support_email)
    print(f"Built {output} ({output.stat().st_size} bytes)")
    if not args.support_email:
        print("Demo package: support@example.invalid is a placeholder. Rebuild with --support-email before installation.")
