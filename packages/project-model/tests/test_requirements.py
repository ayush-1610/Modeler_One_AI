"""T-42 / T-43: the data plan derived from the brief, and the feasibility check."""

from __future__ import annotations

import pytest

from modeler_project import ArtifactKind, FileProjectStore, Workspace
from modeler_project.brief import Citation, FieldStatus, empty_brief
from modeler_project.brief_ops import agent_set, edit_field
from modeler_project.data_plan import NoBriefError, derive_data_plan
from modeler_project.feasibility import check
from modeler_project.requirements import (
    RequirementMatrix,
    RequirementOverride,
    application_additions,
    client_items,
    client_request,
    derive,
    evaluate_when,
    literature_items,
)

CITE = (Citation(doc_sha256="a" * 64, page=1, quote="quoted from the proposal"),)


def _set(brief, path, value):
    return agent_set(brief, path, value=value, unit=None, citations=CITE, status=FieldStatus.EXTRACTED, confidence="A", by="a1")


def _vbe_brief():
    b = empty_brief("Dapagliflozin", by="u")
    for path, value in [
        ("drug.modality", "small_molecule"), ("drug.bcs_class", "III"),
        ("qoi.applications", ["APP-14"]),
        ("products[0].name", "Test 10 mg tablet"), ("products[0].role", "TEST"), ("products[0].release", "IR"),
        ("products[1].name", "Farxiga 10 mg tablet"), ("products[1].role", "RLD"), ("products[1].release", "IR"),
        ("scenarios[0].population", "healthy adults"), ("scenarios[0].route", "oral"), ("scenarios[0].dose", 10),
        ("scenarios[0].food_state", "fasted"),
        ("data_plan[0].item", "dissolution in three media"), ("data_plan[0].category", "dissolution"),
        ("data_plan[0].provider", "CLIENT"), ("data_plan[0].purpose", "model_building"),
        ("data_plan[1].item", "pivotal BE study NG-01 individual data"), ("data_plan[1].category", "rld_data"),
        ("data_plan[1].provider", "CLIENT"), ("data_plan[1].purpose", "external_validation"),
        ("data_plan[2].item", "physicochemical parameters"), ("data_plan[2].category", "physchem"),
        ("data_plan[2].provider", "LITERATURE"),
        ("scope.pathways_stated", "UGT1A9 metabolism; renal excretion of the glucuronide"),
    ]:
        b = _set(b, path, value)
    return b


@pytest.mark.req("T-42")
def test_conditions_are_true_false_or_undetermined():
    b = _vbe_brief()
    assert evaluate_when({"route": ["oral"]}, b) is True
    assert evaluate_when({"bcs": ["II", "IV"]}, b) is False
    assert evaluate_when({"nonlinear": True}, b) is None  # the brief does not say
    assert evaluate_when({"route": ["oral"], "bcs": ["II"]}, b) is False


@pytest.mark.req("T-42")
def test_nonlinearity_yes_no_and_not_stated():
    # page review 1: "no" (not applicable) is linear PK, so Km and Vmax are not asked; nothing said stays undetermined
    b = _vbe_brief()
    assert evaluate_when({"nonlinear": True}, b) is None
    linear = edit_field(b, "scope.nonlinearity", status=FieldStatus.NOT_APPLICABLE, by="u")
    assert evaluate_when({"nonlinear": True}, linear) is False and evaluate_when({"nonlinear": False}, linear) is True
    stated = _set(b, "scope.nonlinearity", "saturable absorption above 50 mg")
    assert evaluate_when({"nonlinear": True}, stated) is True


@pytest.mark.req("T-42")
def test_each_application_names_the_data_it_adds():
    adds = application_additions()
    assert {"Meal composition of each fed study", "FaSSIF / FeSSIF solubility"} <= set(adds["APP-12"])
    assert "APP-01" not in adds  # the core template applies to every project, so an application adds nothing of its own


@pytest.mark.req("T-42")
def test_matrix_takes_providers_from_the_proposals_data_plan_and_repeats_per_product():
    matrix = derive(_vbe_brief())
    assert any(t.startswith("req-app-vbe@") for t in matrix.templates)
    release = [i for i in matrix.items if i.req_id.startswith("REQ-form.release@")]
    assert [i.product for i in release] == ["Test 10 mg tablet", "Farxiga 10 mg tablet"]
    assert all(i.provider == "CLIENT" and i.provider_source == "data_plan[0]" for i in release)
    assert release[0].provider_statement == "dissolution in three media"
    logp = matrix.get("REQ-phys.logp")
    assert (logp.provider, logp.provider_source) == ("LITERATURE", "data_plan[2]")
    assert matrix.get("REQ-phys.solubility.table").applies == "no"   # BCS III
    assert matrix.get("REQ-perm.intestinal").applies == "yes"        # oral
    assert matrix.get("REQ-elim.renal").applies == "yes"             # "renal" stated
    assert matrix.get("REQ-elim.mm").applies == "undetermined"
    assert matrix.get("REQ-vbe.be_study").provider == "CLIENT"
    assert matrix.get("REQ-ddi.inhibition") is None                  # no DDI application


@pytest.mark.req("T-42")
def test_overrides_are_kept_across_rederivation_and_drive_what_p2_searches():
    b = _vbe_brief()
    first = derive(b)
    override = RequirementOverride(req_id="REQ-form.release@test-10-mg-tablet", cross_check=True,
                                   reason="check the client's dissolution against the label", by="u")
    second = derive(b, (override,), previous=first)
    item = second.get("REQ-form.release@test-10-mg-tablet")
    assert item.cross_check and item.provider == "CLIENT"
    assert item in literature_items(second) and item in client_items(second)
    switched = derive(b, (RequirementOverride(req_id="REQ-phys.logp", provider="CLIENT", reason="client measured it", by="u"),))
    assert switched.get("REQ-phys.logp").provider_source == "override"


@pytest.mark.req("T-43")
def test_feasibility_reports_what_the_builder_cannot_produce_yet():
    b = _vbe_brief()
    b = edit_field(b, "scenarios[0].route", value="inhalation", status=FieldStatus.EDITED, note="test", by="u")
    b = _set(b, "scope.pathways_stated", "UGT1A9 and CYP9Z9 metabolism; biliary excretion")
    report = check(b)
    status = {line.feature: line.status for line in report.lines}
    assert status["small-molecule PBPK model"] == "SUPPORTED"
    assert status["route: inhalation"] == "NOT_SUPPORTED"
    assert status["expression profile: UGT1A9"] == "SUPPORTED"
    assert status["expression profile: CYP9Z9"] == "NEEDS_HARVEST"
    assert status["biliary / tubular-secretion clearance"] == "NEEDS_HARVEST"
    assert status["application: virtual bioequivalence"] == "LIMITED"
    assert len(report.blocking) == 3
    empty = check(empty_brief("X", by="u"))
    assert {line.status for line in empty.lines} == {"UNDETERMINED"}


@pytest.mark.req("T-42")
def test_the_data_plan_service_derives_from_the_latest_brief_and_keeps_overrides(tmp_path):
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    with pytest.raises(NoBriefError, match="no brief to derive the data plan from"):
        derive_data_plan(ws, actor="u", reason="derived")
    brief = ws.commit(ArtifactKind.BRIEF, "main", _vbe_brief().to_content(), actor="u", reason="drafted")
    override = RequirementOverride(req_id="REQ-phys.logp", provider="CLIENT", reason="client measured it", by="u")
    derive_data_plan(ws, actor="u", reason="derived")
    derive_data_plan(ws, actor="u", reason="REQ-phys.logp: client measured it", extra=override)
    derive_data_plan(ws, actor="u", reason="re-derived")
    matrix_version = ws.latest(ArtifactKind.REQUIREMENTS, "main")
    matrix = RequirementMatrix.from_content(matrix_version.content)
    assert matrix.overrides == (override,) and matrix.get("REQ-phys.logp").provider == "CLIENT"
    feasibility = ws.latest(ArtifactKind.FEASIBILITY, "main")
    assert feasibility.content == check(_vbe_brief()).to_content()
    assert matrix_version.derived_from == (brief.ref,) and feasibility.derived_from == (brief.ref,)


def test_the_pathway_kinds_decide_the_pathway_items_a_list_of_enzymes_alone_would_not():
    """`scope.pathways` (Start): a brief that names only its enzymes still says whether the drug is cleared renally, so
    the renal items are neither dropped nor left undetermined."""
    b = _set(empty_brief("X", by="u"), "drug.modality", "small_molecule")
    assert derive(b).get("REQ-elim.renal").applies == "undetermined"
    enzymes = _set(b, "scope.pathways_stated", ["UGT1A9"])
    assert derive(enzymes).get("REQ-elim.renal").applies == "no"                       # the enzyme names say nothing renal
    kinds = edit_field(enzymes, "scope.pathways", value=["hepatic_metabolism", "renal_filtration"], status=FieldStatus.EDITED,
                       by="u")
    assert derive(kinds).get("REQ-elim.renal").applies == "yes"
    only_hepatic = edit_field(b, "scope.pathways", value=["hepatic_metabolism"], status=FieldStatus.EDITED, by="u")
    assert derive(only_hepatic).get("REQ-elim.renal").applies == "no"


def test_the_client_request_lists_what_only_the_client_sends_with_what_it_serves_and_where_it_goes():
    # page review 1 (the owner's decision 2b of 2026-10-29): the CRO's day-one data request, from the data plan
    matrix = derive(_vbe_brief())
    request = client_request(matrix)
    assert [line.req_id for line in request] == [i.req_id for i in client_items(matrix)]      # what the arrival check expects
    by_id = {(line.req_id, line.product): line for line in request}
    be = next(line for line in request if line.req_id == "REQ-vbe.be_study")
    assert be.why == "absorption and formulation and virtual bioequivalence" and be.required
    assert be.sheet == "PK_Individual or PK_Summary"
    dissolution = [line for line in request if line.req_id == "REQ-vbe.rld_dissolution"]
    assert dissolution and all(line.sheet == "Dissolution and Product" for line in dissolution)
    assert all(line.why for line in by_id.values())
