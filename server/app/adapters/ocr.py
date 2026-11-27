"""Local OCR through the Tesseract command line. Images never leave this machine."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.config import SERVER_ROOT

_DEFAULT_WINDOWS = Path("C:/Program Files/Tesseract-OCR/tesseract.exe")
PASSES = ("eng+hin", "eng", "hin")


def tesseract_path() -> str | None:
    found = shutil.which("tesseract")
    if found:
        return found
    return str(_DEFAULT_WINDOWS) if _DEFAULT_WINDOWS.is_file() else None


class TesseractOCR:
    """Runs several language passes, because English-only and Hindi-only reads often fix each other's mistakes."""

    def __init__(self, binary: str | None = None, tessdata: Path | None = None, passes: tuple[str, ...] = PASSES) -> None:
        self.binary = binary or tesseract_path()
        self.tessdata = tessdata or SERVER_ROOT / "data" / "tessdata"
        self.passes = passes

    @property
    def available(self) -> bool:
        return bool(self.binary) and any((self.tessdata / f"{lang}.traineddata").is_file() for lang in ("eng", "hin"))

    def read(self, image: bytes) -> list[str]:
        if not self.available:
            return []
        texts: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "page.png"
            path.write_bytes(image)
            for lang in self.passes:
                if not all((self.tessdata / f"{part}.traineddata").is_file() for part in lang.split("+")):
                    continue
                env = {"TESSDATA_PREFIX": str(self.tessdata), "PATH": os.environ.get("PATH", "")}
                done = subprocess.run([str(self.binary), str(path), "-", "-l", lang], capture_output=True, env=env, timeout=90, check=False)
                texts.append(done.stdout.decode("utf-8", errors="replace"))
        return texts
