"""`GET /projects/{id}/steps`: the redesigned flow's four steps, read from content and the runner's campaigns."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from modeler_api.main import app
from modeler_storage.filestore import FileWriteStore

pytestmark = pytest.mark.req("T-50")

DEV = {"Authorization": "Bearer dev"}


@pytest.fixture
def http(tmp_path, api_settings):
    api_settings(read_root=str(tmp_path), dev_auth=True, execution_backend="local")
    return TestClient(app)


def test_the_steps_start_empty_and_run_follows_the_projects_campaigns(http, tmp_path):
    store = FileWriteStore(str(tmp_path))
    store.put_project("dev", {"id": "p1", "name": "P1", "compounds": ["Drug-A"], "openQuestions": 0, "risk": "medium",
                              "questions": [], "pipeline": True})

    def states() -> dict[str, str]:
        answer = http.get("/api/v1/projects/p1/steps", headers=DEV)
        assert answer.status_code == 200
        return {s["step"]: s["state"] for s in answer.json()["data"]["steps"]}

    assert states() == {"start": "not_started", "inputs": "not_started", "review": "not_started", "run": "not_started"}
    store.upsert_campaign("dev", {"id": "camp-1", "project": "p1", "status": "ESCALATED"})
    assert states()["run"] == "needs_you"
    store.upsert_campaign("dev", {"id": "camp-1", "project": "p1", "status": "COMPLETED"})
    assert states()["run"] == "done"
