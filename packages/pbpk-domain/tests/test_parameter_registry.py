"""Phase 4b: the parameter registry derives every pbpk_domain table of CPF ids exactly (docs/plans/2026-10-08-parameter-
registry.md). The tables in modeler_project and the recorded answers for every id are checked in
tests/architecture/test_parameter_registry.py."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pbpk_domain import parameter_units, parameters, pksim_paths
from pbpk_domain.cpf import build, process_bindings
from pbpk_domain.cpf.completeness import check_completeness
from pbpk_domain.cpf.models import CPF, ParameterRecord, ParameterStatus, Provenance
from pbpk_domain.reference.osp_import import PROCESS_FAMILY, PROCESS_PARAMETERS

pytestmark = pytest.mark.req("T-25")


def _corpus() -> list[str]:
    """Every key, a child of every family, every harvested process id, and edge probes."""
    ids = {"elim", "phys.pka", "unknown.parameter", "phys.solubility.ref@fed", "elim.hepatic.CYP3A4@alt.clspec",
           "elim.renal.total.plasma_clearance", "elim.hepatic.total.plasma_clearance", "form.tablet.weibull.shape",
           "form.tablet.weibull.t50", "phys.pka.acid.1", "phys.pka.neutral", "elim.fm.CYP3A4", "food.fed_solubility_factor"}
    for rule in parameters.registry().parameters:
        ids |= {rule.key, rule.key + "x", rule.key + ".x", rule.key + "CYP3A4" + (rule.suffix or "")}
    for prefix, process in process_bindings._FIXED_PREFIX.items():
        ids |= {f"{prefix}.{suffix}" for suffix, _ in PROCESS_PARAMETERS[process].values()}
    for process, family in PROCESS_FAMILY.items():
        ids |= {f"{family}.CYP3A4.{suffix}" for suffix, _ in PROCESS_PARAMETERS[process].values()}
    return sorted(ids)


CORPUS = _corpus()


def _record(cpf_id: str) -> ParameterRecord:
    return ParameterRecord(id=cpf_id, value=1.0, status=ParameterStatus.FIXED,
                           provenance=Provenance(source_type="measured", reference="registry test"))


def test_registry_is_governed_content():
    reg = parameters.registry()
    assert reg.id == "parameter-registry" and reg.version == "1.1" and reg.status == "UNVERIFIED"


def test_storage_units_are_parameter_units_tables():
    assert parameters.storage_targets() == parameter_units._TARGETS
    for cpf_id in CORPUS:
        assert parameters.storage_family(cpf_id) == parameter_units.target_family(cpf_id), cpf_id
    families = {family for _, family in parameter_units._TARGETS}
    assert families <= {*parameter_units._FAMILIES, "fraction", None}


def test_not_converted_reason_is_the_conversion_error():
    reason = parameters.not_converted_reason("elim.hepatic.CYP3A4.clspec")
    with pytest.raises(parameter_units.ConversionError, match="IVIVE") as raised:
        parameter_units.to_storage_unit("elim.hepatic.CYP3A4.clspec", 1.0, "µl/min/mg")
    assert str(raised.value) == reason
    assert parameters.not_converted_reason("elim.hepatic.CYP3A4.km") is None


def test_compound_parameters_are_the_harvested_names():
    assert parameters.compound_parameters() == pksim_paths._COMPOUND_PARAM


def test_process_families_are_the_builders_and_the_bindings():
    assert set(parameters.builder_process_prefixes()) == set(build._PROCESS_FAMILIES)
    assert set(parameters.reference_elimination()) == set(build.REFERENCE_ELIMINATION)
    for cpf_id in CORPUS:
        assert cpf_id.startswith(parameters.process_prefixes()) == process_bindings.is_process_id(cpf_id), cpf_id


def test_s0_requirements_are_the_completeness_gate():
    empty = check_completeness(CPF(compound="Drug"))
    assert [r.message for r in parameters.s0_requirements()] == list(empty.missing)
    assert [r.requirement for r in parameters.s0_requirements()] == list(empty.missing_ids)
    elim = next(r for r in parameters.s0_requirements() if r.requirement == "elim")
    assert set(elim.excluding) == set(build.REFERENCE_ELIMINATION)


@pytest.mark.parametrize("ids", [(i,) for i in CORPUS] + [
    ("elim.fe_urine", "elim.fm.CYP3A4"), ("elim.fe_urine", "elim.renal.gfr_fraction"),
    ("phys.solubility.table",), ("phys.pka.neutral", "phys.mw"), ("phys.mw", "phys.logp", "bind.fu"),
])
def test_unmet_s0_is_what_completeness_reports(ids):
    cpf = CPF(compound="Drug", parameters=tuple(_record(i) for i in ids))
    assert [r.requirement for r in parameters.unmet_s0(ids)] == list(check_completeness(cpf).missing_ids)


@pytest.mark.parametrize("rule, problem", [
    ({"key": "elim.x", "placement": "process"}, "names a family"),
    ({"key": "form.", "suffix": ".shape", "storage": "dimensionless", "placement": "model"}, "only gives a storage"),
    ({"key": "elim.hepatic.", "suffix": ".clspec", "storage": "not_converted"}, "reason"),
    ({"key": "phys.", "pksim_compound": "Lipophilicity", "placement": "model"}, "one model id"),
    ({"key": "bind.fu", "physical_bounds": [1.0, 0.0]}, "low, high"),
])
def test_inconsistent_rules_are_refused(rule, problem):
    with pytest.raises(ValidationError, match=problem):
        parameters.ParameterRule.model_validate(rule)


def test_a_key_is_listed_once():
    reg = parameters.registry().model_dump()
    reg["parameters"] = [*reg["parameters"], reg["parameters"][0]]
    with pytest.raises(ValidationError, match="listed twice"):
        parameters.ParameterRegistry.model_validate(reg)


def test_an_alias_resolves_to_what_it_stands_for():
    # registry 1.1 (phase 4e): elim.hepatic.total_cl stands for the id PK-Sim's LiverClearance is bound to
    assert parameters.canonical("elim.hepatic.total_cl") == "elim.hepatic.total.plasma_clearance"
    assert parameters.canonical("elim.hepatic.total_cl@fed") == "elim.hepatic.total.plasma_clearance@fed"
    assert parameters.canonical("bind.fu") == "bind.fu"
    assert parameters.placement("elim.hepatic.total_cl") == parameters.placement("elim.hepatic.total.plasma_clearance") \
        == "process"
    assert parameters.storage_family("elim.hepatic.total.plasma_clearance") == "ml/min/kg"
    assert parameters.origin("elim.hepatic.total.plasma_clearance") == "in_vivo"
    assert parameters.origin("elim.hepatic.CYP3A4.clspec") == "in_vitro"


def test_a_refused_id_is_never_placed():
    assert parameters.refusal("elim.ehc_fraction") and "not harvested" in parameters.refusal("elim.ehc_fraction")
    assert parameters.placement("elim.ehc_fraction") is None
    assert parameters.refusal("bind.fu") is None


def test_total_plasma_clearance_alone_is_an_elimination_pathway_the_builder_places():
    from pbpk_domain.cpf.build import _compound_from_cpf, unplaceable_parameters
    from pbpk_domain.cpf.models import EngineBinding

    candidate = process_bindings.binding_candidates("elim.hepatic.total_cl")[0]
    clearance = _record("elim.hepatic.total.plasma_clearance").model_copy(
        update={"unit": candidate.unit, "engine_binding": candidate.binding("Literature")})
    compound_values = tuple(_record(i).model_copy(update={"value": v, "unit": u}) for i, v, u in (
        ("phys.mw", 300.0, "g/mol"), ("phys.logp", 2.0, "Log Units"), ("bind.fu", 0.3, None),
        ("phys.solubility.ref", 1.0, "mg/ml"), ("phys.pka.neutral", 1.0, None)))
    cpf = CPF(compound="Drug", parameters=(*compound_values, clearance))
    assert parameters.unmet_s0({p.id for p in cpf.parameters}) == ()
    assert unplaceable_parameters(cpf) == ()
    compound, used, _ = _compound_from_cpf(cpf)
    assert "elim.hepatic.total.plasma_clearance" in used
    assert [p.internal_name for p in compound.processes] == ["LiverClearance"]
    assert isinstance(clearance.engine_binding, EngineBinding) and clearance.unit == "ml/min/kg"


@pytest.mark.parametrize("rule, problem", [
    ({"key": "x.y", "alias_of": "a.b", "placement": "model"}, "alias or a refusal"),
    ({"key": "x.y", "alias_of": "a.b", "refused": "no"}, "not both"),
])
def test_inconsistent_aliases_are_refused(rule, problem):
    with pytest.raises(ValidationError, match=problem):
        parameters.ParameterRule.model_validate(rule)


def test_every_alias_stands_for_a_placed_id():
    for rule in parameters.registry().parameters:
        if rule.alias_of:
            assert parameters.placement(rule.alias_of) is not None, rule.key
