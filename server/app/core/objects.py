"""Encrypted files for evidence and transcripts. The case data key is the only way to read them."""

from __future__ import annotations

import shutil
from pathlib import Path

from app.core.crypto import open_seal, seal
from app.core.errors import AppError


class MissingObject(AppError):
    def __init__(self, ref: str) -> None:
        super().__init__("missing_object", "Stored object was not found", status_code=404, details={"ref": ref})


class EncryptedObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def put(self, case_id: str, ref: str, payload: bytes, data_key: bytes) -> str:
        path = self._path(case_id, ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(seal(payload, data_key))
        return ref

    def get(self, case_id: str, ref: str, data_key: bytes) -> bytes:
        path = self._path(case_id, ref)
        if not path.is_file():
            raise MissingObject(ref)
        return open_seal(path.read_bytes(), data_key)

    def wipe(self, case_id: str) -> None:
        folder = self.root / case_id
        if folder.exists():
            shutil.rmtree(folder)

    def _path(self, case_id: str, ref: str) -> Path:
        safe_ref = Path(ref).name
        if not safe_ref or safe_ref in {".", ".."}:
            raise AppError("bad_ref", "Object reference is not valid", status_code=400)
        return self.root / case_id / safe_ref
