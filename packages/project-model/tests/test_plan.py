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
    decide_proposal,
    default_map,
    diff,
    map_from_plan,
    place,
    rebase,
    set_fit,
    unlock,
    validate,
)
from pbpk_domain.cpf.models import CPF, EngineBinding, ParameterRecord, ParameterStatus, Provenance

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


def test_the_default_plan_is_ms01_and_its_map_equals_generate_map():
    cpf, structure = _cpf(), Structure()
    plan = build_default(cpf, ROWS, structure)
    roles = {s: p.role for s, p in plan.placements.items()}
    assert roles["iv-1"] == "S1" and roles["iv-2"] == "S5" and roles["po-10"] == "S2" and roles["po-100"] in ("S2", "S5")
    assert sum(r == "S3" for r in roles.values()) == 1 and plan.fit_candidates["S1"] and plan.budgets["S1"] == 720 and plan.budgets["SJ"] == 540
    assert not blocking(validate(plan, cpf, ROWS))
    expected, _ = default_map(cpf, ROWS, structure)
    assert map_from_plan(plan, cpf, ROWS).content_sha256() == expected.content_sha256()


def test_every_ms01_rule_is_enforced_on_the_canvas():
    cpf = _cpf()
    rows = [*ROWS, _row("ddi-itra", dose=50, co_medication="itraconazole"), _row("nca-only", dose=50, profile=False)]
    plan = build_default(cpf, rows, Structure())

    def errors(p):
        return {(v.rule, v.target) for v in validate(p, cpf, rows) if v.severity == "error"}

    with pytest.raises(PlanError, match="reason"):
        place(plan, "po-10", "S5", by="u", reason=" ")
    assert ("rule-4", "ddi-itra") in errors(place(plan, "ddi-itra", "S2", by="u", reason="try"))       # rule 4
    assert ("stage", "iv-2") in errors(place(plan, "iv-2", "S2", by="u", reason="try"))               # IV trains S1
    assert ("profile", "nca-only") in errors(place(plan, "nca-only", "S2", by="u", reason="try"))     # NCA only
    assert ("rule-4", "po-50") in errors(place(plan, "po-50", "S6", by="u", reason="try"))            # core study in S6
    food = build_default(cpf, rows, Structure(food_effect_in_question=True))
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
    plan = place(build_default(cpf, ROWS, Structure()), "po-10", "S5", by="u", reason="keep the low dose external")
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
    fresh = build_default(cpf, [*ROWS, _row("po-25", dose=25)], Structure())
    rebased = rebase(plan, fresh)
    assert rebased.placements["po-10"].role == "S5" and rebased.study("po-25").new
    assert unlock(rebased, "po-10").placements["po-10"].role == rebased.study("po-10").default_role


def test_fit_choices_become_fit_policies_of_the_campaign_cpf():
    cpf = _cpf()
    plan = set_fit(build_default(cpf, ROWS, Structure()), "elim.renal.gfr_fraction",
                   {"stages": ("S1",), "lower": 0.1, "upper": 10.0, "scale": "log"}, by="u", reason="renal clearance uncertain")
    assert not blocking(validate(plan, cpf, ROWS))
    doc = map_from_plan(plan, cpf, ROWS)
    gfr = next(p for p in doc.cpf_parameters if p.id == "elim.renal.gfr_fraction")
    assert gfr.fittable_stages == ("S1",)
    bad = set_fit(plan, "phys.logp", {"stages": ("S4",), "lower": -3, "upper": 0}, by="u", reason="x")
    assert any(v.rule == "fit" and "S1–S3" in v.message for v in validate(bad, cpf, ROWS))


@pytest.mark.req("T-31")
def test_the_briefs_vbe_application_waits_for_the_persons_inputs_before_the_map():
    from modeler_project.plan import set_structure, structure_from_brief
    from pbpk_domain.campaign.map import MapApplication

    class Brief:  # the one brief field the structure reads here
        def value(self, key):
            return ["APP-14 virtual bioequivalence"] if key == "qoi.applications" else None

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
