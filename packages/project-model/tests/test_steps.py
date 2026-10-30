"""The four steps of the redesigned flow read from content, not approvals (redesign §3, D-27); Start's short brief,
ICH M15 model risk and scope gates (D-28)."""

from __future__ import annotations

import pytest

from modeler_project import ArtifactKind, FileProjectStore, Workspace
from modeler_project.brief import FieldStatus, add_question, empty_brief, risk_check
from modeler_project.brief_ops import agent_set, edit_field
from modeler_project.feasibility import check, pathways_not_named, scope_gates
from modeler_project.map_artifact import MapArtifact, MapSignature
from modeler_project.steps import project_steps, run_step, start_issues, start_problems

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


def _fill(brief, *pairs):
    for path, value in pairs:
        brief = edit_field(brief, path, value=value, status=FieldStatus.EDITED, by="u")
    return brief


SHORT = (("qoi.text", "exposure after 10 mg"), ("qoi.context_of_use", "support a biowaiver"),
         ("qoi.applications", ["APP-14"]), ("drug.modality", "small_molecule"), ("scope.pbpk_model", "full"),
         ("scope.site_of_action", "systemic"), ("scope.formulation_types", ["ir_tablet"]), ("scenarios[0].route", "oral"),
         ("m15.influence", "the biowaiver rests on the model alone"),
         ("m15.consequence", "an untested product would reach patients"))


def test_start_is_done_when_the_short_brief_the_model_risk_and_the_scope_gates_are_set_with_no_approval(tmp_path):
    ws = _ws(tmp_path)
    brief = empty_brief("Drugol", by="u")
    ws.commit(ArtifactKind.BRIEF, "main", brief.to_content(), actor="u", reason="start")
    start = project_steps(ws, [])[0]
    assert start.state == "needs_you"
    assert {"Question of interest: not set yet", "Model risk: not set yet (it is never assumed)",
            "Model influence: not rated yet", "PBPK model: not set yet", "Routes: not set yet"} <= set(start.reasons)
    brief = _fill(brief, *SHORT, ("m15.influence_rating", "medium"), ("m15.consequence_rating", "high"),
                  ("acceptance.tier", "high"))
    assert start_problems(brief) == ["Why this model risk: influence and consequence differ, so say why it is high"]
    brief = _fill(brief, ("m15.risk_justification", "a wrong biowaiver exposes patients to an untested product"))
    ws.commit(ArtifactKind.BRIEF, "main", brief.to_content(), actor="u", reason="filled")
    assert _states(ws)["start"] == "done"                                 # the brief was never approved


def test_start_refuses_what_the_builder_cannot_model_yet():
    """D-28: a minimal PBPK model, a local site of action, a liposome, an inhaled route are refused at Start."""
    brief = _fill(empty_brief("Drugol", by="u"), *SHORT, ("m15.influence_rating", "low"),
                  ("m15.consequence_rating", "low"), ("acceptance.tier", "low"), ("scope.pbpk_model", "minimal"),
                  ("scope.site_of_action", "local"), ("scope.formulation_types", ["ir_tablet", "liposome", "mr"]),
                  ("scenarios[1].route", "inhalation"))
    gates = {g.gate: g for g in scope_gates(brief)}
    assert {k: g.state for k, g in gates.items()} == {"modality": "supported", "pbpk_model": "not_supported",
                                                      "site_of_action": "not_supported",
                                                      "formulation_types": "not_supported", "routes": "not_supported"}
    assert gates["formulation_types"].message.startswith("liposome: not supported yet; modified release: extended")
    assert start_problems(brief) == [
        "PBPK model: minimal PBPK: not supported yet",
        "Site of action: local: not supported yet: a local site of action needs a site model the builder does not make",
        f"Formulation types: {gates['formulation_types'].message}", "Routes: inhalation: not supported yet"]
    feasibility = {line.needed_because: line.status for line in check(brief).lines}
    assert feasibility["scope.pbpk_model"] == feasibility["scope.formulation_types"] == "NOT_SUPPORTED"
    # an IV-only project: no formulation type applies, and modified release alone is limited, not refused
    iv = edit_field(_fill(brief, ("scope.pbpk_model", "full"), ("scope.site_of_action", "systemic")), "scenarios[1].route",
                    value="iv_infusion", status=FieldStatus.EDITED, by="u")
    iv = edit_field(iv, "scope.formulation_types", status=FieldStatus.NOT_APPLICABLE, by="u")
    assert start_problems(iv) == [] and {g.gate: g.state for g in scope_gates(iv)}["formulation_types"] == "supported"
    assert {g.gate: g.state for g in scope_gates(_fill(iv, ("scope.formulation_types", ["mr"])))}["formulation_types"] \
        == "limited"


@pytest.mark.parametrize(("influence", "consequence", "tier", "allowed", "refused"), [
    ("low", "low", "low", ("low",), False), ("high", "high", "medium", ("high",), True),
    ("low", "high", "medium", ("low", "medium", "high"), False), ("medium", "low", "high", ("low", "medium"), True)])
def test_the_model_risk_lies_in_the_range_its_m15_ratings_admit(influence, consequence, tier, allowed, refused):
    brief = _fill(empty_brief("Drugol", by="u"), ("m15.influence_rating", influence),
                  ("m15.consequence_rating", consequence), ("acceptance.tier", tier))
    check_ = risk_check(brief)
    assert check_.allowed == allowed and bool(check_.refused) is refused


def test_open_questions_on_the_short_brief_hold_start_up_and_proposal_notes_never_do():
    brief = _fill(empty_brief("Drugol", by="u"), *SHORT, ("m15.influence_rating", "low"), ("m15.consequence_rating", "low"),
                  ("acceptance.tier", "low"))
    brief = add_question(add_question(brief, "drug.mw_free_base", "the stated MW differs from the structure's",
                                      raised_by="system"), "proj.client", "Who is the sponsor?", raised_by="agent:a1")
    question = "Open question on Molecular weight (free base): the stated MW differs from the structure's"
    assert start_problems(brief) == [question]


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


def test_each_start_issue_names_the_field_it_belongs_to_so_the_screen_marks_it():
    # page review 1: no side panel; the screen marks the field each issue belongs to
    brief = _fill(empty_brief("Drugol", by="u"), *SHORT, ("m15.influence_rating", "medium"),
                  ("m15.consequence_rating", "medium"), ("acceptance.tier", "medium"))
    assert start_issues(brief) == []
    looser = _fill(brief, ("acceptance.internal_target_pe", 40))
    (issue,) = start_issues(looser)
    assert issue.path == "acceptance.internal_target_pe" and issue.message.startswith("Internal target: at most 33.3 %")
    assert start_issues(_fill(brief, ("acceptance.internal_target_pe", 20))) == []
    unset = start_issues(empty_brief("Drugol", by="u"))
    assert {"qoi.text", "acceptance.tier", "drug.modality", "scenarios"} <= {i.path.split("[")[0] for i in unset}
    assert [i.message for i in unset] == start_problems(empty_brief("Drugol", by="u"))


def test_a_pathway_the_published_model_places_and_the_proposal_does_not_name_is_flagged():
    brief = _fill(empty_brief("Drugol", by="u"), ("scope.pathways_stated", ["UGT1A9 glucuronidation"]),
                  ("scope.pathways", ["hepatic_metabolism"]))
    targets = ["elim.hepatic.UGT1A9.clspec", "elim.hepatic.UGT2B7.clspec", "elim.renal.gfr_fraction", "phys.logp"]
    assert pathways_not_named(brief, targets) == ["UGT2B7", "renal elimination"]
    named = _fill(brief, ("scope.pathways", ["hepatic_metabolism", "renal_filtration"]),
                  ("scope.pathways_stated", ["UGT1A9 glucuronidation", "UGT2B7"]))
    assert pathways_not_named(named, targets) == []


def test_why_each_rating_is_what_it_is_needs_a_persons_word():
    # page review 1 (the owner's decision 1b of 2026-10-29): the agent's draft waits on a person, and so do the proposal's words
    brief = _fill(empty_brief("Drugol", by="u"), *SHORT[:-2], ("m15.influence_rating", "high"),
                  ("m15.consequence_rating", "high"), ("acceptance.tier", "high"))
    unwritten = {i.path: i.message for i in start_issues(brief)}
    assert unwritten == {"m15.influence": "How the model is used: not written yet (ICH M15 asks why the rating is what it is)",
                         "m15.consequence": "What a wrong decision means: not written yet (ICH M15 asks why the rating is what "
                                            "it is)"}
    drafted = agent_set(brief, "m15.influence", value="the biowaiver rests on the model alone", unit=None, citations=(),
                        status=FieldStatus.DRAFTED, confidence=None, by="agent:a1")
    drafted = agent_set(drafted, "m15.consequence", value="an untested product would reach patients", unit=None,
                        citations=(), status=FieldStatus.EXTRACTED, confidence="A", by="agent:a1")
    assert {i.path: i.message for i in start_issues(drafted)} == {
        "m15.influence": "How the model is used: confirm the intake agent's draft, or change it",
        "m15.consequence": "What a wrong decision means: confirm the proposal's words, or change them"}
    for path in ("m15.influence", "m15.consequence"):
        drafted = edit_field(drafted, path, status=FieldStatus.CONFIRMED, by="u")
    assert start_issues(drafted) == []
