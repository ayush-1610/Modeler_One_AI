"""No job state lives in one process (docs/ARCHITECTURE_BOUNDARIES.md, coupling C8, phase 8).

A set of running jobs or a thread lock at module level holds only for the process that owns it: a second API worker, or
the orchestrator beside the API, sees an empty set and an unheld lock. Phase 8 moved that state beside the data (job
leases in `modeler_storage.jobs`, `flock` on the documents in `pbpk_domain.atomic_io.file_lock`), and this test keeps
it there: a module-level assignment of a set, a thread lock or event, a queue, or an empty collection fails, unless
listed below with its reason. A lock inside an object (one engine's memo) is per instance and is not counted.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.req("T-25")

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [ROOT / p for p in ("packages", "services")]
STATE_CALLS = {"set", "Lock", "RLock", "Semaphore", "BoundedSemaphore", "Condition", "Event", "defaultdict", "deque",
               "Queue"}
ALLOWED = {
    # the audit chain's in-process lock, taken before its cross-process flock on the chain file (locked file)
    "packages/project-model/src/modeler_project/audit.py:_LOCK",
}


def _state() -> set[str]:
    found = set()
    for base in SOURCES:
        for path in base.glob("*/src/**/*.py"):
            for node in ast.parse(path.read_text(encoding="utf-8")).body:
                if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
                    continue
                value = node.value
                if isinstance(value, ast.Call):
                    func = value.func
                    stateful = (func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")) in STATE_CALLS
                else:
                    stateful = (isinstance(value, ast.Dict) and not value.keys) or (
                        isinstance(value, (ast.List, ast.Set)) and not value.elts)
                if stateful:
                    for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                        found.add(f"{path.relative_to(ROOT)}:{ast.unparse(target)}")
    return found


def test_no_job_state_at_module_level() -> None:
    new = sorted(_state() - ALLOWED)
    assert not new, (
        "module-level mutable state holds only for one process (C8):\n  " + "\n  ".join(new)
        + "\nKeep a job's state beside the data: a lease in modeler_storage.jobs (modeler_api.jobs for a project's agent "
          "job), and a read-modify-write under pbpk_domain.atomic_io.file_lock.")


def test_the_allowed_state_still_exists() -> None:
    stale = sorted(ALLOWED - _state())
    assert not stale, "remove these entries from ALLOWED, so the list only shrinks:\n  " + "\n  ".join(stale)
