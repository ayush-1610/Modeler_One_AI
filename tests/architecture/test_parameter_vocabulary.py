"""The CPF parameter ids are listed independently in several modules; this test keeps those lists consistent.

Until phase 4 replaces them with one parameter registry in pbpk_domain (docs/ARCHITECTURE_BOUNDARIES.md, C1), the ids
a value may target live in `parameter_units` (storage units), `pksim_paths` (PK-Sim compound parameters),
`cpf.process_bindings` (process parameters), `cpf.build` and `cpf.completeness` (S0), `modeler_project.inputs` (what
the model takes) and `modeler_project.evidence` (physical bounds). A new id added to one list and not the others
passed every other test and produced a model without the value. The test reads those tables as they are, private
ones included, on purpose: it pins today's vocabulary, and goes away with the registry.

Known drift is marked xfail(strict=True): when it is fixed (a science change, with the owner's approval) the test
turns red until the mark is removed.
"""

from __future__ import annotations

import re

import pytest

from modeler_project import evidence, inputs
from pbpk_domain import parameter_units, pksim_paths
from pbpk_domain.cpf.build import REFERENCE_ELIMINATION
from pbpk_domain.cpf.completeness import check_completeness
from pbpk_domain.cpf.models import CPF, ParameterRecord, ParameterStatus, Provenance

pytestmark = pytest.mark.req("T-25")

# One concrete id per storage-unit target in parameter_units._TARGETS (a prefix there covers a family of ids).
EXAMPLES = {
    "phys.mw": "phys.mw",
    "phys.logp": "phys.logp",
    "phys.pka": "phys.pka.acid.1",
    "bind.fu": "bind.fu",
    "dist.bp_ratio": "dist.bp_ratio",
    "phys.solubility.ref": "phys.solubility.ref",
    "perm.intestinal": "perm.intestinal",
    "perm.cellular": "perm.cellular",
    "elim.renal.gfr_fraction": "elim.renal.gfr_fraction",
    "elim.hepatic.total_cl": "elim.hepatic.total_cl",
    "elim.hepatic.total.plasma_clearance": "elim.hepatic.total.plasma_clearance",
    "elim.ehc_fraction": "elim.ehc_fraction",
    "elim.fe_urine": "elim.fe_urine",
    "elim.fm": "elim.fm.CYP3A4",
    "form.": "form.tablet.weibull.t50",
}

# elim.hepatic.total_cl was here until phase 4e made it an alias of elim.hepatic.total.plasma_clearance (registry 1.1)
DRIFT = {
    "elim.ehc_fraction": "converts to a storage unit but is refused (registry 1.1): MS-01 places it on the Individual "
                         "(Organism|Liver|EHC continuous fraction), a path not harvested yet; harvest it to place it",
}
_ID = re.compile(r"\b[a-z]+(?:\.[a-z0-9_]+)+\b")


def _placeable(cpf_id: str) -> bool:
    return inputs.placement(cpf_id) is not None


def _case(cpf_id: str):
    reason = DRIFT.get(cpf_id)
    return pytest.param(cpf_id, marks=pytest.mark.xfail(strict=True, reason=reason)) if reason else cpf_id


def test_examples_cover_every_storage_unit_target():
    assert set(EXAMPLES) == {prefix for prefix, _ in parameter_units._TARGETS}
    for prefix, example in EXAMPLES.items():
        family = dict(parameter_units._TARGETS)[prefix]
        assert parameter_units.target_family(example) == family, example


@pytest.mark.parametrize("cpf_id", [_case(example) for example in EXAMPLES.values()])
def test_every_storage_unit_target_is_placeable(cpf_id):
    assert _placeable(cpf_id), cpf_id


@pytest.mark.parametrize("cpf_id", [t.replace("<enzyme>", "CYP3A4") for t in inputs.PATHWAY_TARGETS])
def test_every_advertised_pathway_target_is_placeable(cpf_id):
    assert _placeable(cpf_id), cpf_id


def _s0_ids() -> list[str]:
    report = check_completeness(CPF(compound="Drug"))
    named = {m for message in report.missing for m in _ID.findall(message)}
    return sorted((named | set(report.missing_ids)) - set(inputs.PLACEHOLDERS))


@pytest.mark.parametrize("cpf_id", [_case(i) for i in _s0_ids()])
def test_every_id_s0_asks_for_is_placeable(cpf_id):
    assert _placeable(cpf_id), cpf_id


def test_s0_placeholders_are_declared():
    report = check_completeness(CPF(compound="Drug"))
    assert {"elim", "phys.pka"} <= set(report.missing_ids)
    assert {"elim", "phys.pka"} <= set(inputs.PLACEHOLDERS)


def test_pksim_compound_parameters_are_model_inputs():
    for cpf_id in pksim_paths._COMPOUND_PARAM:
        assert cpf_id in inputs.MODEL_IDS and inputs.placement(cpf_id) == "model", cpf_id


@pytest.mark.parametrize("cpf_id", sorted(evidence._PHYSICAL))
def test_physical_bounds_name_placeable_ids(cpf_id):
    assert _placeable(cpf_id), cpf_id


def _record(cpf_id: str, value: float) -> ParameterRecord:
    return ParameterRecord(id=cpf_id, value=value, status=ParameterStatus.FIXED,
                           provenance=Provenance(source_type="measured", reference="vocabulary test"))


def test_reference_elimination_agrees_between_builder_inputs_and_s0():
    referenced = {i for i in inputs.REFERENCE_IDS if i.startswith("elim.")} | set(inputs.REFERENCE_PREFIXES)
    assert referenced == set(REFERENCE_ELIMINATION)
    for cpf_id in ("elim.fe_urine", "elim.fm.CYP3A4"):
        assert inputs.placement(cpf_id) == "reference", cpf_id
    # fe and fm describe elimination; they are not a pathway the model has, so S0 still asks for one
    clinical = CPF(compound="Drug", parameters=(_record("elim.fe_urine", 0.45), _record("elim.fm.CYP3A4", 0.2)))
    assert "elim" in check_completeness(clinical).missing_ids
    pathway = CPF(compound="Drug", parameters=(*clinical.parameters, _record("elim.renal.gfr_fraction", 1.0)))
    assert "elim" not in check_completeness(pathway).missing_ids
