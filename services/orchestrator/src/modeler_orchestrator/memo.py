"""Memoized engine runs and model sets (plan §12.3 N1 and N7; T-51).

**Memoized execution.** An engine job is keyed by what determines its result: the task, the content hash of every
input, the options (seeds included) and the engine's identity (command and image digest). When a job with the same
key already succeeded and its outputs are still there with the recorded hashes, the outputs are copied into the new
job's output directory and a manifest is returned for the new job, marked as reused; no engine process starts. So
propagation re-runs only what changed, and a repeated cycle costs nothing twice. Anything in doubt (a missing or
changed output, a failed earlier run) is a miss and runs on the engine.

**Model set.** Every judged round records the model set it judged: the CPF content hash, the engine, the hash of the
stage's scenarios in the signed MAP and the builder version. A CPF change is a new model set, so an evaluation is
always attributable to exactly one parameter set (plan §12.3 N1).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
from collections.abc import Callable
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from modeler_contracts.runs import EngineJob, EngineManifest, OutputFile
from pbpk_domain.atomic_io import atomic_write_text

EngineRun = Callable[[EngineJob], EngineManifest]
MEMO_NOTE = "memoized"
# S7 re-runs every bundled simulation on a fresh engine to prove the package reproduces (decision D13): reusing an
# earlier output would make that check prove nothing, so those jobs (`package_activities.prepare_reproduction_jobs`
# names them `<campaign>-S7-rerun-<stem>`) always run.
NEVER_REUSE_MARKERS = ("-S7-rerun-",)


def _path(uri: str) -> Path:
    return Path(unquote(urlparse(uri).path))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def job_key(job: EngineJob, engine_key: str) -> str:
    """What decides a job's result. The input *names* and the job id are left out (they carry the campaign id)."""
    doc = {"task": job.task, "inputs": sorted(i.sha256 for i in job.inputs), "engine": engine_key,
           "options": json.loads(json.dumps(job.options, sort_keys=True, default=str))}
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class MemoEngine:
    """An engine that reuses the outputs of an identical, successful earlier job."""

    def __init__(self, engine: EngineRun, *, root: Path, engine_key: str):
        self.engine = engine
        self.root = root
        self.engine_key = engine_key
        self.hits = 0
        self.misses = 0
        self._lock = threading.Lock()
        self.__name__ = getattr(engine, "__name__", type(engine).__name__)

    def _record(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def _reuse(self, job: EngineJob, record: dict[str, Any]) -> EngineManifest | None:
        out_dir = _path(job.outputs_uri)
        files: list[OutputFile] = []
        for o in record["outputs"]:
            source = _path(o["uri"])
            if not source.is_file() or _sha256(source) != o["sha256"]:
                return None  # the earlier output is gone or changed: run again
            files.append(OutputFile(**o))
        out_dir.mkdir(parents=True, exist_ok=True)
        copied = []
        for o in files:
            target = out_dir / o.name
            if _path(o.uri) != target:
                shutil.copyfile(_path(o.uri), target)
            copied.append(replace(o, uri=target.as_uri()))
        manifest = EngineManifest(**{**record["manifest"], "outputs": []})
        return replace(manifest, job_id=job.job_id, outputs=copied,
                       warnings=[*manifest.warnings, f"{MEMO_NOTE}: outputs of {record['manifest']['job_id']} reused"])

    def __call__(self, job: EngineJob) -> EngineManifest:
        if any(marker in job.job_id for marker in NEVER_REUSE_MARKERS):
            return self.engine(job)
        key = job_key(job, self.engine_key)
        path = self._record(key)
        if path.is_file():
            reused = self._reuse(job, json.loads(path.read_text(encoding="utf-8")))
            if reused is not None:
                with self._lock:
                    self.hits += 1
                return reused
        manifest = self.engine(job)
        with self._lock:
            self.misses += 1
        if manifest.status == "SUCCEEDED":
            path.parent.mkdir(parents=True, exist_ok=True)
            data = asdict(manifest)
            atomic_write_text(path, json.dumps({"key": key, "manifest": data, "outputs": data["outputs"]}))
        return manifest


def model_set(*, cpf_sha256: str, engine_key: str, scenarios: list[dict[str, Any]], stage: str) -> dict[str, str]:
    """The model set a round judged (plan §12.3 N1): CPF, engine, the stage's scenarios, builder version."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        builder = version("pbpk-domain")
    except PackageNotFoundError:
        builder = "unknown"
    scenario_sha = hashlib.sha256(json.dumps(scenarios, sort_keys=True, default=str).encode()).hexdigest()
    ident = hashlib.sha256(f"{cpf_sha256}|{engine_key}|{scenario_sha}|{builder}".encode()).hexdigest()
    return {"id": f"ms-{ident[:12]}", "stage": stage, "cpf_sha256": cpf_sha256, "engine": engine_key,
            "scenario_set_sha256": scenario_sha, "builder_version": builder}
