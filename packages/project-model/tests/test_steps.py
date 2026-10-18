"""The four steps of the redesigned flow read from content, not approvals (redesign §3, D-27)."""

from __future__ import annotations

import pytest

from modeler_project import ArtifactKind, FileProjectStore, Workspace
from modeler_project.brief import FieldStatus, empty_brief
from modeler_project.brief_ops import edit_field
from modeler_project.map_artifact import MapArtifact, MapSignature
from modeler_project.steps import project_steps, run_step

pytestmark = pytest.mark.req("T-50")


def _ws(tmp_path) -> Workspace:
    return Workspace(FileProjectStore(tmp_path), "t1", "p1")


def _states(ws, campaigns=()) -> dict[str, str]:
    return {s.step: s.state for s in project_steps(ws, list(campaigns))}


def test_a_new_project_has_every_step_ahead_of_it(tmp_path):
    steps = project_steps(_ws(tmp_path), [])
    assert [(s.step, s.label, s.state) for s in steps] == [
        ("start", "Start", "not_started"), ("inputs", "Inputs", "not_started"),
        ("review", "Review & sign", "not_started"), ("run", "Run", "not_started")]


# What Start needs (redesign §3.1): the question, the ICH M15 ratings and risk, the scope gates and the routes.
START = (("qoi.text", "exposure after 10 mg"), ("qoi.context_of_use", "support a biowaiver"),
         ("qoi.applications", ["APP-01"]), ("m15.influence_rating", "medium"), ("m15.consequence_rating", "medium"),
         ("acceptance.tier", "medium"), ("drug.modality", "small_molecule"), ("scope.model_structure", "full_pbpk"),
         ("scope.site_of_action", "systemic"), ("scope.formulation_types", ["ir_solid"]), ("scenarios[0].route", "oral"),
         ("scenarios[0].food_state", "fasted"))


def test_start_is_done_when_the_short_brief_is_filled_with_no_approval(tmp_path):
    ws = _ws(tmp_path)
    brief = empty_brief("Drugol", by="u")
    ws.commit(ArtifactKind.BRIEF, "main", brief.to_content(), actor="u", reason="start")
    start = project_steps(ws, [])[0]
    assert start.state == "needs_you"
    assert "Model risk: not set yet" in start.reasons                    # never assumed: it is asked for
    assert "Model type: not set yet" in start.reasons                    # a scope gate of D-28
    for path, value in START:
        brief = edit_field(brief, path, value=value, status=FieldStatus.EDITED, by="u",
                           note="medium influence and consequence" if path == "acceptance.tier" else "")
    ws.commit(ArtifactKind.BRIEF, "main", brief.to_content(), actor="u", reason="filled")
    assert _states(ws)["start"] == "done"                                 # the brief was never approved
    refused = edit_field(brief, "scope.model_structure", value="minimal_pbpk", status=FieldStatus.EDITED, by="u")
    ws.commit(ArtifactKind.BRIEF, "main", refused.to_content(), actor="u", reason="minimal PBPK")
    start = project_steps(ws, [])[0]
    assert start.state == "needs_you" and start.reasons == (
        "Not supported yet: Minimal PBPK (the builder makes full (whole-body) PBPK models)",)


def test_inputs_follow_the_latest_readiness_check(tmp_path):
    ws = _ws(tmp_path)
    ws.commit(ArtifactKind.READINESS, "main", {"ready": False, "checks": [{"check": "S0 completeness (MS-01 §2.2)",
                                                                           "ok": False, "detail": ["phys.mw"]}]},
              actor="u", reason="not ready")
    inputs = project_steps(ws, [])[1]
    assert inputs.state == "needs_you" and inputs.reasons == ("S0 completeness (MS-01 §2.2)",)
    ws.commit(ArtifactKind.READINESS, "main", {"ready": True, "checks": []}, actor="u", reason="ready")
    assert _states(ws)["inputs"] == "done"


def test_review_is_done_only_with_a_signed_map(tmp_path):
    ws = _ws(tmp_path)
    ws.commit(ArtifactKind.MODEL_PLAN, "main", {"plan": "draft"}, actor="u", reason="default plan")
    assert _states(ws)["review"] == "needs_you"
    signed = MapArtifact(map={"compound": "Drugol"}, map_sha256="a" * 64,
                         signature=MapSignature(signature_id="s1", manifestation="Dev User, Approved"))
    ws.commit(ArtifactKind.MAP, "main", signed.to_content(), actor="u", reason="signed")
    assert _states(ws)["review"] == "done"


@pytest.mark.parametrize(("statuses", "state"), [
    ([], "not_started"), (["RUNNING"], "running"), (["COMPLETED", "ESCALATED"], "needs_you"),
    (["AWAITING_SIGNATURE"], "needs_you"), (["COMPLETED"], "done"), (["FAILED"], "needs_you")])
def test_run_follows_the_projects_campaigns(statuses, state):
    assert run_step(statuses).state == state
