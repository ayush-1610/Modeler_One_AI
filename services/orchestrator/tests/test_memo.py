"""T-51: memoized engine runs — reused only when everything that decides the result is identical; never for S7."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from modeler_contracts.runs import EngineInput, EngineJob, EngineManifest, OutputFile
from modeler_orchestrator.memo import MemoEngine

pytestmark = pytest.mark.req("T-51")


class Counting:
    def __init__(self):
        self.calls = 0

    def __call__(self, job: EngineJob) -> EngineManifest:
        self.calls += 1
        out = Path(job.outputs_uri.removeprefix("file://"))
        out.mkdir(parents=True, exist_ok=True)
        (out / "result.csv").write_text(f"run {self.calls}")
        data = (out / "result.csv").read_bytes()
        return EngineManifest(job_id=job.job_id, status="SUCCEEDED", engine_id="t", image_digest="d", started_at="",
                              finished_at="", inputs={}, warnings=[], engine_info={}, stderr_tail="",
                              outputs=[OutputFile("result.csv", (out / "result.csv").as_uri(), hashlib.sha256(data).hexdigest(), len(data))])


def _job(tmp_path: Path, job_id: str, *, sha: str = "a" * 64, options: dict | None = None) -> EngineJob:
    return EngineJob(job_id=job_id, tenant_id="t", task="simulate", inputs=[EngineInput(f"{job_id}.json", "file:///x", sha)],
                     outputs_uri=(tmp_path / job_id).as_uri(), options=options or {"seed": 1})


def test_identical_jobs_reuse_outputs_and_anything_different_runs(tmp_path):
    engine = Counting()
    memo = MemoEngine(engine, root=tmp_path / "memo", engine_key="pksim@sha")
    first = memo(_job(tmp_path, "c1-S1-r1"))
    again = memo(_job(tmp_path, "c2-S1-r1"))                       # another campaign, same content
    assert engine.calls == 1 and memo.hits == 1
    assert again.job_id == "c2-S1-r1" and (tmp_path / "c2-S1-r1" / "result.csv").read_text() == "run 1"
    assert any("memoized" in w for w in again.warnings) and first.outputs[0].sha256 == again.outputs[0].sha256
    memo(_job(tmp_path, "c3", sha="b" * 64))                        # another input
    memo(_job(tmp_path, "c4", options={"seed": 2}))                 # another seed
    MemoEngine(engine, root=tmp_path / "memo", engine_key="pksim@other")(_job(tmp_path, "c5"))  # another engine
    assert engine.calls == 4
    (tmp_path / "c1-S1-r1" / "result.csv").write_text("tampered")   # the stored output changed: run again
    memo(_job(tmp_path, "c6"))
    assert engine.calls == 5


def test_the_s7_reproduction_rerun_always_runs(tmp_path):
    engine = Counting()
    memo = MemoEngine(engine, root=tmp_path / "memo", engine_key="pksim@sha")
    memo(_job(tmp_path, "c1-S7-rerun-S4-c1", options={"stem": "S4-c1"}))
    memo(_job(tmp_path, "c2-S7-rerun-S4-c1", options={"stem": "S4-c1"}))
    assert engine.calls == 2 and memo.hits == 0
