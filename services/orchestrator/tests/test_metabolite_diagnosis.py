"""Each study diagnoses the compounds it informs (MS-01 v1.3 §6.5, diag-rules 0.6): a metabolite's data its own
clearance or the rate that forms it, a racemic sum both enantiomers'. On the published OSP Itraconazole and Verapamil
systems (fixtures/SOURCES.md); the fit policies are the test's, as a project's model plan would set them."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from modeler_contracts.runs import RoundContext, RoundEvaluation
from modeler_orchestrator.campaign_activities import diagnose_round
from pbpk_domain.campaign.map import generate_map
from pbpk_domain.campaign.split import QuestionOfInterest, StudyRecord, split_studies
from pbpk_domain.cpf.models import FitPolicy, Scale
from pbpk_domain.m15 import Rating
from pbpk_domain.reference.osp_import import import_osp_system

FIXTURES = Path(__file__).resolve().parents[2] / "engine-worker" / "golden" / "fixtures"
pytestmark = pytest.mark.req("T-14")


def _with_policies(system, policies: dict[str, dict[str, tuple[str, ...]]]):
    """The system with fit policies on the named parameters, per compound: {compound: {id: stages}}."""
    compounds = []
    for cpf in system.compounds:
        wanted = policies.get(cpf.compound, {})
        records = tuple(p.model_copy(update={"fit_policy": FitPolicy(stage=wanted[p.id], lower=float(p.value) * 0.1,
                                                                       upper=float(p.value) * 10 or 1.0, scale=Scale.LOG)})
                        if p.id in wanted else p for p in cpf.parameters)
        compounds.append(cpf.model_copy(update={"parameters": records}))
    return system.model_copy(update={"compounds": tuple(compounds)})


def _campaign(tmp_path: Path, model: str, policies) -> tuple[RoundContext, object, object]:
    imported = import_osp_system(json.loads((FIXTURES / f"{model}-Model.json").read_text(encoding="utf-8")))
    system = _with_policies(imported.system, policies)
    fitted = system.parents[0]
    studies = [StudyRecord.model_validate({k: v for k, v in s.items() if k in StudyRecord.model_fields})
               for s in imported.studies]
    doc = generate_map(compound=fitted, cpf=system.cpf(fitted), studies=studies,
                       split=split_studies(studies, QuestionOfInterest()), objective="t", context_of_use="t",
                       food_effect_in_question=False, model_risk=Rating.MEDIUM, engine_image_digest="t",
                       software_versions={}, system=system)
    for name, text in (("cpf.json", system.cpf(fitted).model_dump_json()), ("system.json", system.model_dump_json()),
                       ("map.json", doc.model_dump_json())):
        (tmp_path / name).write_text(text, encoding="utf-8")
    ctx = RoundContext(campaign_id="c1", tenant_id="t1", stage="SM", round_index=1, cpf_uri=(tmp_path / "cpf.json").as_uri(),
                       cpf_sha256="a" * 64, pending_action=None, map_uri=(tmp_path / "map.json").as_uri(),
                       system_uri=(tmp_path / "system.json").as_uri())
    return ctx, system, doc


def _row(study_id: str, *, auc: float, thalf: float, analyte: str) -> dict:
    return {"study_id": study_id, "role": "fitting", "gated": True, "analyte": analyte,
            "predicted_auc": auc, "observed_auc": 1.0, "predicted_cmax": auc, "observed_cmax": 1.0,
            "predicted_thalf": thalf * 100.0, "observed_thalf": 100.0, "auc_in_limits": False}


def _evaluation(*rows: dict) -> RoundEvaluation:
    return RoundEvaluation(gate_passed=False, acceptable=False, metrics={"studies": list(rows)}, findings=[])


ITZ = {"Itraconazole": {"elim.hepatic.CYP3A4.kcat": ("S1", "S2", "SM")},
       "Hydroxy-Itraconazole": {"elim.hepatic.CYP3A4.kcat": ("SM",), "phys.logp": ("SM",)}}


def test_a_metabolite_formed_too_little_is_offered_the_parents_forming_rate(tmp_path):
    ctx, _system, doc = _campaign(tmp_path, "Itraconazole", ITZ)
    study = next(s for s in doc.scenarios if s.stage == "SM" and s.analyte == "Hydroxy-Itraconazole")
    diag = diagnose_round(ctx, _evaluation(_row(study.study_id, auc=0.4, thalf=1.0, analyte=study.analyte)))
    # the parent's CYP3A4 process forms hydroxy-itraconazole: its rate, on the parent (a bare id)
    assert "formation_off" in diag.evidence and diag.permitted_actions == ["fit elim.hepatic.CYP3A4.kcat"]


def test_a_metabolite_eliminated_too_slowly_is_offered_its_own_clearance_then_logp(tmp_path):
    ctx, _system, doc = _campaign(tmp_path, "Itraconazole", ITZ)
    study = next(s for s in doc.scenarios if s.stage == "SM" and s.analyte == "Hydroxy-Itraconazole")
    diag = diagnose_round(ctx, _evaluation(_row(study.study_id, auc=1.8, thalf=1.6, analyte=study.analyte)))
    # templated as for a single compound: `{enzyme}` resolves on the metabolite's CPF when the fit is built
    assert diag.permitted_actions == ["fit Hydroxy-Itraconazole::elim.hepatic.{enzyme}.kcat",
                                      "fit Hydroxy-Itraconazole::phys.logp"]


def test_a_tried_metabolite_action_is_not_offered_again(tmp_path):
    ctx, _system, doc = _campaign(tmp_path, "Itraconazole", ITZ)
    study = next(s for s in doc.scenarios if s.stage == "SM" and s.analyte == "Hydroxy-Itraconazole")
    ctx = RoundContext(**{**ctx.__dict__, "actions_tried": ["fit Hydroxy-Itraconazole::elim.hepatic.{enzyme}.kcat"]})
    diag = diagnose_round(ctx, _evaluation(_row(study.study_id, auc=1.8, thalf=1.6, analyte=study.analyte)))
    assert diag.permitted_actions == ["fit Hydroxy-Itraconazole::phys.logp"]


def test_a_racemic_sum_fits_both_enantiomers_together(tmp_path):
    kcat = "elim.hepatic.CYP3A4@Norverapamil.kcat"
    ctx, _system, doc = _campaign(tmp_path, "Verapamil", {"R-Verapamil": {kcat: ("S1", "S2")},
                                                          "S-Verapamil": {kcat: ("S1", "S2")}})
    del _system
    total = next(s for s in doc.scenarios if s.stage in ("S1", "S2") and s.analyte and s.analyte.startswith("Sum-Verapamil"))
    ctx = RoundContext(**{**ctx.__dict__, "stage": total.stage})
    diag = diagnose_round(ctx, _evaluation(_row(total.study_id, auc=1.8, thalf=1.6, analyte=total.analyte)))
    # the sum cannot tell the enantiomers apart: one fit of both their rates (the fitted R bare, S qualified)
    assert diag.permitted_actions[0] == "fit elim.hepatic.{enzyme}.kcat+S-Verapamil::elim.hepatic.{enzyme}.kcat"


def test_a_single_compound_monitor_has_no_sm_row(tmp_path):
    # SM is in the campaign's stage list, but a MAP that does not plan it is not part of the campaign: no pending row
    from modeler_contracts.runs import CAMPAIGN_STAGES, CampaignRequest
    from modeler_orchestrator.local_runner import _campaign_writer

    ctx, _system, doc = _campaign(tmp_path, "Itraconazole", ITZ)
    single = doc.model_copy(update={"stage_plan": tuple(p for p in doc.stage_plan if p.stage != "SM")})
    (tmp_path / "single.json").write_text(single.model_dump_json(), encoding="utf-8")
    request = CampaignRequest(campaign_id="c1", tenant_id="t1", compound="Itraconazole", map_id="m", cpf_uri=ctx.cpf_uri,
                              cpf_sha256="a" * 64, map_uri=(tmp_path / "single.json").as_uri(), stages=list(CAMPAIGN_STAGES))
    writer = _campaign_writer(request, read_root=str(tmp_path / "root"), project="p", question="q", model_risk="medium",
                              budget_seconds=None, engine=None)
    assert "SM" not in writer.stages and "S3" in writer.stages
    planned = _campaign_writer(CampaignRequest(**{**request.__dict__, "map_uri": ctx.map_uri}),
                               read_root=str(tmp_path / "root"), project="p", question="q", model_risk="medium",
                               budget_seconds=None, engine=None)
    assert planned.stages.index("SM") == planned.stages.index("S3") + 1
