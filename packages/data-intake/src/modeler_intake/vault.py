"""Write-once, content-addressed storage for files exactly as the client supplied them."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import shutil
import stat
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class StoredFile:
    sha256: str
    original_name: str
    size_bytes: int
    media_type: str
    uploaded_by: str
    uploaded_at: str


class LocalRawVault:
    """Development vault on a local directory. Deployed profiles use S3/MinIO with Object Lock."""

    def __init__(self, root: Path):
        self.root = root

    def _paths(self, sha256: str) -> tuple[Path, Path]:
        folder = self.root / sha256[:2]
        return folder / sha256, folder / f"{sha256}.json"

    def store(self, source: Path, *, uploaded_by: str, original_name: str | None = None) -> StoredFile:
        sha256 = sha256_file(source)
        blob, meta = self._paths(sha256)
        if blob.exists():
            return StoredFile(**json.loads(meta.read_text(encoding="utf-8")))

        blob.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=blob.parent, delete=False) as tmp, source.open("rb") as handle:
            shutil.copyfileobj(handle, tmp)
        os.replace(tmp.name, blob)
        blob.chmod(stat.S_IRUSR | stat.S_IRGRP)

        name = original_name or source.name
        record = StoredFile(
            sha256=sha256,
            original_name=name,
            size_bytes=blob.stat().st_size,
            media_type=mimetypes.guess_type(name)[0] or "application/octet-stream",
            uploaded_by=uploaded_by,
            uploaded_at=datetime.now(UTC).isoformat(),
        )
        meta.write_text(json.dumps(asdict(record), indent=2), encoding="utf-8")
        meta.chmod(stat.S_IRUSR | stat.S_IRGRP)
        return record

    def path(self, sha256: str) -> Path:
        blob, _ = self._paths(sha256)
        if not blob.exists():
            raise FileNotFoundError(sha256)
        return blob

    def verify(self, sha256: str) -> bool:
        return sha256_file(self.path(sha256)) == sha256
