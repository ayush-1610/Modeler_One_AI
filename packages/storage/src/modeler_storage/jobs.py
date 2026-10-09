"""Leases on background jobs, shared by every process on one root (docs/ARCHITECTURE_BOUNDARIES.md, phase 8, C8).

A background job (an agent run of a project, a campaign continuing after a decision) used to be guarded by a set in
the process that started it, so a second API worker could start the same job again and showed it as not running. Its
state now lives beside the data, in one small file per job::

    <root>/<tenant>/jobs/<scope>/<key>.json     {owner, started_at, heartbeat_at}

`claim` takes the lease, or returns None while another holder's lease is live. A holder renews it (`heartbeat`, every
`HEARTBEAT_S` while `run_in_background` runs the job) and gives it up when the job ends (`release`). A lease whose holder
stopped renewing it for `TTL_S`, or whose process is gone on this host, is stale: `running` reads it as not running
and the next `claim` takes it over, so a job lost in a crash or a restart never blocks its project for good.
"""

from __future__ import annotations

import json
import os
import re
import socket
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from modeler_storage.filestore import resolve_root
from pbpk_domain.atomic_io import atomic_write_text, file_lock

TTL_S = 120          # a lease not renewed for this long is stale
HEARTBEAT_S = 30     # how often a running job renews its lease
_SAFE = re.compile(r"[^A-Za-z0-9._-]")


@dataclass(frozen=True)
class Lease:
    path: Path
    owner: str


def _now() -> datetime:
    return datetime.now(UTC)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # it exists, under another user
        return True
    return True


class FileJobRegistry:
    """Job leases under a file root (the project store's root: every worker of a deployment shares it)."""

    def __init__(self, root: str | Path, *, ttl_s: float = TTL_S):
        self.root = root if isinstance(root, Path) else resolve_root(root)
        self.ttl = timedelta(seconds=ttl_s)
        self.host = socket.gethostname()

    def _path(self, tenant_id: str, scope: str, key: str) -> Path:
        return self.root / _SAFE.sub("_", tenant_id) / "jobs" / _SAFE.sub("_", scope) / f"{_SAFE.sub('_', key)}.json"

    @staticmethod
    def _read(path: Path) -> dict[str, Any] | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return None

    def _live(self, record: dict[str, Any] | None) -> bool:
        if not record:
            return False
        if _now() - datetime.fromisoformat(record["heartbeat_at"]) > self.ttl:
            return False
        return record.get("host") != self.host or _alive(int(record.get("pid", 0)))

    def claim(self, tenant_id: str, scope: str, key: str) -> Lease | None:
        """Take the job's lease, or None while another holder's lease is live."""
        path = self._path(tenant_id, scope, key)
        with file_lock(path):
            if self._live(self._read(path)):
                return None
            owner = f"{self.host}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
            at = _now().isoformat()
            atomic_write_text(path, json.dumps({"owner": owner, "host": self.host, "pid": os.getpid(), "started_at": at,
                                                "heartbeat_at": at}))
            return Lease(path, owner)

    def heartbeat(self, lease: Lease) -> bool:
        """Renew a lease; False when it is no longer this holder's (it went stale and was taken over)."""
        with file_lock(lease.path):
            record = self._read(lease.path)
            if not record or record.get("owner") != lease.owner:
                return False
            atomic_write_text(lease.path, json.dumps({**record, "heartbeat_at": _now().isoformat()}))
            return True

    def release(self, lease: Lease) -> None:
        """Give the lease up (a no-op when another holder has taken it over)."""
        with file_lock(lease.path):
            record = self._read(lease.path)
            if record and record.get("owner") == lease.owner:
                lease.path.unlink()

    def running(self, tenant_id: str, scope: str, key: str) -> bool:
        """Whether a live holder has the job, in this process or any other on the root."""
        return self._live(self._read(self._path(tenant_id, scope, key)))

    def run_in_background(self, tenant_id: str, scope: str, key: str, target: Callable[[], None], *,
                          name: str | None = None) -> bool:
        """Claim the job and run `target` on a thread that renews the lease and releases it when `target` returns or
        raises. False, and nothing started, while another holder has it."""
        lease = self.claim(tenant_id, scope, key)
        if lease is None:
            return False

        def job() -> None:
            stop = threading.Event()

            def beat() -> None:
                while not stop.wait(HEARTBEAT_S):
                    if not self.heartbeat(lease):
                        return

            threading.Thread(target=beat, name=f"{name or key}-lease", daemon=True).start()
            try:
                target()
            finally:
                stop.set()
                self.release(lease)

        threading.Thread(target=job, name=name, daemon=True).start()
        return True
