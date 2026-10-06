"""T-50: the P5 endpoints — default plan, drops with reasons, validator gate, A5 proposals, sign, campaign inputs."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote, urlparse

import pytest
from fastapi.testclient import TestClient

from modeler_api import project_api
from modeler_api.auth import get_verifier
from modeler_api.filestore import FileWriteStore
from modeler_api.main import app
from modeler_project import ArtifactKind, FileProjectStore, Workspace
from modeler_project.brief import empty_brief
from modeler_project.dataset_register import decide_dataset, propose_dataset
from modeler_project.datasets import ObservedDataset, Origin, Series, new_dataset_id
from modeler_project.evidence import EvidenceItem, EvidenceState, SourceRef, SourceType, new_id
from modeler_project.evidence_register import decide, propose
from modeler_project.inputs import accept_inputs, assemble
from modeler_project.requirements import derive

pytestmark = pytest.mark.req("T-50")
H = {"Authorization": "Bearer t"}
ROLES = {"value": ["modeler-curator", "modeler-reviewer"]}


def map_doc_sha(doc: dict) -> str:
    from pbpk_domain.campaign.map import MapDocument

    return MapDocument.model_validate(doc).content_sha256()


class FakeVerifier:
    def verify(self, token):
        return {"sub": "u1", "name": "Dr MIDD Lead", "tenant_id": "t1", "realm_access": {"roles": ROLES["value"]},
                "projects": ["*"], "acr": "loa2", "auth_time": int(time.time())}


def _dataset(ws, sid, route, dose, food="fasted", **extra):
    ds = ObservedDataset(id=new_dataset_id(), kind="profile", origin=Origin.LITERATURE, time_unit="h", unit="µmol/l",
                         study={"study_id": sid, "n": 12, "route": route, "dose_mg": dose, "formulation": "solution",
                                "food_state": food, "n_timepoints": 5, **({"infusion_time_min": 60} if route == "iv_infusion" else {}),
                                **extra},
                         series=(Series(times=(0.5, 1, 2, 4, 8), values=(20.0, 35.0, 21.0, 9.0, 2.0), n=12),))
    propose_dataset(ws, ds, actor="u1")
    decide_dataset(ws, ds.id, state=EvidenceState.ACCEPTED, reason="checked", by="u1")


@pytest.fixture
def setup(tmp_path, monkeypatch):
    import modeler_api.config as cfg

    store = FileProjectStore(tmp_path / "projects")
    read_root = tmp_path / "read-root"
    settings = SimpleNamespace(read_root=str(read_root), execution_backend="local")
    monkeypatch.setattr(cfg, "get_settings", lambda: settings)
    monkeypatch.setattr("modeler_api.plan_api.get_settings", lambda: settings)
    monkeypatch.setattr("modeler_api.project_api.get_settings", lambda: settings)
    monkeypatch.delenv("MODELER_LLM_PROVIDER", raising=False)
    ROLES["value"] = ["modeler-curator", "modeler-reviewer"]
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier()
    app.dependency_overrides[project_api.get_project_store] = lambda: store
    FileWriteStore(str(read_root)).put_project("t1", {"id": "p1", "name": "P1", "compounds": ["Renaldrug"], "pipeline": True})
    ws = Workspace(store, "t1", "p1")
    brief = empty_brief("Renaldrug", by="u1")
    b = ws.commit(ArtifactKind.BRIEF, "main", brief.to_content(), actor="u1", reason="start")
    ws.commit(ArtifactKind.REQUIREMENTS, "main", derive(brief).to_content(), derived_from=[b.ref], actor="u1", reason="derived")
    for target, value, conditions in (("phys.mw", 225.2, {}), ("phys.logp", -1.56, {}), ("bind.fu", 0.85, {}),
                                      ("phys.solubility.ref", 1.3, {}), ("phys.pka", 2.3, {"type": "base"}),
                                      ("elim.renal.gfr_fraction", 1.0, {})):
        unit = {"phys.mw": "g/mol", "phys.solubility.ref": "mg/ml"}.get(target)
        item = propose(ws, EvidenceItem(id=new_id(), target=target, value=value, unit=unit, conditions=conditions,
                                        source=SourceRef(title="review"), source_type=SourceType.REGULATORY_REVIEW,
                                        quote=f"{target} {value}"), actor="u1")
        decide(ws, item.id, state=EvidenceState.ACCEPTED, reason="checked", by="u1")
    for sid, route, dose in (("iv-250", "iv_infusion", 250), ("iv-500", "iv_infusion", 500), ("po-10", "oral", 10),
                             ("po-50", "oral", 50), ("po-100", "oral", 100)):
        _dataset(ws, sid, route, dose)
    _dataset(ws, "ddi-itra", "oral", 50, co_medication="itraconazole")
    assemble(ws, by="u1")
    accept_inputs(ws, by="u1")
    yield TestClient(app), ws, read_root
    app.dependency_overrides.clear()


def test_the_plan_is_ms01_by_default_and_a_rule_breaking_drop_blocks_the_signature(setup):
    c, ws, _root = setup
    view = c.get("/api/v1/projects/p1/plan", headers=H).json()["data"]
    roles = {s["study_id"]: s["role"] for s in view["overall_data"]["studies"]}
    assert roles["iv-250"] == "S1" and roles["ddi-itra"] == "SUPPORTIVE" and view["diff"] == []
    assert view["d1"]["pathways"][0]["process"] == "GlomerularFiltration" and view["d1"]["informed_by"] == ["iv-250"]
    assert view["d2"]["lanes"][0]["name"] == "solution"
    no_reason = c.put("/api/v1/projects/p1/plan/placements/ddi-itra", headers=H, json={"role": "S2", "reason": ""})
    assert no_reason.status_code == 422
    bad = c.put("/api/v1/projects/p1/plan/placements/ddi-itra", headers=H,
                json={"role": "S2", "reason": "more oral data"}).json()["data"]
    error = next(v for v in bad["violations"] if v["target"] == "ddi-itra")
    assert error["severity"] == "error" and error["rule"] == "rule-4" and bad["blocking"] >= 1
    assert bad["diff"][0] == {"kind": "role", "target": "ddi-itra", "from": "SUPPORTIVE", "to": "S2", "by": "u1",
                              "reason": "more oral data", "status": "APPLIED"}
    refused = c.post("/api/v1/projects/p1/plan:sign", headers=H, json={})
    assert refused.status_code == 409 and "open rule violations" in refused.json()["detail"]
    back = c.post("/api/v1/projects/p1/plan/placements/ddi-itra:unlock", headers=H).json()["data"]
    assert not any(v["target"] == "ddi-itra" for v in back["violations"])
    assert ws.latest(ArtifactKind.MODEL_PLAN, "main").version == 3


def test_a5_explains_and_proposes_and_only_a_person_applies(setup):
    from modeler_agents.llm import ChatResult, ToolCall
    from modeler_api.plan_api import run_planning_job

    c, ws, _root = setup
    c.put("/api/v1/projects/p1/plan/placements/po-50", headers=H, json={"role": "S5", "reason": "mid dose for validation"})

    class Scripted:
        provider, model = "test", "s"

        def __init__(self):
            self.turn = 0

        def complete(self, messages, tools):
            self.turn += 1
            calls = () if self.turn > 1 else (
                ToolCall(id="0", name="get_plan", arguments={}),
                ToolCall(id="1", name="explain", arguments={"target": "iv-250", "rationale": "the IV study trains S1"}),
                ToolCall(id="2", name="propose_role", arguments={"study_id": "po-50", "role": "S2", "reason": "x"}),
                ToolCall(id="3", name="propose_role", arguments={"study_id": "ddi-itra", "role": "S2", "reason": "y"}),
                ToolCall(id="4", name="propose_fit", arguments={"parameter": "elim.renal.gfr_fraction", "stages": ["S1"],
                                                                "lower": 0.1, "upper": 10, "scale": "log",
                                                                "reason": "GFR fraction is uncertain in this population"}))
            return ChatResult(content="" if calls else "done", tool_calls=calls, finish_reason="", usage={}, model="s")

    result = run_planning_job(ws.store, "t1", "p1", model=Scripted())
    assert result["explained"] == 1 and result["proposed"] == ["fit elim.renal.gfr_fraction"]
    assert set(result["refused"]) == {"po-50 → S2", "ddi-itra → S2"}   # a person's choice; a rule-4 break
    view = c.get("/api/v1/projects/p1/plan", headers=H).json()["data"]
    pending = [d for d in view["diff"] if d["status"] == "PENDING"]
    assert len(pending) == 1 and pending[0]["reason"] == "GFR fraction is uncertain in this population"
    assert next(s for s in view["overall_data"]["studies"] if s["study_id"] == "iv-250")["rationale"] == "the IV study trains S1"
    decided = c.post(f"/api/v1/projects/p1/plan/proposals/{pending[0]['proposal']}:decide", headers=H,
                     json={"accept": True, "reason": "agreed: one renal parameter free in S1"}).json()["data"]
    assert decided["plan"]["fits"]["elim.renal.gfr_fraction"]["userLocked"] is True


def test_approve_and_sign_generates_the_map_signs_it_and_stages_the_campaign(setup):
    c, ws, _root = setup
    view = c.get("/api/v1/projects/p1/plan", headers=H).json()["data"]
    for v in [v for v in view["violations"] if v["severity"] == "warning" and not v["acknowledged"]]:
        c.post(f"/api/v1/projects/p1/plan/violations/{v['id']}:acknowledge", headers=H, json={"reason": "accepted limitation"})
    ROLES["value"] = ["modeler-curator"]
    assert c.post("/api/v1/projects/p1/plan:sign", headers=H, json={}).status_code == 403   # the MIDD lead signs (D-07)
    ROLES["value"] = ["modeler-curator", "modeler-reviewer"]
    signed = c.post("/api/v1/projects/p1/plan:sign", headers=H, json={"note": "plan reviewed"})
    assert signed.status_code == 200, signed.text
    data = signed.json()["data"]
    assert data["signature"]["signature_id"] and data["map"]["status"] == "APPROVED"
    campaign = data["map"]["campaign"]
    map_doc = json.loads(Path(unquote(urlparse(campaign["map_uri"]).path)).read_text())
    assert map_doc["status"] == "SIGNED" and map_doc["signature"]["printed_name"] == "Dr MIDD Lead"
    observed = json.loads(Path(unquote(urlparse(campaign["observed_uri"]).path)).read_text())
    assert observed["iv-250"]["origin"] == "LITERATURE"
    assert ws.phases()["P5"] == "APPROVED"
    # D-14: after the signature a change is a MAP deviation, pending until the MIDD lead signs it
    after = c.put("/api/v1/projects/p1/plan/placements/po-10", headers=H, json={"role": "S5", "reason": "late change"})
    assert after.status_code == 200, after.text
    view = after.json()["data"]
    assert view["signed"] and view["deviations_pending"] == 1
    (dev,) = view["deviations"]
    assert (dev["kind"], dev["target"], dev["change"], dev["against_map"], dev["signature_id"]) == (
        "role", "po-10", "placed in S5", 1, None)
    assert c.put("/api/v1/projects/p1/plan/layout", headers=H, json={"layout": {"S1": {"x": 1, "y": 2}}}).json()[
        "data"]["deviations_pending"] == 1                                   # the layout is a view, never a deviation
    resigned = c.post("/api/v1/projects/p1/plan:sign", headers=H, json={"note": "deviation reviewed"})
    assert resigned.status_code == 200, resigned.text
    data = resigned.json()["data"]
    assert data["deviations_pending"] == 0 and data["deviations"][0]["signed_map"] == 2
    assert data["map"]["map_version"] == 2 and data["map"]["supersedes"] == map_doc_sha(map_doc)
    v2 = json.loads(Path(unquote(urlparse(data["map"]["campaign"]["map_uri"]).path)).read_text())
    assert v2["status"] == "SIGNED" and any("Deviation from MAP v1 (role, po-10)" in r for r in v2["split_rationale"])
    assert c.post("/api/v1/projects/p1/plan:sign", headers=H, json={}).status_code == 409    # nothing new to sign


@pytest.mark.req("T-50")
def test_external_values_are_blinded_until_the_map_is_signed(setup):
    """D-15: with blinding on, an external study's values are left out of every view (its metadata stays) until the
    MAP is signed; a curator reveals one dataset for a check with a reason on the audit chain."""
    c, _ws, _root = setup
    state = c.get("/api/v1/projects/p1/blinding", headers=H).json()["data"]
    assert state["on"] is False and "default" in state["source"]                 # medium risk: off by default
    ROLES["value"] = ["modeler-curator"]
    assert c.put("/api/v1/projects/p1/blinding", headers=H, json={"on": True, "reason": "r"}).status_code == 403
    ROLES["value"] = ["modeler-curator", "modeler-reviewer"]
    on = c.put("/api/v1/projects/p1/blinding", headers=H, json={"on": True, "reason": "ICH M15 §4.1 for this project"})
    assert on.status_code == 200 and on.json()["data"]["on"] is True
    c.get("/api/v1/projects/p1/plan", headers=H)                                  # the plan places the external studies
    blinded = c.get("/api/v1/projects/p1/blinding", headers=H).json()["data"]["blinded"]
    assert blinded and "iv-250" not in blinded
    sid = blinded[0]

    evidence = c.get("/api/v1/projects/p1/evidence", headers=H).json()["data"]
    hidden = next(d for d in evidence["datasets"] if d["study"]["study_id"] == sid)
    shown = next(d for d in evidence["datasets"] if d["study"]["study_id"] == "iv-250")
    assert hidden["blinded"] and set(hidden["series"][0]["values"]) == {None} and hidden["series"][0]["times"]
    assert shown["series"][0]["values"][0] == 20.0 and "blinded" not in shown
    artifact = c.get(f"/api/v1/projects/p1/artifacts/dataset/{hidden['id']}", headers=H).json()["data"]["content"]
    assert set(artifact["series"][0]["values"]) == {None}
    catalog = c.get("/api/v1/projects/p1/inputs", headers=H).json()["data"]["catalog"]["content"]["studies"]
    row = next(r for r in catalog if r["study_id"] == sid)
    assert row["blinded"] and "profile" not in row

    assert c.post(f"/api/v1/projects/p1/datasets/{hidden['id']}:reveal", headers=H, json={}).status_code == 422
    revealed = c.post(f"/api/v1/projects/p1/datasets/{hidden['id']}:reveal", headers=H,
                      json={"reason": "check the digitized points before acceptance"}).json()["data"]
    assert revealed["series"][0]["values"][0] == 20.0
    audit = c.get("/api/v1/projects/p1/audit", headers=H).json()["data"]["events"]
    assert any(e["action"] == "dataset.reveal" and "digitized points" in e["reason"] for e in audit)
    assert any(e["action"] == "blinding.set" and e["after"] is True for e in audit)

    for v in [v for v in c.get("/api/v1/projects/p1/plan", headers=H).json()["data"]["violations"] if v["severity"] == "warning"]:
        c.post(f"/api/v1/projects/p1/plan/violations/{v['id']}:acknowledge", headers=H, json={"reason": "accepted"})
    assert c.post("/api/v1/projects/p1/plan:sign", headers=H, json={}).status_code == 200
    after = c.get("/api/v1/projects/p1/evidence", headers=H).json()["data"]
    assert next(d for d in after["datasets"] if d["study"]["study_id"] == sid)["series"][0]["values"][0] == 20.0
