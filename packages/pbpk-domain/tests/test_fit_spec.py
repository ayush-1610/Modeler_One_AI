from __future__ import annotations

import pytest

from pbpk_domain.cpf import CPF, EngineBinding, FitPolicy, ParameterRecord, ParameterStatus, Plausibility, Provenance
from pbpk_domain.fit_spec import (
    FitSimulation,
    FitSpecError,
    apply_fit_estimates,
    build_fit_spec,
    pi_observed,
    resolve_fit_ids,
)

PROV = Provenance(source_type="measured", reference="x")


def rec(pid, value, *, unit=None, status=ParameterStatus.PREDICTED, binding=None, fit_policy=None, plausibility=None):
    return ParameterRecord(id=pid, value=value, unit=unit, status=status, provenance=PROV,
                           engine_binding=binding, fit_policy=fit_policy, plausibility=plausibility)


def _cpf():
    clspec_bind = EngineBinding(building_block="Compound", process="MetabolizationSpecific_FirstOrder:CYP3A4",
                                parameter="CLspec/[Enzyme]", data_source="Optimized")
    return CPF(compound="Drug-A", parameters=(
        rec("phys.mw", 300.0, unit="g/mol", status=ParameterStatus.FIXED),
        rec("phys.logp", 2.5, unit="Log Units", fit_policy=FitPolicy(stage=("S1",), lower=1.0, upper=4.0)),
        rec("elim.hepatic.CYP3A4.clspec", 0.8, unit="l/µmol/min", status=ParameterStatus.FITTED, binding=clspec_bind,
            fit_policy=FitPolicy(stage=("S1", "S2"), lower=0.01, upper=100.0, scale="log")),
    ))


def _sim(study_id="iv"):
    obs = pi_observed("obs", [0.5, 1, 4], [12.0, 20.0, 5.0], time_unit="h", unit="ng/ml", mol_weight=300.0, sd=[1, 2, 0.5], lloq=0.1)
    return FitSimulation(study_id=study_id, pkml=f"{study_id}.pkml",
                         output_path="Organism|PeripheralVenousBlood|Drug-A|Plasma (Peripheral Venous Blood)", observed=obs)


# --- resolve_fit_ids -----------------------------------------------------------------------------


def test_resolve_templated_target_to_concrete_ids():
    assert resolve_fit_ids(_cpf(), "elim.hepatic.{enzyme}.clspec") == ("elim.hepatic.CYP3A4.clspec",)


def test_resolve_plain_target():
    assert resolve_fit_ids(_cpf(), "phys.logp") == ("phys.logp",)
    assert resolve_fit_ids(_cpf(), "phys.pka") == ()  # absent -> empty


# --- build_fit_spec ------------------------------------------------------------------------------


def test_build_fit_spec_structure_and_path():
    spec = build_fit_spec(_cpf(), ["phys.logp", "elim.hepatic.CYP3A4.clspec"], [_sim("iv"), _sim("po")])
    assert [s["id"] for s in spec["simulations"]] == ["iv", "po"]
    assert [s["pkml"] for s in spec["simulations"]] == ["iv.pkml", "po.pkml"]
    logp = next(p for p in spec["parameters"] if p["name"] == "phys.logp")
    assert logp["min"] == 1.0 and logp["max"] == 4.0 and logp["start"] == 2.5
    assert logp["paths"] == [{"simulation": "iv", "path": "Drug-A|Lipophilicity"},
                             {"simulation": "po", "path": "Drug-A|Lipophilicity"}]
    clspec = next(p for p in spec["parameters"] if p["name"] == "elim.hepatic.CYP3A4.clspec")
    assert clspec["paths"][0]["path"] == "Drug-A-CYP3A4-Optimized|CLspec/[Enzyme]"
    assert spec["output_mappings"][0]["observed"]["lloq"] == 0.1
    assert spec["algorithm"] == "BOBYQA"


def test_dimensionless_parameter_carries_no_unit_key():
    """A null unit came back from run_job.R's re-serialisation as {} and ospsuite rejected it (found on PK-Sim)."""
    gfr_bind = EngineBinding(building_block="Compound", process="GlomerularFiltration", parameter="GFR fraction",
                             data_source="Literature")
    cpf = CPF(compound="Drug-A", parameters=(
        rec("phys.mw", 300.0, unit="g/mol", status=ParameterStatus.FIXED),
        rec("elim.renal.gfr_fraction", 0.4, binding=gfr_bind, fit_policy=FitPolicy(stage=("S1",), lower=0.0, upper=3.0)),
    ))
    spec = build_fit_spec(cpf, ["elim.renal.gfr_fraction"], [_sim()])
    assert "unit" not in spec["parameters"][0]
    assert build_fit_spec(_cpf(), ["phys.logp"], [_sim()])["parameters"][0]["unit"] == "Log Units"


def test_bounds_override_wins_and_start_is_clamped():
    spec = build_fit_spec(_cpf(), ["phys.logp"], [_sim()], bounds_override={"phys.logp": (3.0, 5.0)})
    p = spec["parameters"][0]
    assert p["min"] == 3.0 and p["max"] == 5.0
    assert p["start"] == 3.0  # 2.5 is below the override lower bound -> clamped up


def test_parameter_without_bounds_raises():
    cpf = CPF(compound="Drug-A", parameters=(rec("phys.logp", 2.5, unit="Log Units"),))  # no fit policy/plausibility
    with pytest.raises(FitSpecError, match="no bounds to fit"):
        build_fit_spec(cpf, ["phys.logp"], [_sim()])


def test_unmapped_parameter_raises():
    cpf = CPF(compound="Drug-A", parameters=(
        rec("phys.pka.base.0", 6.0, plausibility=Plausibility(lower=1.0, upper=12.0)),
    ))
    with pytest.raises(Exception, match="no harvested"):  # ParameterPathError from the resolver
        build_fit_spec(cpf, ["phys.pka.base.0"], [_sim()])


# --- apply_fit_estimates -------------------------------------------------------------------------


@pytest.mark.req("T-13")
def test_apply_estimates_creates_fitted_new_version():
    cpf = _cpf()
    updated = apply_fit_estimates(cpf, {"phys.logp": 3.1, "elim.hepatic.CYP3A4.clspec": 1.4}, stage="S1", run="round-3")
    assert updated.version == cpf.version + 1
    logp = updated.require("phys.logp")
    assert logp.numeric_value == 3.1
    assert logp.status is ParameterStatus.FITTED
    assert logp.fitted_at_stage == "S1"
    assert logp.provenance.source_type == "ParameterIdentification"
    assert logp.provenance.supersedes == f"Drug-A@{cpf.version}:phys.logp"
    assert logp.fit_policy is not None  # policy/binding preserved
    assert cpf.require("phys.logp").numeric_value == 2.5  # original unchanged (immutable)


def test_apply_unknown_estimate_raises():
    with pytest.raises(FitSpecError, match="no such parameter"):
        apply_fit_estimates(_cpf(), {"phys.nonesuch": 1.0}, stage="S1")


def test_weibull_parameter_is_fitted_per_simulation_under_its_own_protocol():
    """Harvested on PK-Sim 12.4.4: Events|<protocol>|<formulation>|Dissolution time (50% dissolved)."""
    prov = Provenance(source_type="measured", reference="in-vitro dissolution")
    cpf = _cpf().model_copy(update={"parameters": (*_cpf().parameters,
        ParameterRecord(id="form.Tab.type", value="Weibull", status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="form.Tab.weibull.t50", value=30.0, unit="min", status=ParameterStatus.FIXED, provenance=prov,
                        fit_policy=FitPolicy(stage=("S3",), lower=15.0, upper=60.0)))})
    obs = pi_observed("o", [1, 2], [1.0, 0.5], time_unit="h", unit="ng/ml", mol_weight=300.0)
    out = "Organism|PeripheralVenousBlood|Drug-A|Plasma (Peripheral Venous Blood)"
    sims = [FitSimulation("tab_a", "snapshot-tab_a.pkml", out, obs, protocol="tab_a protocol", formulation="Tab"),
            FitSimulation("tab_b", "snapshot-tab_b.pkml", out, obs, protocol="tab_b protocol", formulation="Tab"),
            FitSimulation("sol", "snapshot-sol.pkml", out, obs, protocol="sol protocol", formulation=None)]
    spec = build_fit_spec(cpf, ["form.Tab.weibull.t50"], sims)
    assert spec["parameters"][0]["paths"] == [
        {"simulation": "tab_a", "path": "Events|tab_a protocol|Tab|Dissolution time (50% dissolved)"},
        {"simulation": "tab_b", "path": "Events|tab_b protocol|Tab|Dissolution time (50% dissolved)"},
    ]  # the solution study has no such parameter and is not given a path
    assert (spec["parameters"][0]["min"], spec["parameters"][0]["max"]) == (15.0, 60.0)
    with pytest.raises(FitSpecError, match="uses formulation"):
        build_fit_spec(cpf, ["form.Tab.weibull.t50"], [sims[2]])
