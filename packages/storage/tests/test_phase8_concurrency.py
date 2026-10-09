"""Phase 8 (C8): job state and read-model writes are shared by every process on one root, not kept per process."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest

from modeler_storage import jobs
from modeler_storage.filestore import FileReadStore, FileWriteStore
from modeler_storage.jobs import FileJobRegistry

pytestmark = pytest.mark.req("T-25")


def test_a_live_lease_blocks_a_second_claim_until_it_is_released(tmp_path):
    registry = FileJobRegistry(tmp_path)
    lease = registry.claim("t1", "p1", "extraction")
    assert lease is not None and registry.running("t1", "p1", "extraction")
    assert registry.claim("t1", "p1", "extraction") is None
    assert registry.claim("t1", "p1", "research") is not None  # another job of the project is independent
    registry.release(lease)
    assert not registry.running("t1", "p1", "extraction")
    assert registry.claim("t1", "p1", "extraction") is not None


def _write_lease(registry: FileJobRegistry, *, host: str, pid: int, age_s: float) -> None:
    path = registry._path("t1", "p1", "extraction")
    path.parent.mkdir(parents=True, exist_ok=True)
    at = (datetime.now(UTC) - timedelta(seconds=age_s)).isoformat()
    path.write_text(json.dumps({"owner": f"{host}:{pid}:x", "host": host, "pid": pid, "started_at": at, "heartbeat_at": at}))


def test_a_lease_not_renewed_within_the_ttl_is_taken_over(tmp_path):
    registry = FileJobRegistry(tmp_path, ttl_s=60)
    _write_lease(registry, host="another-worker", pid=1, age_s=30)
    assert registry.running("t1", "p1", "extraction") and registry.claim("t1", "p1", "extraction") is None
    _write_lease(registry, host="another-worker", pid=1, age_s=90)
    assert not registry.running("t1", "p1", "extraction")
    assert registry.claim("t1", "p1", "extraction") is not None


def test_a_lease_whose_process_is_gone_on_this_host_is_taken_over(tmp_path):
    registry = FileJobRegistry(tmp_path)
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    _write_lease(registry, host=registry.host, pid=gone.pid, age_s=1)
    assert not registry.running("t1", "p1", "extraction")
    _write_lease(registry, host=registry.host, pid=os.getpid(), age_s=1)
    assert registry.running("t1", "p1", "extraction")


def test_release_by_a_holder_whose_lease_was_taken_over_leaves_the_new_holder(tmp_path):
    registry = FileJobRegistry(tmp_path, ttl_s=60)
    old = registry.claim("t1", "p1", "extraction")
    _write_lease(registry, host="another-worker", pid=1, age_s=0)  # taken over meanwhile
    assert not registry.heartbeat(old)
    registry.release(old)
    assert registry.running("t1", "p1", "extraction")


def test_a_background_job_holds_its_lease_while_it_runs_and_releases_it_after(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "HEARTBEAT_S", 0.05)
    registry = FileJobRegistry(tmp_path)
    gate, done = threading.Event(), threading.Event()

    def work() -> None:
        gate.wait(5)
        done.set()

    assert registry.run_in_background("t1", "p1", "planning", work, name="test-job")
    assert registry.running("t1", "p1", "planning")
    assert not registry.run_in_background("t1", "p1", "planning", work)  # one at a time
    time.sleep(0.2)  # a few heartbeats
    gate.set()
    assert done.wait(5)
    for _ in range(100):
        if not registry.running("t1", "p1", "planning"):
            break
        time.sleep(0.02)
    assert not registry.running("t1", "p1", "planning")


def test_a_failing_background_job_still_releases_its_lease(tmp_path):
    registry = FileJobRegistry(tmp_path)

    def boom() -> None:
        raise RuntimeError("agent failed")

    assert registry.run_in_background("t1", "p1", "triage", boom)
    for _ in range(100):
        if not registry.running("t1", "p1", "triage"):
            break
        time.sleep(0.02)
    assert not registry.running("t1", "p1", "triage")


_HOLD = """
import sys, time
from modeler_storage.jobs import FileJobRegistry
registry = FileJobRegistry(sys.argv[1])
lease = registry.claim("t1", "p1", "extraction")
print("held" if lease else "busy", flush=True)
time.sleep(float(sys.argv[2]))
if lease:
    registry.release(lease)
"""


def test_a_job_held_by_another_process_is_running_here_and_cannot_be_claimed(tmp_path):
    holder = subprocess.Popen([sys.executable, "-c", _HOLD, str(tmp_path), "3"], stdout=subprocess.PIPE, text=True)
    assert holder.stdout.readline().strip() == "held"
    registry = FileJobRegistry(tmp_path)
    assert registry.running("t1", "p1", "extraction")
    assert registry.claim("t1", "p1", "extraction") is None
    assert holder.wait(timeout=30) == 0
    assert not registry.running("t1", "p1", "extraction")


_UPSERT = """
import sys
from modeler_storage.filestore import FileWriteStore
store = FileWriteStore(sys.argv[1])
for i in range(int(sys.argv[3])):
    store.upsert_campaign("t1", {"id": f"{sys.argv[2]}-{i}", "status": "RUNNING"})
"""


def test_two_processes_upserting_one_collection_lose_no_row(tmp_path):
    workers = [subprocess.Popen([sys.executable, "-c", _UPSERT, str(tmp_path), name, "60"]) for name in ("a", "b")]
    assert [w.wait(timeout=120) for w in workers] == [0, 0]
    ids = {c["id"] for c in FileReadStore(str(tmp_path)).list_campaigns("t1")}
    assert ids == {f"{n}-{i}" for n in ("a", "b") for i in range(60)}


def test_an_escalation_is_removed_once(tmp_path):
    store = FileWriteStore(str(tmp_path))
    store.upsert_escalation("t1", {"id": "camp-1-S1", "campaignId": "camp-1"})
    assert store.remove_escalation("t1", "camp-1-S1") is True
    assert store.remove_escalation("t1", "camp-1-S1") is False  # a second decision claims nothing
