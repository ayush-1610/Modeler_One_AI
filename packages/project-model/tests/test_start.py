"""Step 1 · Start (redesign §3.1): scope gates (D-28), the ICH M15 model risk, what Start still needs, feasibility
warnings by field, and the data checklist derived at every brief change with no approval (D-27)."""

from __future__ import annotations

import pytest

from modeler_project import ArtifactKind, FileProjectStore, Workspace
from modeler_project.brief import FieldStatus, ProjectBrief, empty_brief
from modeler_project.brief_ops import EditError, edit_field, save_brief
from modeler_project.requirements import RequirementMatrix, derive
from modeler_project.start import checklist, gates, missing, risk, warnings

pytestmark = pytest.mark.req("T-41")

FILLED = (("qoi.text", "exposure after 10 mg"), ("qoi.context_of_use", "support a biowaiver"),
          ("qoi.applications", ["APP-01"]), ("m15.influence_rating", "medium"), ("m15.consequence_rating", "medium"),
          ("acceptance.tier", "medium"), ("drug.modality", "small_molecule"), ("scope.model_structure", "full_pbpk"),
          ("scope.site_of_action", "systemic"), ("scope.formulation_types", ["ir_solid"]), ("scenarios[0].route", "oral"),
          ("scenarios[0].food_state", "fasted"))


def _set(brief: ProjectBrief, path: str, value, note: str = "") -> ProjectBrief:
    if path == "acceptance.tier" and not note:
        note = "the model supports, does not replace, the clinical study"
    return edit_field(brief, path, value=value, status=FieldStatus.EDITED, note=note, by="u")


def _filled(**changes) -> ProjectBrief:
    brief = empty_brief("Drugol", by="u")
    for path, value in FILLED:
        brief = _set(brief, path, changes.get(path, value))
    return brief


def test_a_filled_short_brief_needs_nothing_more_and_an_empty_one_lists_it_all_in_order():
    assert missing(_filled()) == []
    assert missing(empty_brief("Drugol", by="u")) == [
        "Question of interest: not set yet", "Context of use: not set yet", "Applications: not set yet",
        "Model influence and decision consequence: not rated yet", "Model risk: not set yet", "Modality: not set yet",
        "Model type: not set yet", "Site of action: not set yet", "Formulation types: not set yet",
        "Routes: add the route of each scenario to simulate"]
    assert missing(_set(_filled(), "scenarios[1].route", "oral")) == ["Scenario 2: food state not set (oral)"]


@pytest.mark.parametrize(("path", "value", "says"), [
    ("drug.modality", "large_molecule", "Large molecule (biologic) (the builder makes PBPK models of small molecules)"),
    ("scope.model_structure", "minimal_pbpk", "Minimal PBPK (the builder makes full (whole-body) PBPK models)"),
    ("scope.site_of_action", "local", "Local (gut lumen, lung, skin, eye…) (the builder models systemic exposure)"),
    ("scope.formulation_types", ["ir_solid", "dr_solid"],
     "Delayed-release (enteric-coated) (the builder models dissolved, particle and Weibull formulations)"),
    ("scenarios[0].route", "subcutaneous", "subcutaneous administration (the builder makes IV and oral administrations)"),
])
def test_what_the_builder_cannot_model_is_refused_at_start(path, value, says):
    brief = _filled(**{path: value})
    refused = [g for g in gates(brief) if g.state == "not_supported"]
    assert [g.message for g in refused] == [f"Not supported yet: {says}"]
    assert missing(brief) == [f"Not supported yet: {says}"]


def test_extended_release_solids_and_suspensions_are_supported():
    brief = _filled(**{"scope.formulation_types": ["iv_solution", "oral_suspension", "er_solid"]})
    assert {g.id: g.state for g in gates(brief)}["scope.formulation_types"] == "supported"


def test_the_m15_ratings_bound_the_model_risk_the_person_sets():
    brief = empty_brief("Drugol", by="u")
    assert risk(brief).allowed == () and risk(brief).suggested is None
    brief = _set(_set(brief, "m15.influence_rating", "high"), "m15.consequence_rating", "high")
    assert risk(brief).allowed == ("high",) and risk(brief).suggested == "high"
    with pytest.raises(EditError, match="admits a model risk of high, not low"):
        _set(brief, "acceptance.tier", "low")
    brief = _set(brief, "m15.consequence_rating", "low")             # different ratings: any risk between, with reasons
    assert risk(brief).allowed == ("low", "medium", "high") and risk(brief).suggested is None
    brief = _set(brief, "acceptance.tier", "medium", note="driven by the influence: the model replaces a study arm")
    assert risk(brief).tier == "medium" and risk(brief).reasons.startswith("driven by")
    # a later rating that no longer admits the risk set is flagged, not overwritten
    brief = _set(brief, "m15.consequence_rating", "high")
    assert risk(brief).problem == ("with model influence high and decision consequence high, ICH M15 admits a model risk "
                                   "of high, not medium")
    assert f"Model risk: {risk(brief).problem}" in missing(brief)


def test_feasibility_warnings_sit_beside_the_field_they_concern():
    brief = _set(_filled(), "scope.pathways_stated", "UGT1A9 and CYP9Z9 metabolism")
    brief = _set(brief, "products[0].name", "50 mg ER tablet")
    brief = _set(brief, "products[0].role", "TEST")
    brief = _set(brief, "products[0].release", "ER")
    found = warnings(brief)
    assert any(w.startswith("expression profile: CYP9Z9: needs harvest") for w in found["scope.pathways"])
    assert any(w.startswith("50 mg ER tablet: ER release: limited") for w in found["products"])
    assert "drug.modality" not in found                                # a scope gate says it already


def test_the_pathways_multi_select_decides_the_conditional_items():
    def applies(brief, req_id):
        return derive(brief).get(req_id).applies

    brief = _filled()
    assert applies(brief, "REQ-elim.renal") == "undetermined"
    assert applies(_set(brief, "scope.pathways", ["renal_filtration"]), "REQ-elim.renal") == "yes"
    assert applies(_set(brief, "scope.pathways", ["hepatic_metabolism"]), "REQ-elim.renal") == "no"
    assert applies(_set(brief, "scope.pathways", ["other"]), "REQ-elim.renal") == "no"


@pytest.mark.req("T-42")
def test_every_stored_brief_re_derives_the_checklist_with_no_approval(tmp_path):
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    first = save_brief(ws, empty_brief("Drugol", by="u"), actor="u", reason="project started")
    plan = ws.latest(ArtifactKind.REQUIREMENTS, "main")
    assert plan is not None and plan.derived_from == (first.ref,)
    brief = _set(_filled(), "data_plan[0].item", "clinical PK of study EX-101")
    brief = _set(brief, "data_plan[0].category", "clinical_pk_oral")
    brief = _set(brief, "data_plan[0].provider", "CLIENT")
    second = save_brief(ws, brief, actor="u", reason="filled at Start")
    current = ws.latest(ArtifactKind.REQUIREMENTS, "main")
    assert current.derived_from == (second.ref,) and ws.status(current).value == "DRAFT"   # current, never approved
    assert current.reason == "derived from brief v2 (filled at Start)"
    shown = checklist(ws)
    matrix = RequirementMatrix.from_content(current.content)
    assert shown.version == current.version and not shown.stale
    assert {i.req_id for i in shown.items} == {i.req_id for i in matrix.items if i.applies != "no"}
    po = next(i for i in shown.items if i.req_id == "REQ-obs.po_fasted_range")
    assert po.provider == "CLIENT" and po.provider_statement == "clinical PK of study EX-101" and po.status == "MISSING"
    assert shown.expected_from_client >= 1 and shown.delivered_by_client == 0
