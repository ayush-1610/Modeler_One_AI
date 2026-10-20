"""Step 3 · Review & sign (redesign §3.3): who supplied a value, a display-only confidence, and the limitations the MAP
names (the brief's assumptions among them)."""

from __future__ import annotations

import pytest

from modeler_project.brief import FieldStatus, empty_brief
from modeler_project.brief_ops import edit_field
from modeler_project.plan import ModelPlan, Structure, Violation, map_limitations, structure_from_brief
from modeler_project.review import application_support, applications, confidence, counts, supplier

pytestmark = pytest.mark.req("T-50")


def test_who_supplied_a_value():
    assert supplier({"proposed_by": "agent:run-1"}) == "agent"
    assert supplier({"proposed_by": "u1", "extraction": "CELL", "source_type": "CLIENT_REPORT"}) == "client file"
    assert supplier({"proposed_by": "u1", "extraction": "TEXT", "source_type": "CLIENT_FILE"}) == "client file"
    assert supplier({"proposed_by": "u1", "extraction": "TEXT", "source_type": "PUBLICATION"}) == "person"
    assert supplier({"proposed_by": ""}) == "system"


def test_confidence_is_display_only_from_grade_flags_and_agreement():
    assert confidence("missing", None, 0) is None
    assert confidence("kept", {"confidence": "A", "flags": []}, 1) == "high"
    assert confidence("kept", {"confidence": "A", "flags": []}, 0) == "medium"     # one source, however good
    assert confidence("kept", {"confidence": "C", "flags": []}, 2) == "medium"
    assert confidence("kept", {"confidence": "B", "flags": ["check: species"]}, 3) == "low"
    assert confidence("kept", {"confidence": "D", "flags": []}, 2) == "low"
    assert confidence("held", {"confidence": "A", "flags": []}, 2) == "low"


def test_the_filters_count_flagged_rows_a_persons_values_and_an_agents():
    rows = [{"state": "kept", "flags": [], "changed_by_person": True, "supplied_by": "person"},
            {"state": "kept", "flags": ["check: x"], "changed_by_person": False, "supplied_by": "agent"},
            {"state": "conflict", "flags": [], "changed_by_person": False, "supplied_by": "agent"},
            {"state": "missing", "flags": [], "changed_by_person": False, "supplied_by": None}]
    assert counts(rows) == {"all": 4, "flagged": 2, "by_person": 1, "from_agent": 2, "open": 2}


def test_the_briefs_assumptions_and_the_accepted_warnings_are_limitations_of_the_map():
    brief = edit_field(empty_brief("Drugol", by="u"), "notes.assumptions", value=["linear PK up to 100 mg"],
                       status=FieldStatus.EDITED, by="u")
    structure = structure_from_brief(brief)
    assert structure.assumptions == ("linear PK up to 100 mg",)
    plan = ModelPlan(compound="Drugol", studies=(), placements={}, structure=structure,
                     default_limitations=("po-10: simulated with the healthy adult default (D-29)",))
    accepted = Violation(id="w1", severity="warning", rule="rule-7", target="po-10", message="one fasted dose level",
                         acknowledged="a limitation of the proof")
    open_warning = Violation(id="w2", severity="warning", rule="rule-8", target="po-50", message="not acknowledged")
    assert map_limitations(plan, [accepted, open_warning]) == (
        "po-10: simulated with the healthy adult default (D-29)",
        "Assumption stated in the brief: linear PK up to 100 mg",
        "one fasted dose level — acknowledged: a limitation of the proof")
    assert map_limitations(plan.model_copy(update={"structure": Structure()}), []) == plan.default_limitations


def _brief_with_applications():
    brief = edit_field(empty_brief("Drugol", by="u"), "qoi.applications", status=FieldStatus.EDITED, by="u",
                       value=["APP-03 enzyme DDI", "APP-12 food effect", "APP-14 virtual bioequivalence"])
    brief = edit_field(brief, "scenarios[0].route", value="oral", status=FieldStatus.EDITED, by="u")
    brief = edit_field(brief, "scenarios[0].dose", value=10, unit="mg", status=FieldStatus.EDITED, by="u")
    return edit_field(brief, "scenarios[0].regimen", value="MD, 10 mg twice daily", status=FieldStatus.EDITED, by="u")


def test_each_application_says_what_the_campaign_does_with_it_and_the_scenarios_are_listed():
    brief = _brief_with_applications()
    plan = ModelPlan(compound="Drugol", studies=(), placements={}, structure=structure_from_brief(brief))
    support = application_support(plan, brief)
    assert [(r["code"], r["status"]) for r in support["rows"]] == [
        ("APP-03", "not_supported"), ("APP-12", "partial"), ("APP-14", "runs")]
    assert support["rows"][0]["label"] == "APP-03 enzyme DDI"
    assert support["scenarios"] == [{"route": "oral", "dose": 10, "regimen": "MD, 10 mg twice daily"}]


def test_the_vbe_application_shows_its_inputs_what_is_missing_and_the_choices():
    from pbpk_domain.cpf import CPF, ParameterRecord, ParameterStatus

    brief = _brief_with_applications()
    plan = ModelPlan(compound="Drugol", studies=(), placements={}, structure=structure_from_brief(brief))
    cpf = CPF(compound="Drugol", parameters=tuple(
        ParameterRecord(id=f"form.{n}.weibull.t50", value=30.0, unit="min", status=ParameterStatus.FIXED) for n in ("Test", "Ref")))
    missing = Violation(id="application:vbe-crossover:1", severity="error", rule="application", target="vbe-crossover:1",
                        message="vbe-crossover: Virtual trials: not given (required; never defaulted)")
    view = applications(plan, cpf, [missing])
    [vbe] = view["pinned"]
    assert (vbe["template"], vbe["status"]) == ("vbe-crossover", "DRAFT") and view["addable"] == []
    by_id = {i["id"]: i for i in vbe["inputs"]}
    assert by_id["n_trials"]["never_default"] and by_id["n_trials"]["value"] is None
    assert by_id["limits"]["default"] == "standard" and not by_id["observed_be"]["required"]
    assert vbe["problems"] == [missing.message] and vbe["formulations"] == ["Ref", "Test"]
    limits = {lim["id"]: lim for lim in vbe["limits"]}
    assert limits["standard"]["verified"] and not limits["nti"]["verified"]
    without = plan.model_copy(update={"structure": plan.structure.model_copy(update={"applications": ()})})
    assert applications(without, cpf, [])["addable"] == ["vbe-crossover"]     # the brief lists APP-14
