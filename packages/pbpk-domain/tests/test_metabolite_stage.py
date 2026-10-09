"""MS-01 v1.3 §6.5 (UNVERIFIED, owner-approved 2026-10-09, D-25): a model system's metabolites are fitted to their own
data at stage SM, every analyte is its own acceptance group, and a single compound's plan is unchanged."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pbpk_domain.acceptance import Comparison, evaluate
from pbpk_domain.campaign.map import BUDGET_FRACTION, SM_BUDGET_FRACTION, generate_map, stage_coverage
from pbpk_domain.campaign.split import QuestionOfInterest, StudyRecord, split_studies
from pbpk_domain.m15 import Rating
from pbpk_domain.reference.osp_import import import_osp_system

FIXTURES = Path(__file__).resolve().parents[3] / "services" / "engine-worker" / "golden" / "fixtures"
pytestmark = pytest.mark.req("T-13")


def _map(model: str, *, system: bool = True, budget: int = 3600):
    imported = import_osp_system(json.loads((FIXTURES / f"{model}-Model.json").read_text(encoding="utf-8")))
    fitted = imported.system.parents[0]
    studies = [StudyRecord.model_validate({k: v for k, v in s.items() if k in StudyRecord.model_fields})
               for s in imported.studies if system or s.get("analyte") in (None, fitted)]
    return imported.system, generate_map(
        compound=fitted, cpf=imported.system.cpf(fitted), studies=studies,
        split=split_studies(studies, QuestionOfInterest()), objective="t", context_of_use="t",
        food_effect_in_question=False, model_risk=Rating.MEDIUM, engine_image_digest="t", software_versions={},
        system=imported.system if system else None, campaign_budget_seconds=budget)


def test_internal_metabolite_data_is_fitted_at_sm_and_reported_at_the_parent_stages():
    system, doc = _map("Itraconazole")
    sm = [s for s in doc.scenarios if s.stage == "SM"]
    assert sm and all(s.gated and system.roles[s.analyte] == "metabolite" for s in sm)
    for s in sm:  # each is the copy of a study that trains a parent stage, where it is reported
        trained = [t for t in doc.scenarios if t.study_id == s.study_id and t.stage in ("S1", "S2", "S3")]
        assert trained and not any(t.gated for t in trained)
    # S4 validates the metabolite as its own group; the parent's plasma is gated everywhere
    assert all(s.gated for s in doc.scenarios if s.stage == "S4")
    assert stage_coverage(doc, "SM").kind == "fit" and stage_coverage(doc, "SM").skip_reason is None


def test_sm_takes_ten_percent_and_the_other_stages_keep_ninety():
    _system, doc = _map("Itraconazole", budget=10_000)
    budgets = {p.stage: p.budget_seconds for p in doc.stage_plan}
    assert list(budgets)[:6] == ["S0", "S1", "S2", "S3", "SM", "SJ"]
    assert budgets["SM"] == round(10_000 * SM_BUDGET_FRACTION)
    assert budgets["S1"] == round(10_000 * BUDGET_FRACTION["S1"] * (1 - SM_BUDGET_FRACTION))
    assert abs(sum(budgets.values()) - 10_000) <= len(budgets)


def test_a_single_compound_plan_has_no_sm_and_its_budgets_are_unchanged():
    _system, doc = _map("Itraconazole", system=False, budget=10_000)
    budgets = {p.stage: p.budget_seconds for p in doc.stage_plan}
    assert "SM" not in budgets and all(s.stage != "SM" for s in doc.scenarios)
    assert budgets == {stage: round(10_000 * f) for stage, f in BUDGET_FRACTION.items()}


def test_every_analyte_is_its_own_acceptance_group():
    comparisons = [Comparison("p1", "AUC", 1.0, 1.0, "fitting", analyte="Itraconazole"),
                   Comparison("m1", "AUC", 3.0, 1.0, "fitting", analyte="Hydroxy-Itraconazole")]
    report = evaluate(comparisons, Rating.MEDIUM)
    by = {g.analyte: g for g in report.groups}
    assert by["Itraconazole"].passes and not by["Hydroxy-Itraconazole"].passes
    assert not report.passes  # a good parent fit does not hide a failing metabolite
    assert report.ruleset == "pbpk-acceptance-criteria@2026.2-draft"


def test_each_analyte_is_split_on_its_own():
    # MS-01 v1.3 §3.3 rule 7: before, Itraconazole's 24 hydroxy studies competed with the parent's in each class and all
    # landed EXTERNAL, so a metabolite never had data to train on
    _system, doc = _map("Itraconazole")
    internal = {r.study_id for r in doc.studies if r.assignment == "INTERNAL"}
    analytes = {s.analyte for s in doc.scenarios if s.study_id in internal}
    assert {"Itraconazole", "Hydroxy-Itraconazole"} <= analytes
    assert any("(rule 7)" in line for line in doc.split_rationale)
    assert any(line.startswith("Hydroxy-Itraconazole: ") for line in doc.split_rationale)
    # a single compound's split is unchanged: no prefix, no rule 7
    _s, single = _map("Itraconazole", system=False)
    assert not any("(rule 7)" in line or line.startswith("Itraconazole: ") for line in single.split_rationale)
