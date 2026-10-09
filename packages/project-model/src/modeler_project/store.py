"""Where artifact versions, approvals, raw files and the audit chain live (plan §15.2).

`ProjectStore` is the seam; `FileProjectStore` is the single-node implementation, laid out per tenant and project::

    <root>/<tenant>/projects/<pid>/artifacts/<kind>/<id>/v0001.json   immutable versions (written once, mode "x")
    <root>/<tenant>/projects/<pid>/approvals.jsonl                    approvals, append-only
    <root>/<tenant>/projects/<pid>/blobs/<sha256>                     raw uploaded bytes (write-once)
    <root>/<tenant>/audit.jsonl                                       the tenant's hash-chained audit trail

A version or blob appears whole or not at all: it is written to a temporary file in its folder, flushed to disk and
then linked into place, and the link fails when the name exists, so a version stays write-once (phase 8). Approvals are
appended under a cross-process lock, as the audit chain is: two API workers or an agent job writing beside a request
never interleave or lose a line.

The Postgres tables `artifact_versions`, `artifact_edges` and `audit_events` implement the same protocol later.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import os
import tempfile
from pathlib import Path
from typing import Protocol
from urllib.parse import unquote, urlparse

from modeler_project.artifacts import Approval, ArtifactKind, ArtifactVersion
from modeler_project.audit import AuditLog

# Filesystems without hard links (some network and container mounts): fall back to an exclusive create, written in place.
_NO_LINKS = {errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EXDEV, errno.EMLINK}


class ImmutableVersionError(RuntimeError):
    """A version that already exists was written again."""


class ProjectStore(Protocol):
    def put(self, tenant_id: str, project_id: str, version: ArtifactVersion) -> None: ...

    def versions(self, tenant_id: str, project_id: str, kind: ArtifactKind, artifact_id: str) -> list[ArtifactVersion]: ...

    def keys(self, tenant_id: str, project_id: str, kind: ArtifactKind | None = None) -> list[tuple[ArtifactKind, str]]: ...

    def approvals(self, tenant_id: str, project_id: str) -> list[Approval]: ...

    def add_approval(self, tenant_id: str, project_id: str, approval: Approval) -> None: ...

    def put_blob(self, tenant_id: str, project_id: str, data: bytes) -> str: ...

    def blob_path(self, tenant_id: str, project_id: str, sha256: str) -> Path | None: ...

    def audit(self, tenant_id: str) -> AuditLog: ...


def _publish(path: Path, data: bytes) -> bool:
    """Write `data` as `path`, whole or not at all; False when `path` already exists (it is never overwritten).

    The temporary file starts with "." and ends ".part", so no reader's pattern (`v*.json`, a blob's sha) matches it."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), 0o644)  # as a plain create would leave it (mkstemp makes it private)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(tmp, path)
        except FileExistsError:
            return False
        except OSError as exc:
            if exc.errno not in _NO_LINKS:
                raise
            try:
                with path.open("xb") as handle:
                    handle.write(data)
            except FileExistsError:
                return False
        return True
    finally:
        os.unlink(tmp)


def resolve_root(root: str | Path) -> Path:
    if isinstance(root, Path):
        return root
    parsed = urlparse(root)
    return Path(unquote(parsed.path) if parsed.scheme == "file" else root)


class FileProjectStore:
    def __init__(self, root: str | Path):
        self.root = resolve_root(root)

    def _project_dir(self, tenant_id: str, project_id: str) -> Path:
        return self.root / tenant_id / "projects" / project_id

    def _artifact_dir(self, tenant_id: str, project_id: str, kind: ArtifactKind, artifact_id: str) -> Path:
        return self._project_dir(tenant_id, project_id) / "artifacts" / kind.value / artifact_id

    # --- versions --------------------------------------------------------------------------------------------

    def put(self, tenant_id: str, project_id: str, version: ArtifactVersion) -> None:
        folder = self._artifact_dir(tenant_id, project_id, version.kind, version.id)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"v{version.version:04d}.json"
        if not _publish(path, version.model_dump_json(indent=2).encode("utf-8")):
            raise ImmutableVersionError(f"{version.ref.label()} already exists; versions are immutable")

    def versions(self, tenant_id: str, project_id: str, kind: ArtifactKind, artifact_id: str) -> list[ArtifactVersion]:
        folder = self._artifact_dir(tenant_id, project_id, kind, artifact_id)
        if not folder.exists():
            return []
        return [ArtifactVersion.model_validate_json(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("v*.json"))]

    def keys(self, tenant_id: str, project_id: str, kind: ArtifactKind | None = None) -> list[tuple[ArtifactKind, str]]:
        base = self._project_dir(tenant_id, project_id) / "artifacts"
        if not base.exists():
            return []
        kinds = [kind] if kind is not None else [k for k in ArtifactKind if (base / k.value).exists()]
        out: list[tuple[ArtifactKind, str]] = []
        for k in kinds:
            folder = base / k.value
            if folder.exists():
                out.extend((k, d.name) for d in sorted(folder.iterdir()) if d.is_dir() and any(d.glob("v*.json")))
        return out

    # --- approvals --------------------------------------------------------------------------------------------

    def approvals(self, tenant_id: str, project_id: str) -> list[Approval]:
        path = self._project_dir(tenant_id, project_id) / "approvals.jsonl"
        if not path.exists():
            return []
        return [Approval.model_validate_json(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]

    def add_approval(self, tenant_id: str, project_id: str, approval: Approval) -> None:
        path = self._project_dir(tenant_id, project_id) / "approvals.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                handle.write(approval.model_dump_json() + "\n")
                handle.flush()
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    # --- raw files --------------------------------------------------------------------------------------------

    def put_blob(self, tenant_id: str, project_id: str, data: bytes) -> str:
        sha = hashlib.sha256(data).hexdigest()
        folder = self._project_dir(tenant_id, project_id) / "blobs"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / sha
        if not path.exists():
            _publish(path, data)  # a concurrent writer of the same bytes may win; the blob is the same either way
        return sha

    def blob_path(self, tenant_id: str, project_id: str, sha256: str) -> Path | None:
        path = self._project_dir(tenant_id, project_id) / "blobs" / sha256
        return path if path.exists() else None

    # --- audit ------------------------------------------------------------------------------------------------

    def audit(self, tenant_id: str) -> AuditLog:
        return AuditLog(self.root, tenant_id)

