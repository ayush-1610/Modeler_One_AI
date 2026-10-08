"""Phase 4b: the parameter registry derives modeler_project's tables of CPF ids and answers, for every id the phase 4a
characterization recorded, what today's code answers (docs/plans/2026-10-08-parameter-registry.md). The pbpk_domain
tables are checked in packages/pbpk-domain/tests/test_parameter_registry.py.

When phase 4c/4d point the consumers at the registry, these equalities hold by construction; until then they prove the
registry is the same vocabulary.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from modeler_project import evidence, inputs
from pbpk_domain import parameters

pytestmark = pytest.mark.req("T-25")

SNAPSHOT = Path(__file__).resolve().parents[2] / "docs" / "architecture" / "parameter-vocabulary.json"
RECORDED = json.loads(SNAPSHOT.read_text(encoding="utf-8"))["ids"]
_METHOD = {"in_vivo": "InVivo", "in_vitro": "InVitro", None: "Unknown"}


def test_model_inputs_tables():
    assert parameters.model_ids() == inputs.MODEL_IDS
    assert set(parameters.model_prefixes()) == set(inputs.MODEL_PREFIXES)
    assert parameters.reference_ids() == inputs.REFERENCE_IDS
    assert set(parameters.reference_prefixes()) == set(inputs.REFERENCE_PREFIXES)
    assert parameters.builder_units() == inputs._BUILDER_UNIT
    assert set(parameters.origin_prefixes("in_vivo")) == set(inputs._IN_VIVO)
    assert set(parameters.origin_prefixes("in_vitro")) == set(inputs._IN_VITRO)


def test_evidence_bounds_table():
    assert parameters.physical_bounds() == evidence._PHYSICAL


@pytest.mark.parametrize("cpf_id", sorted(RECORDED))
def test_registry_answers_what_was_recorded(cpf_id):
    recorded = RECORDED[cpf_id]
    family = parameters.storage_family(cpf_id)
    name = parameters.compound_parameters().get(cpf_id)
    bounds = parameters.physical_bounds().get(cpf_id)
    present = {cpf_id}
    satisfied = {r.requirement for r in parameters.s0_requirements()} - {r.requirement for r in parameters.unmet_s0(present)}
    assert parameters.placement(cpf_id) == recorded["placement"]
    assert ("not converted" if family is False else family) == recorded["storage_family"]
    assert cpf_id.startswith(parameters.process_prefixes()) == recorded["process_id"]
    assert (list(bounds) if bounds else None) == recorded["physical_bounds"]
    assert _METHOD[parameters.origin(cpf_id)] == recorded["value_origin_method"]
    assert sorted(satisfied) == recorded["s0_satisfies"]
    if name:
        assert recorded["compound_path"] == f"Drug|{name}"
    else:
        assert recorded["compound_path"].startswith("ParameterPathError")
