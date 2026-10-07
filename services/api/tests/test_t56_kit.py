"""T-56: the Dapagliflozin proof kit (`deploy/proof/run_t56.py`) drives P0 → P5 over the API.

Software only: the inputs are the published OSP model's values and datasets, accepted by a test identity; the PK-Sim
run and the person's MAP signature are the server's (plan §19 T-56)."""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from modeler_api import project_api
from modeler_api.auth import get_verifier
from modeler_api.main import app
from modeler_project import FileProjectStore

pytestmark = pytest.mark.req("T-56")
KIT = Path(__file__).resolve().parents[3] / "deploy" / "proof" / "run_t56.py"


def _kit():
    spec = importlib.util.spec_from_file_location("run_t56", KIT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeVerifier:
    def verify(self, token):
        return {"sub": "u1", "name": "Dr MIDD Lead", "tenant_id": "t1",
                "realm_access": {"roles": ["modeler-curator", "modeler-reviewer"]},
                "projects": ["*"], "acr": "loa2", "auth_time": int(time.time())}


@pytest.fixture
def api(tmp_path, monkeypatch):
    from modeler_api.config import reload_settings

    store = FileProjectStore(tmp_path / "projects")
    monkeypatch.setenv("MODELER_READ_ROOT", str(tmp_path / "read-root"))
    monkeypatch.setenv("MODELER_EXECUTION_BACKEND", "local")
    monkeypatch.delenv("MODELER_LLM_PROVIDER", raising=False)
    reload_settings()
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier()
    app.dependency_overrides[project_api.get_project_store] = lambda: store
    client = TestClient(app, headers={"Authorization": "Bearer t"})
    yield _kit(), client
    app.dependency_overrides.clear()
    reload_settings()


def test_the_kit_takes_dapagliflozin_from_the_mock_proposal_to_a_traced_campaign(api, monkeypatch):
    kit, client = api
    monkeypatch.setenv("MODELER_ENGINE_COMMAND", f"python3 {KIT.parents[2] / 'deploy' / 'dev' / 'stub_engine.py'}")
    lines: list[str] = []
    prepared = kit.prepare(kit.Api(client), log=lines.append)
    assert len(prepared["proposed"]["evidence"]) == 42 and len(prepared["proposed"]["datasets"]) == 39
    pid = prepared["project_id"]
    plan = kit.accept(kit.Api(client), pid, prepared, name="Test Owner", log=lines.append)
    assert not plan["blocking"] and "fits: none" in lines[-2]
    with pytest.raises(RuntimeError, match="not signed"):
        kit.start(kit.Api(client), pid)                          # nothing runs before the MIDD lead signs
    # the signature is a person's (step-up); here the test identity signs, as the MIDD lead would in the web app
    assert client.post(f"/api/v1/projects/{pid}/plan:sign", json={"note": "T-56 software check"}).status_code == 200
    campaign_id = kit.start(kit.Api(client), pid, log=lines.append)
    for _ in range(120):
        campaign = client.get(f"/api/v1/campaigns/{campaign_id}").json()["data"]
        if campaign.get("status") not in ("RUNNING", "QUEUED"):
            break
        time.sleep(0.5)
    report, broken = kit.trace(kit.Api(client), pid, campaign_id)
    assert "Not a PBPK result" in report                          # the stub engine ran it: said so in the report
    assert "| `phys.mw` | 408.873 g/mol |" in report and "pubmed/21435141" in report
    assert not [b for b in broken if not b.startswith("MAR")], broken


def test_the_trace_reads_the_mar_evidence_index():
    kit = _kit()
    md = ("# MAR\n\n## Evidence index\n\nEvery quantitative statement above resolves to an entry here.\n\n"
          "| Reference | Value / title | Source |\n| --- | --- | --- |\n| value:auc_gmfe_s1 | 1.21 | stage S1 final round AUC GMFE |\n"
          "| table:studies | Studies | |\n\n## Signatures\n")
    assert kit.mar_evidence_index(md) == [("value:auc_gmfe_s1", "1.21", "stage S1 final round AUC GMFE"),
                                          ("table:studies", "Studies", "")]
