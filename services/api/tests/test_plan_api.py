"""T-50: the P5 endpoints — default plan, drops with reasons, validator gate, A5 proposals, sign, campaign inputs."""

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest
from fastapi.testclient import TestClient

from modeler_api import project_api
from modeler_api.auth import get_verifier
from modeler_api.main import app
from modeler_project import ArtifactKind, FileProjectStore, Workspace
from modeler_project.brief import FieldStatus, empty_brief
from modeler_project.brief_ops import edit_field
from modeler_project.dataset_register import decide_dataset, propose_dataset
from modeler_project.datasets import ObservedDataset, Origin, Series, new_dataset_id
from modeler_project.evidence import EvidenceItem, EvidenceState, SourceRef, SourceType, new_id
from modeler_project.evidence_register import decide, propose
from modeler_project.inputs import accept_inputs, assemble
from modeler_project.requirements import derive
from modeler_storage.filestore import FileReadStore, FileWriteStore

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
    ds = ObservedDataset(id=new_dataset_id(), kind="profile", demographics_choice="healthy_adult_default", origin=Origin.LITERATURE, time_unit="h", unit="µmol/l",
                         study={"study_id": sid, "n": 12, "route": route, "dose_mg": dose, "formulation": "solution",
                                "food_state": food, "n_timepoints": 5, **({"infusion_time_min": 60} if route == "iv_infusion" else {}),
                                **extra},
                         series=(Series(times=(0.5, 1, 2, 4, 8), values=(20.0, 35.0, 21.0, 9.0, 2.0), n=12),))
    propose_dataset(ws, ds, actor="u1")
    decide_dataset(ws, ds.id, state=EvidenceState.ACCEPTED, reason="checked", by="u1")


@pytest.fixture
def setup(tmp_path, monkeypatch, api_settings):
    store = FileProjectStore(tmp_path / "projects")
    read_root = tmp_path / "read-root"
    api_settings(read_root=str(read_root), execution_backend="local")
    monkeypatch.delenv("MODELER_LLM_PROVIDER", raising=False)
    ROLES["value"] = ["modeler-curator", "modeler-reviewer"]
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier()
    app.dependency_overrides[project_api.get_project_store] = lambda: store
    FileWriteStore(str(read_root)).put_project("t1", {"id": "p1", "name": "P1", "compounds": ["Renaldrug"], "openQuestions": 0,
                                                       "risk": "medium", "questions": [], "pipeline": True})
    ws = Workspace(store, "t1", "p1")
    # the person's ICH M15 tier (never assumed: a plan without one cannot be signed)
    brief = edit_field(empty_brief("Renaldrug", by="u1"), "acceptance.tier", value="medium", status=FieldStatus.EDITED,
                       note="influence medium, consequence medium", by="u1")
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
    from pbpk_domain.campaign.map import MapDocument, cpf_differences
    from pbpk_domain.cpf import CPF

    staged = CPF.model_validate_json(Path(unquote(urlparse(campaign["cpf_uri"]).path)).read_text())
    assert cpf_differences(MapDocument.model_validate(map_doc), staged) == []   # D-36: a pilot starts on the staged pair
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
    # phase 6e: MAP/main is written and read through modeler_project.map_artifact; its stored content keeps the keys the
    # router wrote before and reads back byte for byte (the audit chain hashes content)
    from modeler_project.map_artifact import MapArtifact

    versions = ws.versions(ArtifactKind.MAP, "main")
    assert [v.version for v in versions] == [1, 2]
    for stored in versions:
        assert set(stored.content) == {"map", "map_sha256", "signature", "campaign"}
        assert MapArtifact.from_content(stored.content).to_content() == stored.content


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

    from modeler_api.read_api import get_read_store

    # the studies published for the legacy campaign path are blinded the same way
    from modeler_api.studies import StudyUpload

    def row(study_id: str, value: float) -> dict:  # a study as `inputs:publish` stores it (the upload shape)
        return StudyUpload(study_id=study_id, route="iv_infusion", dose_mg=250, infusion_time_min=60,
                           profile={"times": [1.0], "values": [value]}).model_dump()

    FileWriteStore(str(_root)).put_studies("t1", "p1", [row(sid, 1.0), row("iv-250", 2.0)])
    app.dependency_overrides[get_read_store] = lambda: FileReadStore(str(_root))
    listed = {s["study_id"]: s for s in c.get("/api/v1/projects/p1/studies", headers=H).json()["data"]["studies"]}
    assert listed[sid]["blinded"] and "profile" not in listed[sid] and listed["iv-250"]["profile"]
    assert c.post(f"/api/v1/projects/p1/datasets/{hidden['id']}:reveal", headers=H, json={}).status_code == 422
    revealed = c.post(f"/api/v1/projects/p1/datasets/{hidden['id']}:reveal", headers=H,
                      json={"reason": "check the digitized points before acceptance"}).json()["data"]
    assert revealed["series"][0]["values"][0] == 20.0
    # the stored dataset, read through its owner: every key of ObservedDataset, and no redaction mark (phase 9e)
    assert set(revealed) == set(ObservedDataset.model_fields) and "blinded" not in revealed
    audit = c.get("/api/v1/projects/p1/audit", headers=H).json()["data"]["events"]
    assert any(e["action"] == "dataset.reveal" and "digitized points" in e["reason"] for e in audit)
    assert any(e["action"] == "blinding.set" and e["after"] is True for e in audit)

    for v in [v for v in c.get("/api/v1/projects/p1/plan", headers=H).json()["data"]["violations"] if v["severity"] == "warning"]:
        c.post(f"/api/v1/projects/p1/plan/violations/{v['id']}:acknowledge", headers=H, json={"reason": "accepted"})
    assert c.post("/api/v1/projects/p1/plan:sign", headers=H, json={}).status_code == 200
    after = c.get("/api/v1/projects/p1/evidence", headers=H).json()["data"]
    assert next(d for d in after["datasets"] if d["study"]["study_id"] == sid)["series"][0]["values"][0] == 20.0


def test_every_canvas_route_answers_the_typed_page(setup, monkeypatch):
    """Phase 9b: the routes no other test reaches answer their response model (the conftest guard compares each typed
    answer with the handler's own value): the read-only view, a move's dry run, a fit set and removed, a structure
    choice, a rebase and the A5 draft."""
    from modeler_api import plan_api

    c, _ws, _root = setup
    c.get("/api/v1/projects/p1/plan", headers=H)
    viewed = c.get("/api/v1/projects/p1/plan:view", headers=H)
    assert viewed.status_code == 200 and viewed.json()["data"]["plan"]["schema"] == "model-plan/1"

    preview = c.put("/api/v1/projects/p1/plan/placements/po-50?dry_run=true", headers=H,
                    json={"role": "S5", "reason": "mid dose for validation"}).json()["data"]
    assert set(preview) == {"violations", "diff", "deviation"} and preview["deviation"] is False

    fit = {"stages": ["S1"], "lower": 0.1, "upper": 10, "scale": "log", "reason": "GFR fraction is uncertain"}
    fitted = c.put("/api/v1/projects/p1/plan/fits/elim.renal.gfr_fraction", headers=H, json=fit).json()["data"]
    assert fitted["plan"]["fits"]["elim.renal.gfr_fraction"]["stages"] == ["S1"]
    removed = c.post("/api/v1/projects/p1/plan/fits/elim.renal.gfr_fraction:remove", headers=H,
                     json={"reason": "fixed after all"}).json()["data"]
    assert "elim.renal.gfr_fraction" not in removed["plan"]["fits"]

    food = c.put("/api/v1/projects/p1/plan/structure", headers=H,
                 json={"key": "food_effect_in_question", "value": True, "reason": "the label asks about food"}).json()["data"]
    row = next(d for d in food["diff"] if d["kind"] == "structure")
    assert row["to"] is True and food["d2"]["food_effect_in_question"] is True

    rebased = c.post("/api/v1/projects/p1/plan:rebase", headers=H)
    assert rebased.status_code == 200 and rebased.json()["data"]["artifact"]["kind"] == "model_plan"

    monkeypatch.setattr(plan_api.agent_jobs, "require_chat_model", lambda _off: object())
    monkeypatch.setattr(plan_api, "run_planning_job", lambda *a, **k: None)
    draft = c.post("/api/v1/projects/p1/plan:draft", headers=H)
    assert draft.status_code == 202 and draft.json()["data"] == {"status": "RUNNING"}


def test_a_brief_edit_makes_the_plan_stale_and_the_rebase_reads_it_while_a_persons_choice_stays(setup):
    """Redesign §3.1 (the "read once" gap): the structure follows the brief on every rebase, except the keys a person
    set on the canvas."""
    c, ws, _root = setup
    c.get("/api/v1/projects/p1/plan", headers=H)
    chosen = c.put("/api/v1/projects/p1/plan/structure", headers=H,
                   json={"key": "context_of_use", "value": "internal go / no-go", "reason": "agreed at kick-off"})
    assert chosen.status_code == 200, chosen.text
    edit = c.put("/api/v1/projects/p1/brief", headers=H, json={"changes": [
        {"path": "qoi.text", "status": "EDITED", "value": "exposure after 100 mg"},
        {"path": "qoi.context_of_use", "status": "EDITED", "value": "support a dose change"},
        {"path": "m15.influence_rating", "status": "EDITED", "value": "high"},
        {"path": "m15.consequence_rating", "status": "EDITED", "value": "high"},
        {"path": "acceptance.tier", "status": "EDITED", "value": "high"}]})
    assert edit.status_code == 200, edit.text
    assemble(ws, by="u1")                     # the CPF derives from the brief: the inputs are put together again
    accept_inputs(ws, by="u1")
    stale = c.put("/api/v1/projects/p1/plan/placements/po-50", headers=H, json={"role": "S5", "reason": "validation"})
    assert stale.status_code == 409 and "the brief changed" in stale.json()["detail"]
    structure = c.post("/api/v1/projects/p1/plan:rebase", headers=H).json()["data"]["plan"]["structure"]
    assert structure["objective"] == "exposure after 100 mg" and structure["model_risk"] == "high"
    assert structure["context_of_use"] == "internal go / no-go" and structure["locked"] == ["context_of_use"]
    assert c.put("/api/v1/projects/p1/plan/placements/po-50", headers=H,
                 json={"role": "S5", "reason": "validation"}).status_code == 200


def test_a_study_on_the_healthy_adult_default_is_a_limitation_of_the_plan(setup):
    """D-29: the person's explicit choice of the default individual is named in the plan, so the MAP and its report
    name it."""
    c, _ws, _root = setup
    limits = c.get("/api/v1/projects/p1/plan", headers=H).json()["data"]["plan"]["default_limitations"]
    assert any(l.startswith("iv-250: demographics not reported; simulated with the healthy adult default") for l in limits)


def test_the_review_shows_every_input_with_its_source_and_the_split_and_limitations_the_map_will_carry(setup):
    """Step 3 · Review & sign (redesign §3.3): read only; the split and limitations are the MAP's own."""
    from modeler_project.inputs import catalog_rows, current_cpf
    from modeler_project.plan import ModelPlan, map_from_plan

    c, ws, _root = setup
    c.get("/api/v1/projects/p1/plan", headers=H)                                   # the plan is built on first read
    answer = c.get("/api/v1/projects/p1/plan/review", headers=H)
    assert answer.status_code == 200, answer.text
    data = answer.json()["data"]
    rows = {r["id"]: r for r in data["rows"]}
    mw = rows["phys.mw"]
    assert mw["state"] == "kept" and mw["value"] == 225.2 and mw["source"]["type"] == "REGULATORY_REVIEW"
    assert mw["quote"] == "phys.mw 225.2" and mw["supplied_by"] == "person" and mw["changed_by_person"]
    assert mw["evidence_id"] and mw["confidence"] == "medium"                     # one source: not "high"
    assert data["counts"] == {"all": len(rows), "flagged": data["counts"]["flagged"], "by_person": len(rows),
                              "from_agent": 0, "open": data["counts"]["open"]}
    studies = {s["study_id"]: s for s in data["studies"]}
    assert studies["iv-250"]["role"] == "S1" and studies["ddi-itra"]["role"] == "SUPPORTIVE"
    assert studies["iv-250"]["demographics"] == "default"
    assert data["risk"] == {"tier": "medium", "set_here": False, "reason": "", "influence": None, "consequence": None,
                            "justification": None}
    # the budget split and the limitations are the ones the MAP generated from this plan carries
    plan = ModelPlan.from_content(ws.latest(ArtifactKind.MODEL_PLAN, "main").content)
    doc = map_from_plan(plan, current_cpf(ws), catalog_rows(ws))
    assert [(s["stage"], s["budget_seconds"]) for s in data["stages"]] == [(s.stage, s.budget_seconds)
                                                                         for s in doc.stage_plan]
    assert {s["stage"]: s["fraction"] for s in data["stages"]}["S3"] == 0.07
    assert data["limitations"] == list(doc.split_limitations)
    assert any("healthy adult default" in limitation for limitation in data["limitations"])
    assert c.get("/api/v1/projects/nope/plan/review", headers=H).status_code in (403, 404)


def test_the_review_shows_the_estimation_plan_the_validation_plan_and_the_tiers_criteria(setup):
    """R4b (redesign §3.3, D-34): each numeric parameter fixed or estimated with MS-01 §2.2's proposed bounds; what S4
    and S5 judge under the MAP and what follows a failure; the tier's limits and a stricter internal target only."""
    from modeler_project.inputs import catalog_rows, current_cpf
    from modeler_project.plan import ModelPlan, map_from_plan
    from pbpk_domain.campaign.map import stage_coverage

    c, ws, _root = setup
    view = c.get("/api/v1/projects/p1/plan", headers=H).json()["data"]
    for v in [v for v in view["violations"] if v["severity"] == "warning" and not v["acknowledged"]]:
        c.post(f"/api/v1/projects/p1/plan/violations/{v['id']}:acknowledge", headers=H, json={"reason": "accepted limitation"})
    data = c.get("/api/v1/projects/p1/plan/review", headers=H).json()["data"]
    estimation = {r["id"]: r for r in data["estimation"]}
    fu, logp = estimation["bind.fu"], estimation["phys.logp"]
    assert fu["estimated"] is None and fu["proposal"]["fixed"] and fu["grade"] and fu["source"]   # measured: MS-01 keeps it
    assert logp["proposal"]["basis"] == "MS-01 §2.2, measured: the start value ± 1.5" and logp["proposal"]["scale"] == "linear"
    assert data["bounds_rule"] == {"version": "0.1", "status": "UNVERIFIED", "source": 'MS-01 v1.3 §2.2 "Default bounds"'}

    # the validation plan and the criteria are the MAP's own
    plan = ModelPlan.from_content(ws.latest(ArtifactKind.MODEL_PLAN, "main").content)
    doc = map_from_plan(plan, current_cpf(ws), catalog_rows(ws))
    validation = {v["stage"]: v for v in data["validation"]}
    for stage in ("S4", "S5"):
        coverage = stage_coverage(doc, stage)
        assert [s["study_id"] for s in validation[stage]["studies"]] == list(coverage.studies)
        assert validation[stage]["skip_reason"] == coverage.skip_reason
    assert "MS-01 §6.6" in validation["S5"]["on_failure"] and "never refitted" in validation["S4"]["on_failure"]
    criteria = data["acceptance"]
    assert criteria["tier"] == "medium" and criteria["ruleset"] == doc.acceptance.ruleset and criteria["status"] == "UNVERIFIED"
    assert {q["quantity"]: q["max_fold"] for q in criteria["pk_parameters"]} == {"AUC": 1.5, "Cmax": 1.5}
    assert {q["quantity"]: q["guest_delta"] for q in criteria["ddi_ratios"]} == {"AUCR": 2, "CmaxR": 2}
    assert (criteria["min_fraction_within"], criteria["loosest_target_pe"], criteria["internal_target_pe"]) == (0.8, 33.3, None)
    assert criteria["target_applied"] is True

    # estimating logP with the proposed bounds: the estimated come first, with nothing to say
    proposal = logp["proposal"]
    fitted = c.put("/api/v1/projects/p1/plan/fits/phys.logp", headers=H, json={
        "stages": ["S1"], "lower": proposal["lower"], "upper": proposal["upper"], "scale": proposal["scale"],
        "reason": "lipophilicity drives the partition coefficients"})
    assert fitted.status_code == 200, fitted.text
    first = c.get("/api/v1/projects/p1/plan/review", headers=H).json()["data"]["estimation"][0]
    assert first["id"] == "phys.logp" and first["estimated"]["stages"] == ["S1"] and first["findings"] == []
    inverted = c.put("/api/v1/projects/p1/plan/fits/phys.logp", headers=H, json={
        "stages": ["S1"], "lower": 3, "upper": 1, "scale": "linear", "reason": "x"})
    assert inverted.status_code == 422 and "must be below the upper bound" in inverted.json()["detail"]
    fu_fit = c.put("/api/v1/projects/p1/plan/fits/bind.fu", headers=H, json={
        "stages": ["S1"], "lower": 0.05, "upper": 0.9, "scale": "log", "reason": "binding uncertain"})
    assert [f["rule"] for f in next(r for r in fu_fit.json()["data"]["violations"] if r["target"] == "bind.fu") and
            next(r for r in c.get("/api/v1/projects/p1/plan/review", headers=H).json()["data"]["estimation"]
                 if r["id"] == "bind.fu")["findings"]] == ["fit-fixed"]

    # a stricter internal target is a criterion of the MAP (R4d), no longer a limitation; a looser one blocks the signature
    c.put("/api/v1/projects/p1/plan/structure", headers=H, json={"key": "internal_target_pe", "value": 20, "reason": "tighter"})
    review = c.get("/api/v1/projects/p1/plan/review", headers=H).json()["data"]
    assert review["acceptance"]["internal_target_pe"] == 20 and review["acceptance"]["target_set_here"]
    assert not any("Internal target" in line for line in review["limitations"])
    loose = c.put("/api/v1/projects/p1/plan/structure", headers=H, json={"key": "internal_target_pe", "value": 40, "reason": "x"})
    assert any(v["rule"] == "target" and v["severity"] == "error" for v in loose.json()["data"]["violations"])
    budget = c.put("/api/v1/projects/p1/plan/structure", headers=H,
                   json={"key": "campaign_budget_seconds", "value": 36000, "reason": "a larger budget"})
    assert budget.status_code == 200, budget.text                     # a number in the changes list is shown as text
    assert {d["target"]: d["to"] for d in budget.json()["data"]["diff"]}["campaign_budget_seconds"] == "36000"


def test_the_review_shows_each_application_its_inputs_and_what_is_still_missing(setup):
    """R4c: the VBE application's inputs are set on Review & sign through the structure route, with a reason; the review
    shows the template's inputs, the values and what the validator still says."""
    c, _ws, _root = setup
    c.get("/api/v1/projects/p1/plan", headers=H)                                   # the plan is built on first read
    review = c.get("/api/v1/projects/p1/plan/review", headers=H).json()["data"]
    assert review["applications"] == {"pinned": [], "addable": []}
    assert review["application_support"] == {"rows": [], "scenarios": []}
    inputs = {"test_formulation": "Test", "reference_formulation": "Ref", "n_subjects": 24, "n_trials": 100, "seed": 7,
              "pos_threshold": 0.8, "limits": "standard",
              "variability": [{"parameter": "Organism|Lumen|Stomach|Gastric emptying time", "cv_percent": 30,
                               "source": "a cited crossover study"}]}
    set_vbe = c.put("/api/v1/projects/p1/plan/structure", headers=H, json={
        "key": "applications", "value": [{"template": "vbe-crossover", "inputs": inputs}], "reason": "the BE question"})
    assert set_vbe.status_code == 200, set_vbe.text
    [vbe] = c.get("/api/v1/projects/p1/plan/review", headers=H).json()["data"]["applications"]["pinned"]
    values = {i["id"]: i["value"] for i in vbe["inputs"]}
    assert values["n_trials"] == 100 and values["variability"][0]["cv_percent"] == 30 and values["observed_be"] is None
    assert vbe["formulations"] == [] and all("is not a CPF formulation" in p for p in vbe["problems"])
    assert len(vbe["problems"]) == 2                                   # only the two formulations are left to give
