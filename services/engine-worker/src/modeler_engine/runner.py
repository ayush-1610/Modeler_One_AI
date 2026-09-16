"""Runs one engine job as a subprocess with integrity checks on every input and output.

The engine is launched as ``<command> <job.json>`` and talks back over stdout:
``PROGRESS <fraction>`` and ``WARNING <text>``; everything else is log output. The platform never
links against engine code (GPLv2 boundary, architecture pack §5.13).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import unquote, urlparse

from modeler_contracts.runs import EngineJob, EngineManifest, OutputFile

_PASSTHROUGH_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "LD_LIBRARY_PATH", "DOTNET_ROOT", "R_LIBS", "R_LIBS_USER", "TMPDIR")


class InputIntegrityError(Exception):
    pass


class EngineFailedError(Exception):
    pass


class EngineTimeoutError(Exception):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _terminate_group(proc: subprocess.Popen) -> int:
    """Kill the engine and its whole process group: SIGTERM, then SIGKILL if it lingers past 5 s."""
    def send(sig: int) -> None:
        try:
            os.killpg(os.getpgid(proc.pid), sig)
        except (ProcessLookupError, PermissionError):
            proc.send_signal(sig)  # process gone, or no group: fall back to the direct child
    send(signal.SIGTERM)
    try:
        return proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        send(signal.SIGKILL)
        return proc.wait()


class ObjectStore(Protocol):
    def download(self, uri: str, destination: Path) -> None: ...

    def upload(self, source: Path, uri: str) -> None: ...


def _local_path(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise ValueError(f"LocalObjectStore only handles file:// URIs, got {uri!r}")
    return Path(unquote(parsed.path))


class LocalObjectStore:
    """file:// object store for development and tests."""

    def download(self, uri: str, destination: Path) -> None:
        shutil.copyfile(_local_path(uri), destination)

    def upload(self, source: Path, uri: str) -> None:
        target = _local_path(uri)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


@dataclass
class EngineRunner:
    command: Sequence[str]
    store: ObjectStore
    engine_id: str
    image_digest: str
    on_heartbeat: Callable[[float], None] | None = None
    is_cancelled: Callable[[], bool] | None = None  # polled during the run; e.g. Temporal activity.is_cancelled
    heartbeat_interval_s: float = 15.0

    def run(self, job: EngineJob) -> EngineManifest:
        started = datetime.now(UTC)
        with tempfile.TemporaryDirectory(prefix="engine-job-") as tmp:
            workdir = Path(tmp)
            inputs_dir, outputs_dir = workdir / "inputs", workdir / "outputs"
            inputs_dir.mkdir()
            outputs_dir.mkdir()

            staged = []
            for item in job.inputs:
                if Path(item.name).name != item.name:
                    raise InputIntegrityError(f"input name {item.name!r} must be a bare file name")
                target = inputs_dir / item.name
                self.store.download(item.uri, target)
                actual = sha256_file(target)
                if actual != item.sha256:
                    raise InputIntegrityError(f"{item.name}: expected sha256 {item.sha256}, got {actual}")
                staged.append({"name": item.name, "path": str(target), "sha256": actual})

            job_file = workdir / "job.json"
            job_file.write_text(
                json.dumps(
                    {"job_id": job.job_id, "task": job.task, "inputs": staged, "options": job.options, "outputs_dir": str(outputs_dir)},
                    indent=2,
                ),
                encoding="utf-8",
            )

            warnings, stderr_tail, returncode, timed_out, cancelled = self._execute(job_file, workdir, job.timeout_s)
            if cancelled:
                # Whatever the engine wrote before it was killed is uploaded under cancelled/ for inspection.
                partial = self._upload_outputs(outputs_dir, f"{job.outputs_uri.rstrip('/')}/cancelled")
                return self._manifest(job, "CANCELLED", started, partial, {}, warnings, stderr_tail)
            if timed_out:
                raise EngineTimeoutError(f"engine exceeded {job.timeout_s}s; stderr: {stderr_tail}")
            if returncode != 0:
                raise EngineFailedError(f"engine exited with status {returncode}; stderr: {stderr_tail}")

            info_path = outputs_dir / "engine_manifest.json"
            engine_info = json.loads(info_path.read_text(encoding="utf-8")) if info_path.exists() else {}
            outputs = self._upload_outputs(outputs_dir, job.outputs_uri.rstrip("/"))

        return self._manifest(job, "SUCCEEDED", started, outputs, engine_info, warnings, stderr_tail)

    def _upload_outputs(self, outputs_dir: Path, base_uri: str) -> list[OutputFile]:
        outputs = []
        for path in sorted(p for p in outputs_dir.rglob("*") if p.is_file()):
            relative = path.relative_to(outputs_dir).as_posix()
            uri = f"{base_uri}/{relative}"
            self.store.upload(path, uri)
            outputs.append(OutputFile(name=relative, uri=uri, sha256=sha256_file(path), size_bytes=path.stat().st_size))
        return outputs

    def _manifest(self, job: EngineJob, status: str, started: datetime, outputs: list[OutputFile],
                  engine_info: dict, warnings: list[str], stderr_tail: str) -> EngineManifest:
        return EngineManifest(
            job_id=job.job_id,
            status=status,
            engine_id=self.engine_id,
            image_digest=self.image_digest,
            started_at=started.isoformat(),
            finished_at=datetime.now(UTC).isoformat(),
            inputs={item.name: item.sha256 for item in job.inputs},
            outputs=outputs,
            warnings=warnings,
            engine_info=engine_info,
            stderr_tail=stderr_tail,
        )

    def _execute(self, job_file: Path, workdir: Path, timeout_s: int) -> tuple[list[str], str, int, bool, bool]:
        env = {key: os.environ[key] for key in _PASSTHROUGH_ENV if key in os.environ}
        proc = subprocess.Popen(
            [*self.command, str(job_file)],
            cwd=workdir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,  # own process group, so cancellation kills the engine and its children
        )
        progress = [0.0]
        warnings: list[str] = []
        stderr_lines: list[str] = []

        def read_stdout() -> None:
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.rstrip("\n")
                if line.startswith("PROGRESS "):
                    try:
                        progress[0] = float(line.split(" ", 1)[1])
                    except ValueError:
                        pass
                elif line.startswith("WARNING "):
                    warnings.append(line.removeprefix("WARNING "))

        def read_stderr() -> None:
            assert proc.stderr is not None
            stderr_lines.extend(proc.stderr)

        readers = [threading.Thread(target=read_stdout, daemon=True), threading.Thread(target=read_stderr, daemon=True)]
        for reader in readers:
            reader.start()

        # Heartbeats are sent from this (activity) thread; Temporal's activity context is thread-local.
        deadline = time.monotonic() + timeout_s
        timed_out = cancelled = False
        while True:
            remaining = deadline - time.monotonic()
            try:
                returncode = proc.wait(timeout=max(0.05, min(self.heartbeat_interval_s, remaining)))
                break
            except subprocess.TimeoutExpired:
                if self.is_cancelled is not None and self.is_cancelled():
                    returncode = _terminate_group(proc)
                    cancelled = True
                    break
                if time.monotonic() >= deadline:
                    returncode = _terminate_group(proc)
                    timed_out = True
                    break
                if self.on_heartbeat:
                    self.on_heartbeat(progress[0])

        for reader in readers:
            reader.join(timeout=5)
        if self.on_heartbeat:
            self.on_heartbeat(progress[0])
        return warnings, "".join(stderr_lines)[-4000:], returncode, timed_out, cancelled
