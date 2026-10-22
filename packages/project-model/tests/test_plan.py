"""T-50: the model plan — MS-01 default exactly as generate_map, every §3.3 rule on the canvas, locks, diff, MAP."""

from __future__ import annotations

import pytest

from modeler_project.plan import (
    PlanError,
    Structure,
    acknowledge,
    add_proposal,
    blocking,
    build_default,
    campaign_cpf,
    decide_proposal,
    default_fit_limitation,
    default_map,
    diff,
    hold_fixed,
    map_from_plan,
    place,
    rebase,
    release,
    set_fit,
    unlock,
    validate,
)
from pbpk_domain.cpf.models import (
    CPF,
    EngineBinding,
    FitPolicy,
    ParameterRecord,
    ParameterStatus,
    Plausibility,
    Provenance,
    Scale,
)

pytestmark = pytest.mark.req("T-50")
PROV = Provenance(source_type="Publication", reference="review")


def _cpf() -> CPF:
    def r(pid, value, unit=None, binding=None):
        return ParameterRecord(id=pid, value=value, unit=unit, status=ParameterStatus.FIXED, provenance=PROV, engine_binding=binding)

    return CPF(compound="Renaldrug", parameters=(
        r("phys.mw", 225.2, "g/mol"), r("phys.logp", -1.56, "Log Units"), r("bind.fu", 0.85),
        r("phys.solubility.ref", 1.3, "mg/ml"), r("phys.pka.base.0", 2.3),
        r("elim.renal.gfr_fraction", 1.0, binding=EngineBinding(building_block="Compound", process="GlomerularFiltration",
                                                                parameter="GFR fraction", data_source="Literature"))))


def _row(sid, route="oral", dose=10.0, food="fasted", *, profile=True, **extra):
    row = {"study_id": sid, "n": 12, "route": route, "dose_mg": dose, "formulation": "solution", "food_state": food,
           "n_timepoints": 6, "origin": "LITERATURE", "evaluable": profile, "design": "SD",
           **({"infusion_time_min": 60} if route == "iv_infusion" else {}), **extra}
    if profile:
        row["profile"] = {"times": [0.5, 1, 2, 4, 8, 12], "values": [5, 9, 7, 4, 1, 0.3], "time_unit": "h", "unit": "µmol/l"}
    return row


ROWS = [_row("iv-1", "iv_infusion", 250), _row("iv-2", "iv_infusion", 500), _row("po-10", dose=10), _row("po-50", dose=50),
        _row("po-100", dose=100), _row("po-100b", dose=100), _row("fed-50", food="fed", dose=50), _row("fed-100", food="fed", dose=100)]


def test_the_default_plan_is_ms01_and_its_map_equals_generate_map_on_its_campaign_cpf():
    cpf, structure = _cpf(), Structure(model_risk="medium")
    plan = build_default(cpf, ROWS, structure)
    roles = {s: p.role for s, p in plan.placements.items()}
    assert roles["iv-1"] == "S1" and roles["iv-2"] == "S5" and roles["po-10"] == "S2" and roles["po-100"] in ("S2", "S5")
    assert sum(r == "S3" for r in roles.values()) == 1 and plan.fit_candidates["S1"] and plan.budgets["S1"] == 5760 and plan.budgets["SJ"] == 4320  # 20 % and 15 % of 8 h
    assert not blocking(validate(plan, cpf, ROWS))
    # the campaign CPF bounds MS-01's candidates by MS-01's defaults (D-37), and the MAP says so in its limitations
    expected, _ = default_map(campaign_cpf(plan, cpf), ROWS, structure)
    doc = map_from_plan(plan, cpf, ROWS)
    assert doc.split_limitations == (*expected.split_limitations, *default_fit_limitation(plan, cpf))
    assert doc.model_copy(update={"split_limitations": expected.split_limitations}).content_sha256() == expected.content_sha256()


def test_ms01_candidates_are_fitted_within_ms01_defaults_unless_a_person_holds_them_fixed():
    """D-37: every MS-01 fit candidate a person neither estimates nor holds fixed gets MS-01 §2.2's default bounds and
    scale as its fit policy at the stages it is a candidate at, so the diagnosis may fit it there."""
    cpf, structure = _cpf(), Structure(model_risk="medium")
    plan = build_default(cpf, ROWS, structure)
    run = campaign_cpf(plan, cpf)
    assert run.get("phys.logp").fit_policy == FitPolicy(stage=("S1",), lower=-3.06, upper=-0.06, scale=Scale.LINEAR)  # ±1.5
    assert run.get("phys.solubility.ref").fit_policy == FitPolicy(stage=("S2",), lower=1.3, upper=130, scale=Scale.LOG)
    assert run.get("bind.fu").fit_policy is None        # a measured fu: MS-01 §2.2 keeps it fixed
    assert run.get("phys.mw").fit_policy is None        # not a candidate
    doc = map_from_plan(plan, cpf, ROWS)
    logp = next(p for p in doc.cpf_parameters if p.id == "phys.logp")
    assert logp.fittable_stages == ("S1",) and logp.bounds is not None and logp.bounds.lower == -3.06
    assert any("D-37" in line and "phys.logp in S1 [-3.06, -0.06] linear" in line and "UNVERIFIED" in line
               for line in doc.split_limitations)
    # held fixed: no fit policy; the diff and the MAP's rationale say who and why
    held = hold_fixed(plan, "phys.logp", by="u", reason="logP measured twice; keep it")
    assert campaign_cpf(held, cpf).get("phys.logp").fit_policy is None
    assert {"kind": "fit", "target": "phys.logp", "from": "MS-01 default", "to": "held fixed", "by": "u",
            "reason": "logP measured twice; keep it", "status": "APPLIED"} in diff(held)
    assert any("Plan change: phys.logp MS-01 default → held fixed by u" in r for r in map_from_plan(held, cpf, ROWS).split_rationale)
    with pytest.raises(PlanError, match="not an MS-01 fit candidate"):
        hold_fixed(plan, "phys.mw", by="u", reason="x")
    assert release(held, "phys.logp").held_fixed == {}
    # the hold survives a rebase while it is still a candidate
    assert set(rebase(held, build_default(cpf, ROWS, structure)).held_fixed) == {"phys.logp"}
    # a person's fit replaces the hold; taking the fit back leaves MS-01's default again
    fitted = set_fit(held, "phys.logp", {"stages": ("S1",), "lower": -2.5, "upper": -0.5, "scale": "linear"}, by="u",
                     reason="narrower than MS-01")
    assert not fitted.held_fixed and campaign_cpf(fitted, cpf).get("phys.logp").fit_policy.lower == -2.5
    unfitted = set_fit(fitted, "phys.logp", None, by="u", reason="back")
    assert campaign_cpf(unfitted, cpf).get("phys.logp").fit_policy.lower == -3.06
    # holding a candidate with a person's fit removes that fit
    assert "phys.logp" not in hold_fixed(fitted, "phys.logp", by="u", reason="fixed after all").fits
    # a candidate the CPF already bounds keeps its own range
    bounded = cpf.model_copy(update={"parameters": tuple(
        r.model_copy(update={"plausibility": Plausibility(lower=-2, upper=0, source="SME")}) if r.id == "phys.logp" else r
        for r in cpf.parameters)})
    assert campaign_cpf(plan, bounded).get("phys.logp").fit_policy is None


def test_every_ms01_rule_is_enforced_on_the_canvas():
    cpf = _cpf()
    rows = [*ROWS, _row("ddi-itra", dose=50, co_medication="itraconazole"), _row("nca-only", dose=50, profile=False)]
    plan = build_default(cpf, rows, Structure(model_risk="medium"))

    def errors(p):
        return {(v.rule, v.target) for v in validate(p, cpf, rows) if v.severity == "error"}

    with pytest.raises(PlanError, match="reason"):
        place(plan, "po-10", "S5", by="u", reason=" ")
    assert ("rule-4", "ddi-itra") in errors(place(plan, "ddi-itra", "S2", by="u", reason="try"))       # rule 4
    assert ("stage", "iv-2") in errors(place(plan, "iv-2", "S2", by="u", reason="try"))               # IV trains S1
    assert ("profile", "nca-only") in errors(place(plan, "nca-only", "S2", by="u", reason="try"))     # NCA only
    assert ("rule-4", "po-50") in errors(place(plan, "po-50", "S6", by="u", reason="try"))            # core study in S6
    food = build_default(cpf, rows, Structure(model_risk="medium", food_effect_in_question=True))
    assert ("rule-5", "fed-50") in errors(place(food, "fed-50", "S3", by="u", reason="try"))           # rule 5
    # removing the only trained IV study asks for an acknowledged consequence (rule 1, decision tree §6.1)
    no_iv = place(place(plan, "iv-1", "S5", by="u", reason="keep both IV external"), "iv-2", "S5", by="u", reason="same")
    warning = next(v for v in validate(no_iv, cpf, rows) if v.rule == "rule-1" and v.target == "S1")
    assert warning in blocking(validate(no_iv, cpf, rows))
    with pytest.raises(PlanError, match="open rule violations"):
        map_from_plan(no_iv, cpf, rows)
    # external coverage (rule 3): every fasted oral study trained leaves no external fasted study
    all_in = plan
    for sid in ("po-10", "po-50", "po-100", "po-100b"):
        all_in = place(all_in, sid, "S2", by="u", reason="use every dose level")
    assert any(v.rule == "rule-3" and v.target == "fasted oral" for v in validate(all_in, cpf, rows))
    # acknowledged warnings no longer block, and travel into the MAP's limitations with their reason
    acked = no_iv
    for v in blocking(validate(no_iv, cpf, rows)):
        assert v.severity == "warning"
        acked = acknowledge(acked, v.id, by="u", reason="IV data are for validation only in this project")
    doc = map_from_plan(acked, cpf, rows)
    assert any("Plan change: iv-1 S1 → S5 by u: keep both IV external" in r for r in doc.split_rationale)
    assert any("acknowledged: IV data are for validation only" in lim for lim in doc.split_limitations)
    assert not any(sc.stage == "S1" for sc in doc.scenarios)


def test_a_persons_choices_are_locked_against_agent_passes_and_rebases():
    cpf = _cpf()
    plan = place(build_default(cpf, ROWS, Structure(model_risk="medium")), "po-10", "S5", by="u", reason="keep the low dose external")
    assert plan.placements["po-10"].userLocked and plan.study("po-10").default_role == "S2"
    plan, answer = add_proposal(plan, "role", "po-10", {"role": "S2"}, reason="more training data", by="agent:a5")
    assert answer.startswith("REFUSED") and "placed by a person" in answer
    plan, answer = add_proposal(plan, "role", "fed-100", {"role": "S5"}, reason="keep fed external", by="agent:a5")
    pending = [d for d in diff(plan) if d["status"] == "PENDING"]
    assert answer.startswith("PROPOSED") and pending[0]["target"] == "fed-100" and pending[0]["reason"] == "keep fed external"
    plan = decide_proposal(plan, answer.split()[1], accept=False, by="u", reason="fed effect must be fitted")
    assert not [d for d in diff(plan) if d["status"] == "PENDING"]
    applied = [d for d in diff(plan) if d["status"] == "APPLIED"]
    assert applied == [{"kind": "role", "target": "po-10", "from": "S2", "to": "S5", "by": "u",
                        "reason": "keep the low dose external", "status": "APPLIED"}]
    # new data: the default is recomputed, the locked choice kept, the new study marked
    fresh = build_default(cpf, [*ROWS, _row("po-25", dose=25)], Structure(model_risk="medium"))
    rebased = rebase(plan, fresh)
    assert rebased.placements["po-10"].role == "S5" and rebased.study("po-25").new
    assert unlock(rebased, "po-10").placements["po-10"].role == rebased.study("po-10").default_role


def test_fit_choices_become_fit_policies_of_the_campaign_cpf():
    cpf = _cpf()
    plan = set_fit(build_default(cpf, ROWS, Structure(model_risk="medium")), "elim.renal.gfr_fraction",
                   {"stages": ("S1",), "lower": 0.1, "upper": 3.0, "scale": "log"}, by="u", reason="renal clearance uncertain")
    assert not blocking(validate(plan, cpf, ROWS))
    wider = set_fit(plan, "elim.renal.gfr_fraction", {"stages": ("S1",), "lower": 0.1, "upper": 10.0, "scale": "log"},
                    by="u", reason="wider")      # beyond MS-01 §2.2's default [0, 3]: said, and acknowledged to sign
    assert [v.rule for v in blocking(validate(wider, cpf, ROWS))] == ["fit-default"]
    doc = map_from_plan(plan, cpf, ROWS)
    gfr = next(p for p in doc.cpf_parameters if p.id == "elim.renal.gfr_fraction")
    assert gfr.fittable_stages == ("S1",)
    bad = set_fit(plan, "phys.logp", {"stages": ("S4",), "lower": -3, "upper": 0}, by="u", reason="x")
    assert any(v.rule == "fit" and "S1–S3" in v.message for v in validate(bad, cpf, ROWS))


@pytest.mark.req("T-31")
def test_the_briefs_vbe_application_waits_for_the_persons_inputs_before_the_map():
    from modeler_project.plan import set_structure, structure_from_brief
    from pbpk_domain.campaign.map import MapApplication

    class Brief:  # the brief fields the structure reads here
        def value(self, key):
            return {"qoi.applications": ["APP-14 virtual bioequivalence"], "acceptance.tier": "medium"}.get(key)

    structure = structure_from_brief(Brief())  # type: ignore[arg-type]
    assert structure.applications == (MapApplication.pinned("vbe-crossover"),)  # started with no inputs, none invented
    cpf = _cpf()
    plan = build_default(cpf, ROWS, structure)
    named = [v.message for v in blocking(validate(plan, cpf, ROWS)) if v.rule == "application"]
    assert any("Intra-subject variability" in m and "never defaulted" in m for m in named)
    with pytest.raises(PlanError, match="Virtual trials: not given"):
        map_from_plan(plan, cpf, ROWS)

    inputs = {"test_formulation": "Test", "reference_formulation": "Ref", "n_subjects": 24, "n_trials": 100, "seed": 7,
              "pos_threshold": 0.8,
              "variability": [{"parameter": "Organism|Stomach|Gastric emptying time", "cv_percent": 30, "source": "cited"}]}
    given = set_structure(plan, "applications", [{"template": "vbe-crossover", "inputs": inputs}], by="u1", reason="design")
    assert [v.message for v in validate(given, cpf, ROWS) if v.rule == "application"] == [
        ("vbe-crossover: TEST formulation (a CPF formulation, form.{name}.*): 'Test' is not a CPF formulation (the CPF "
         "defines none)"),
        "vbe-crossover: Reference (RLD) formulation (a CPF formulation): 'Ref' is not a CPF formulation (the CPF defines none)"]
    tablets = tuple(ParameterRecord(id=f"form.{n}.weibull.t50", value=30.0, unit="min", status=ParameterStatus.FIXED,
                                    provenance=PROV) for n in ("Test", "Ref"))
    with_tablets = cpf.model_copy(update={"parameters": (*cpf.parameters, *tablets)})
    assert not [v for v in validate(given, with_tablets, ROWS) if v.rule == "application"]
    assert map_from_plan(given, with_tablets, ROWS).applications[0].inputs == inputs
    row = next(r for r in diff(given) if r["target"] == "applications")
    assert row["to"] == [f"vbe-crossover {structure.applications[0].template_version}"]
    with pytest.raises(PlanError, match="known analysis template"):
        set_structure(plan, "applications", [{"template": "no-such"}], by="u1", reason="x")


def test_the_model_risk_is_never_assumed_and_the_budget_is_the_persons():
    # ICH M15: the tier decides the acceptance criteria, so an unset one blocks the signature instead of defaulting to
    # medium. The campaign's time budget is a structure choice; MS-01's fractions split it across the stages.
    cpf = _cpf()
    unrated = build_default(cpf, ROWS, Structure())
    assert [v.rule for v in blocking(validate(unrated, cpf, ROWS))] == ["risk"]
    with pytest.raises(PlanError, match="model risk"):
        map_from_plan(unrated, cpf, ROWS)
    two_hours = build_default(cpf, ROWS, Structure(model_risk="high", campaign_budget_seconds=2 * 3600))
    doc = map_from_plan(two_hours, cpf, ROWS)
    assert doc.model_risk.value == "high"
    assert {p.stage: p.budget_seconds for p in doc.stage_plan}["S1"] == 1440  # 20 % of 2 h
    # a fit keeps 15 min of its stage's share in reserve: a budget that leaves S3 less is said at signing, not at run time
    fit = {"stages": ("S3",), "lower": 0.1, "upper": 10.0, "scale": "log"}
    short = set_fit(two_hours, "elim.renal.gfr_fraction", fit, by="u", reason="the tablet's exposure is uncertain")
    (warning,) = [v for v in validate(short, cpf, ROWS) if v.rule == "budget"]
    assert warning.target == "S3" and warning.severity == "warning" and "8 min of the 2 h budget" in warning.message
    assert "More than 3.6 h" in warning.message
    roomy = set_fit(build_default(cpf, ROWS, Structure(model_risk="high")), "elim.renal.gfr_fraction", fit, by="u", reason="x")
    assert not [v for v in validate(roomy, cpf, ROWS) if v.rule == "budget"]  # 8 h: S3 has 34 min


def test_a_fit_s_bounds_are_checked_against_ms01_and_plausibility_and_inverted_bounds_are_refused():
    """R4b (D-34): MS-01 §2.2's defaults may be narrowed, never widened beyond plausibility; a start value on a bound is
    inside the bounds; a measured fu, which MS-01 keeps fixed, is said when estimated."""
    cpf = _cpf()
    plan = build_default(cpf, ROWS, Structure(model_risk="medium"))
    fit = {"stages": ("S1",), "scale": "linear"}
    with pytest.raises(PlanError, match="must be below the upper bound"):
        set_fit(plan, "elim.renal.gfr_fraction", {**fit, "lower": 2.0, "upper": 0.5}, by="u", reason="r")
    on_bound = set_fit(plan, "elim.renal.gfr_fraction", {**fit, "lower": 0.0, "upper": 1.0}, by="u", reason="r")
    assert not [v for v in validate(on_bound, cpf, ROWS) if v.target == "elim.renal.gfr_fraction"]
    beyond = set_fit(plan, "elim.renal.gfr_fraction", {**fit, "lower": 0.0, "upper": 12.0}, by="u", reason="r")
    assert {v.rule for v in validate(beyond, cpf, ROWS) if v.target == "elim.renal.gfr_fraction"} == {"fit-plausible", "fit-default"}
    fu = set_fit(plan, "bind.fu", {**fit, "lower": 0.5, "upper": 1.0}, by="u", reason="r")
    assert [v.rule for v in validate(fu, cpf, ROWS) if v.target == "bind.fu"] == ["fit-fixed"]


def test_an_internal_target_must_be_stricter_than_the_tier_and_the_signed_map_carries_it():
    """MS-01 §8: a project may judge more strictly than its tier, never more loosely. At medium (1.5-fold) a ratio within
    ±t % stays inside [1/1.5, 1.5] only for t ≤ 33.3 %. The MAP records the target and the verdicts apply it (R4d), so it
    is a criterion, no longer a limitation."""
    from modeler_project.plan import map_limitations, set_structure, structure_from_brief
    from pbpk_domain.acceptance import loosest_internal_target

    class Brief:
        def value(self, key):
            return {"acceptance.tier": "medium", "acceptance.internal_target_pe": 20}.get(key)

    structure = structure_from_brief(Brief())  # type: ignore[arg-type]
    assert structure.internal_target_pe == 20 and loosest_internal_target("medium") == pytest.approx(100 / 3)
    cpf = _cpf()
    plan = build_default(cpf, ROWS, structure)
    assert not [v for v in validate(plan, cpf, ROWS) if v.rule == "target"]
    assert not any("Internal target" in line for line in map_limitations(plan, []))
    assert map_from_plan(plan, cpf, ROWS).acceptance.internal_target_pe == 20
    loose = set_structure(plan, "internal_target_pe", 40, by="u", reason="r")
    [target] = [v for v in validate(loose, cpf, ROWS) if v.rule == "target"]
    assert target.severity == "error" and "at most 33.3 %" in target.message
    high = set_structure(loose, "model_risk", "high", by="u", reason="r")
    assert "at most 20.0 %" in next(v.message for v in validate(high, cpf, ROWS) if v.rule == "target")


def test_applications_the_campaign_cannot_run_are_said_at_signing_and_named_among_the_limitations():
    """R4c (owner 2026-10-19): an application S6 does not run is a warning at signing; acknowledged, the MAP names it as
    a limitation. A VBE crossover needs two subjects per trial, and each of its problems is its own line."""
    from modeler_project.plan import acknowledge, map_limitations, set_structure, structure_from_brief

    class Brief:
        def value(self, key):
            return {"qoi.applications": ["APP-01 model build and verification", "APP-03 enzyme DDI", "APP-12 food effect",
                                         "APP-14 virtual bioequivalence"], "acceptance.tier": "medium"}.get(key)

    structure = structure_from_brief(Brief())  # type: ignore[arg-type]
    assert structure.application_codes == ("APP-01", "APP-03", "APP-12", "APP-14")
    cpf = _cpf()
    plan = build_default(cpf, ROWS, structure)
    unsupported = {v.target: v for v in validate(plan, cpf, ROWS) if v.rule == "application-unsupported"}
    assert set(unsupported) == {"APP-03", "APP-12"}                      # APP-01: the campaign; APP-14: S6 runs it
    assert unsupported["APP-03"].severity == "warning"
    assert unsupported["APP-03"].message.startswith("APP-03 enzyme DDI: not supported yet — S6 runs no DDI template")
    assert unsupported["APP-12"].message.startswith("APP-12 food effect: partly supported — fed studies are judged at S5")
    acknowledged = acknowledge(plan, unsupported["APP-03"].id, by="u1", reason="the DDI question is answered elsewhere")
    lines = map_limitations(acknowledged, validate(acknowledged, cpf, ROWS))
    assert any(line.startswith("APP-03 enzyme DDI: not supported yet") and "answered elsewhere" in line for line in lines)

    ids = [v.id for v in validate(plan, cpf, ROWS) if v.rule == "application"]
    assert len(ids) > 1 and len(ids) == len(set(ids))                    # one id per problem, never shared
    one = {"test_formulation": "Test", "reference_formulation": "Ref", "n_subjects": 1, "n_trials": 100, "seed": 7,
           "pos_threshold": 0.8, "variability": [{"parameter": "Organism|Lumen|Stomach|Gastric emptying time",
                                                  "cv_percent": 30, "source": "cited"}]}
    tablets = tuple(ParameterRecord(id=f"form.{n}.weibull.t50", value=30.0, unit="min", status=ParameterStatus.FIXED,
                                    provenance=PROV) for n in ("Test", "Ref"))
    with_tablets = cpf.model_copy(update={"parameters": (*cpf.parameters, *tablets)})
    single = set_structure(plan, "applications", [{"template": "vbe-crossover", "inputs": one}], by="u1", reason="design")
    assert [v.message for v in validate(single, with_tablets, ROWS) if v.rule == "application"] == [
        ("vbe-crossover: Subjects per trial: at least 2 (a crossover's 90 % confidence interval needs two subjects; the "
         "engine refuses fewer)")]
