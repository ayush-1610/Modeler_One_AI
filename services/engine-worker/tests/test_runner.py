import hashlib
import sys
import textwrap
from pathlib import Path

import pytest

from modeler_contracts.runs import EngineInput, EngineJob
from modeler_engine.runner import EngineRunner, EngineTimeoutError, InputIntegrityError, LocalObjectStore

FAKE_ENGINE = textwrap.dedent(
    """
    import json, sys, time
    from pathlib import Path
    job = json.loads(Path(sys.argv[1]).read_text())
    if job["task"] == "sleep":
        time.sleep(10)
    out = Path(job["outputs_dir"])
    print("PROGRESS 0.5", flush=True)
    print("WARNING solver tolerance relaxed", flush=True)
    snapshot = Path(job["inputs"][0]["path"]).read_text()
    (out / "results.csv").write_text("time,value\\n0,0\\n1," + str(len(snapshot)) + "\\n")
    (out / "engine_manifest.json").write_text(json.dumps({"ospsuite_version": "fake"}))
    print("PROGRESS 1", flush=True)
    """
)


@pytest.fixture
def workspace(tmp_path: Path):
    engine = tmp_path / "fake_engine.py"
    engine.write_text(FAKE_ENGINE)
    snapshot = tmp_path / "store" / "snapshot.json"
    snapshot.parent.mkdir()
    snapshot.write_text('{"Version": 80}')
    return engine, snapshot, tmp_path


def make_job(snapshot: Path, tmp_path: Path, sha256: str, task: str = "simulate", timeout_s: int = 30) -> EngineJob:
    return EngineJob(
        job_id="run_test",
        tenant_id="t1",
        task=task,
        inputs=[EngineInput(name="snapshot.json", uri=snapshot.as_uri(), sha256=sha256)],
        outputs_uri=(tmp_path / "outputs").as_uri(),
        timeout_s=timeout_s,
    )


def test_run_hashes_outputs_and_captures_protocol(workspace):
    engine, snapshot, tmp_path = workspace
    beats: list[float] = []
    runner = EngineRunner(
        command=[sys.executable, str(engine)],
        store=LocalObjectStore(),
        engine_id="fake",
        image_digest="sha256:test",
        on_heartbeat=beats.append,
        heartbeat_interval_s=0.05,
    )
    sha = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    manifest = runner.run(make_job(snapshot, tmp_path, sha))

    assert manifest.status == "SUCCEEDED"
    assert manifest.warnings == ["solver tolerance relaxed"]
    assert manifest.engine_info == {"ospsuite_version": "fake"}
    by_name = {o.name: o for o in manifest.outputs}
    stored = tmp_path / "outputs" / "results.csv"
    assert by_name["results.csv"].sha256 == hashlib.sha256(stored.read_bytes()).hexdigest()
    assert beats and beats[-1] == 1.0


def test_tampered_input_is_rejected_before_execution(workspace):
    engine, snapshot, tmp_path = workspace
    runner = EngineRunner(command=[sys.executable, str(engine)], store=LocalObjectStore(), engine_id="fake", image_digest="x")
    with pytest.raises(InputIntegrityError, match="expected sha256"):
        runner.run(make_job(snapshot, tmp_path, "0" * 64))
    assert not (tmp_path / "outputs").exists()


def test_timeout_kills_engine(workspace):
    engine, snapshot, tmp_path = workspace
    runner = EngineRunner(
        command=[sys.executable, str(engine)], store=LocalObjectStore(), engine_id="fake", image_digest="x", heartbeat_interval_s=0.1
    )
    sha = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    with pytest.raises(EngineTimeoutError):
        runner.run(make_job(snapshot, tmp_path, sha, task="sleep", timeout_s=1))
