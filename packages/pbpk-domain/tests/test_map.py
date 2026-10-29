from __future__ import annotations

from pathlib import Path

import pytest

from pbpk_domain.acceptance import Comparison, evaluate, load_acceptance_ruleset
from pbpk_domain.campaign.map import BUDGET_FRACTION, MapBounds, MapDocument, MapStatus, generate_map
from pbpk_domain.campaign.split import (
    FoodState,
    FormulationKind,
    QuestionOfInterest,
    Route,
    StudyRecord,
    split_studies,
)
from pbpk_domain.cpf import CPF, FitPolicy, ParameterRecord, ParameterStatus, Plausibility, Provenance
from pbpk_domain.m15 import Rating

pytestmark = pytest.mark.req("T-16")


def _cpf() -> CPF:
    prov = Provenance(source_type="measured", reference="Example 2020")
    return CPF(compound="Example-A", parameters=(
        ParameterRecord(id="phys.mw", value=408.5, unit="g/mol", status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="phys.logp", value=2.6, unit="Log Units", status=ParameterStatus.PREDICTED, provenance=prov,
                        fit_policy=FitPolicy(stage=("S1",), lower=1.0, upper=4.0)),
        ParameterRecord(id="bind.fu", value=0.02, status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="phys.solubility.ref", value=0.1, unit="mg/ml", status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="phys.pka.base.0", value=6.4, status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="elim.hepatic.CYP3A4.clspec", value=0.8, unit="l/µmol/min", status=ParameterStatus.FITTED, provenance=prov),
    ))


def _studies() -> list[StudyRecord]:
    def s(sid, **kw):
        base = dict(study_id=sid, n=12, design="SD", route=Route.ORAL, dose_mg=10.0,
                    formulation=FormulationKind.SOLUTION, food_state=FoodState.FASTED, n_timepoints=15)
        base.update(kw)
        return StudyRecord(**base)
    return [
        s("iv", route=Route.IV_BOLUS, dose_mg=5),
        s("po_low", dose_mg=5, n=20),
        s("po_high", dose_mg=50, n=20),
        s("fed", food_state=FoodState.FED, n=18),
    ]


def _map(**overrides):
    studies = _studies()
    split = split_studies(studies, QuestionOfInterest(measured_fed_solubility=True))
    kwargs = dict(
        compound="Example-A", cpf=_cpf(), studies=studies, split=split,
        objective="Predict oral exposure across doses", context_of_use="MIDD dose selection",
        food_effect_in_question=False, model_risk=Rating.MEDIUM, engine_image_digest="sha256:abcd",
        software_versions={"ospsuite": "12.4.4", "pksim": "12.3.173", "dotnet": "8"}, seed=42,
        campaign_budget_seconds=3600,
    )
    kwargs.update(overrides)
    return generate_map(**kwargs)


def test_map_contains_every_section():
    m = _map()
    assert m.version == 1 and m.status is MapStatus.DRAFT
    assert m.objective and m.context_of_use
    assert m.compound == "Example-A"
    assert len(m.cpf_parameters) == 6
    assert {s.study_id for s in m.studies} == {"iv", "po_low", "po_high", "fed"}
    assert m.split_rationale  # generated sentences from the split
    assert m.diagnostics_ruleset_version.startswith("diag-rules@")
    assert m.acceptance.tier == "medium"
    assert m.engine_image_digest == "sha256:abcd"
    assert m.software_versions["ospsuite"] == "12.4.4"
    assert m.seeds == {"campaign": 42}
    assert m.escalation_triggers  # non-empty


def test_cpf_parameter_table_carries_source_and_fit_policy():
    m = _map()
    by_id = {p.id: p for p in m.cpf_parameters}
    assert by_id["phys.logp"].source == "measured"
    assert by_id["phys.logp"].status == "PREDICTED"
    assert by_id["phys.logp"].fittable_stages == ("S1",)
    assert by_id["phys.mw"].fittable_stages == ()


def test_stage_plan_budgets_and_candidates():
    m = _map(campaign_budget_seconds=3600)
    plan = {p.stage: p for p in m.stage_plan}
    assert set(plan) == {"S0", "S1", "S2", "S3", "SJ", "S4", "S5", "S6", "S7"}  # SJ: MS-01 v1.1 (UNVERIFIED, D-04)
    assert abs(sum(p.budget_seconds for p in plan.values()) - 3600) <= 8  # MS-01 §7 split adds up to the campaign
    assert plan["S1"].budget_seconds == round(3600 * BUDGET_FRACTION["S1"])  # 720 (20 %, D-04)
    assert plan["SJ"].budget_seconds == 540 and plan["SJ"].max_rounds == 1
    assert "phys.logp" in plan["S1"].fit_candidates
    assert "dist.partition_method" in plan["S1"].branches
    assert plan["S4"].fit_candidates == ()  # validation stage, nothing fitted


def test_scenarios_train_their_stage_and_are_validated_in_s4_and_s5():
    """R1: internal studies train S1–S3 and are re-simulated in S4; external studies are judged in S5."""
    studies = _studies()
    split = split_studies(studies, QuestionOfInterest(measured_fed_solubility=True))
    internal = {r.study_id for r in split.splits if r.assignment.value == "INTERNAL"}
    external = {r.study_id for r in split.splits if r.assignment.value == "EXTERNAL"}
    m = _map()
    stages_of: dict[str, set[str]] = {}
    for sc in m.scenarios:
        stages_of.setdefault(sc.study_id, set()).add(sc.stage)
    assert stages_of["iv"] == {"S1", "S4"}
    for sid in internal:
        assert "S4" in stages_of[sid]                         # every trained study is validated internally
    for sid in external:
        assert stages_of[sid] == {"S5"}                       # every external core study is judged in S5
    # fed is external here (measured fed solubility): judged in S5, never trained
    assert stages_of["fed"] == {"S5"}
    assert {sc.study_class for sc in m.scenarios if sc.study_id == "fed"} == {"PO-FED"}


def test_stage_coverage_skips_a_stage_with_nothing_to_simulate():
    from pbpk_domain.campaign.map import stage_coverage

    m = _map()
    assert stage_coverage(m, "S1").kind == "fit" and stage_coverage(m, "S1").studies == ("iv",)
    s3 = stage_coverage(m, "S3")                              # fed is external here, so nothing trains S3
    assert s3.studies == () and "§6.7" in s3.skip_reason
    s5 = stage_coverage(m, "S5")
    assert s5.kind == "validate" and "fed" in s5.studies and s5.skip_reason is None


def test_s5_notes_name_external_studies_that_validate_an_application_instead():
    from pbpk_domain.campaign.map import stage_coverage
    from pbpk_domain.campaign.split import StudyClass

    studies = [*_studies(), StudyRecord(study_id="ddi", n=10, dose_mg=10, n_timepoints=12, co_medication="itraconazole")]
    split = split_studies(studies, QuestionOfInterest(measured_fed_solubility=True,
                                                      planned_applications=frozenset({StudyClass.DDI})))
    m = _map(studies=studies, split=split)
    s5 = stage_coverage(m, "S5")
    assert "ddi" not in s5.studies
    assert any("ddi (DDI) validates the planned DDI application in S6" in n for n in s5.notes)


def test_scenarios_carry_the_sampling_window_and_multiple_dose_regimen():
    studies = [*_studies(), StudyRecord(study_id="md", n=12, design="MD", dose_mg=10, n_timepoints=20,
                                        dosing_interval_h=24, n_doses=7)]
    split = split_studies(studies, QuestionOfInterest(measured_fed_solubility=True))
    m = _map(studies=studies, split=split, sampling_end_h={"iv": 72.0, "md": 168.0})
    by = {(sc.study_id, sc.stage): sc for sc in m.scenarios}
    assert by[("iv", "S1")].sim_end_time_h == 72.0 and by[("iv", "S4")].sim_end_time_h == 72.0
    md = by[("md", "S5")]
    assert (md.dosing_interval_h, md.n_doses, md.sim_end_time_h) == (24, 7, 168.0)
    assert by[("iv", "S1")].dosing_interval_h is None       # single dose carries no regimen


def test_acceptance_tier_varies_with_model_risk():
    assert _map(model_risk=Rating.HIGH).acceptance.tier == "high"
    assert _map(model_risk=Rating.LOW).acceptance.tier == "low"


def test_content_hash_is_deterministic():
    assert _map().content_sha256() == _map().content_sha256()


def test_signing_freezes_the_version():
    m = _map()
    signed = m.sign(printed_name="Dr Lead", meaning="Approved", signature_id="sig-1")
    assert signed.status is MapStatus.SIGNED
    assert signed.signature is not None
    assert signed.signature.content_sha256 == m.content_sha256()
    with pytest.raises(ValueError, match="already signed"):
        signed.sign(printed_name="again")


def test_revision_after_signing_creates_new_version_and_invalidates():
    signed = _map().sign(printed_name="Dr Lead")
    revised = signed.revise(objective="Revised objective")
    assert revised.version == 2
    assert revised.status is MapStatus.DRAFT
    assert revised.objective == "Revised objective"
    assert revised.supersedes_sha256 == signed.content_sha256()
    assert revised.invalidates_prior_campaigns is True
    assert _map().invalidates_prior_campaigns is False


def _tablet_cpf(kind: str = "Weibull") -> CPF:
    prov = Provenance(source_type="measured", reference="in-vitro dissolution")
    extra = [ParameterRecord(id="form.Tab.type", value=kind, status=ParameterStatus.FIXED, provenance=prov)]
    if kind == "Weibull":
        extra += [ParameterRecord(id="form.Tab.weibull.t50", value=30.0, unit="min", status=ParameterStatus.FIXED, provenance=prov),
                  ParameterRecord(id="form.Tab.weibull.shape", value=0.6, status=ParameterStatus.FIXED, provenance=prov)]
    return _cpf().model_copy(update={"parameters": (*_cpf().parameters, *extra)})


def _tablet_studies(with_solution: bool) -> list[StudyRecord]:
    base = dict(n=12, design="SD", route=Route.ORAL, food_state=FoodState.FASTED, n_timepoints=15)
    studies = [StudyRecord(study_id="iv", route=Route.IV_BOLUS, dose_mg=5, formulation=FormulationKind.SOLUTION,
                           **{k: v for k, v in base.items() if k != "route"})]
    if with_solution:
        studies.append(StudyRecord(study_id="sol", dose_mg=10, formulation=FormulationKind.SOLUTION, **base))
    # a second dose level, so the split makes both the lowest (solution) and highest (tablet) dose internal (§3.3)
    studies.append(StudyRecord(study_id="tab", dose_mg=20, formulation=FormulationKind.IR_TABLET, formulation_name="Tab", **base))
    return studies


def _stage_of(m, sid: str, *, not_: str = "S4") -> set[str]:
    return {sc.stage for sc in m.scenarios if sc.study_id == sid and sc.stage != not_}


def test_weibull_tablet_trains_s3_when_a_solution_study_trains_s2():
    """MS-01 §4 S2: S2 uses the solution studies; a slowly releasing IR solid is handled in S3."""
    studies = _tablet_studies(with_solution=True)
    split = split_studies(studies, QuestionOfInterest(measured_fed_solubility=True))
    m = _map(cpf=_tablet_cpf(), studies=studies, split=split)
    assert {r.study_id for r in split.splits if r.assignment.value == "INTERNAL"} >= {"sol", "tab"}
    assert _stage_of(m, "sol") == {"S2"} and _stage_of(m, "tab") == {"S3"}
    assert next(sc for sc in m.scenarios if sc.study_id == "tab").formulation_name == "Tab"


def test_tablet_is_the_s2_reference_when_there_is_no_solution_study():
    """MS-01 §6.3: with no solution, the tablet trains S2 with its in-vitro Weibull fixed."""
    studies = _tablet_studies(with_solution=False)
    m = _map(cpf=_tablet_cpf(), studies=studies, split=split_studies(studies, QuestionOfInterest(measured_fed_solubility=True)))
    assert _stage_of(m, "tab") == {"S2"}


def test_rapidly_dissolving_tablet_trains_s2_like_a_solution():
    studies = _tablet_studies(with_solution=True)
    split = split_studies(studies, QuestionOfInterest(measured_fed_solubility=True))
    m = _map(cpf=_tablet_cpf(kind="Dissolved"), studies=studies, split=split)
    assert _stage_of(m, "tab") == {"S2"}


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.req("T-50")
@pytest.mark.parametrize("name", ["map_signed_on_main_no_fit.json", "map_signed_on_main_with_fit.json"])
def test_a_map_signed_before_the_bounds_and_target_existed_keeps_its_hash(name):
    # written and signed by the code on main before R4d (cc9f02b): read again, it hashes as it was signed, so every
    # signature already given stays valid
    signed = MapDocument.model_validate_json((FIXTURES / name).read_text(encoding="utf-8"))
    assert signed.signature is not None and signed.content_sha256() == signed.signature.content_sha256
    assert all(p.bounds is None and p.plausibility is None for p in signed.cpf_parameters)
    assert signed.acceptance.internal_target_pe is None


@pytest.mark.req("T-50")
def test_a_fit_s_bounds_and_the_plausibility_range_are_in_the_map_and_under_its_hash():
    m = _map()
    logp = next(p for p in m.cpf_parameters if p.id == "phys.logp")
    assert logp.fittable_stages == ("S1",) and logp.bounds == MapBounds(lower=1.0, upper=4.0, scale="linear")
    wider = _cpf().model_copy(update={"parameters": tuple(
        p.model_copy(update={"fit_policy": FitPolicy(stage=("S1",), lower=1.0, upper=5.0)}) if p.id == "phys.logp" else p
        for p in _cpf().parameters)})
    assert _map(cpf=wider).content_sha256() != m.content_sha256()
    plausible = _cpf().model_copy(update={"parameters": tuple(
        p.model_copy(update={"plausibility": Plausibility(lower=0.001, upper=1.0)}) if p.id == "bind.fu" else p
        for p in _cpf().parameters)})
    fu = next(p for p in _map(cpf=plausible).cpf_parameters if p.id == "bind.fu")
    assert fu.plausibility == (0.001, 1.0) and fu.bounds is None
    assert _map(cpf=plausible).content_sha256() != m.content_sha256()


@pytest.mark.req("T-50")
def test_each_values_source_grade_is_recorded_under_the_hash_and_not_compared_with_the_campaign_cpf():
    # PI-2b: the signed table carries each source's grade, MS-01's "more reliable source" for fix_and_refit; the CPF
    # does not carry it, so a run's CPF is never refused for it (D-36), and a MAP without grades hashes as before
    from pbpk_domain.campaign.map import cpf_differences

    m, graded = _map(), _map(grades={"phys.logp": "B", "bind.fu": "A"})
    assert {p.id: p.grade for p in graded.cpf_parameters if p.grade} == {"phys.logp": "B", "bind.fu": "A"}
    assert all(p.grade is None for p in m.cpf_parameters) and _map(grades={}).content_sha256() == m.content_sha256()
    assert graded.content_sha256() != m.content_sha256()
    assert _map(grades={"phys.logp": "C", "bind.fu": "A"}).content_sha256() != graded.content_sha256()
    assert cpf_differences(graded, _cpf()) == []
    signed = graded.sign(printed_name="Owner")
    assert MapDocument.model_validate_json(signed.model_dump_json()).content_sha256() == signed.signature.content_sha256


@pytest.mark.req("T-50")
def test_the_internal_target_is_recorded_under_the_hash_and_never_looser_than_the_tier():
    m, strict = _map(), _map(internal_target_pe=20)
    assert m.acceptance.internal_target_pe is None and strict.acceptance.internal_target_pe == 20
    assert strict.content_sha256() != m.content_sha256()
    with pytest.raises(ValueError, match="no looser than the medium tier"):
        _map(internal_target_pe=40)                     # medium (1.5-fold) allows at most 33.3 %
    assert _map(model_risk=Rating.HIGH, internal_target_pe=20).acceptance.internal_target_pe == 20


@pytest.mark.req("T-50")
def test_the_recorded_criteria_judge_as_the_ruleset_they_were_taken_from():
    # D-35: a campaign is judged by the criteria its MAP was signed with
    m = _map()
    comparisons = [Comparison("a", "AUC", 1.4, 1.0, "fitting"), Comparison("b", "Cmax", 1.6, 1.0, "validation")]
    recorded, current = evaluate(comparisons, m.model_risk, m.acceptance.as_ruleset()), evaluate(comparisons, m.model_risk)
    assert [v.passes for v in recorded.verdicts] == [v.passes for v in current.verdicts] == [True, False]
    assert recorded.ruleset == current.ruleset == m.acceptance.ruleset
    ruleset = load_acceptance_ruleset()
    assert m.acceptance.as_ruleset() == {"id": ruleset["id"], "version": ruleset["version"],
                                         "tiers": {"medium": ruleset["tiers"]["medium"]}}
