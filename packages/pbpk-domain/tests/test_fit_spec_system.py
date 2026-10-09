"""Fit ids in a model system: another compound's parameter is fitted as ``<compound>::<id>`` (multi-compound phase 2,
D-25). Uses the published OSP Itraconazole system (parent and three metabolites, fixtures/SOURCES.md)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pbpk_domain.fit_spec import (
    FitSimulation,
    FitSpecError,
    build_fit_spec,
    by_compound,
    pi_observed,
    qualify,
    resolve_fit_ids,
    split_fit_id,
)
from pbpk_domain.pksim_paths import pksim_parameter_path
from pbpk_domain.reference.osp_import import import_osp_system

FIXTURES = Path(__file__).resolve().parents[3] / "services" / "engine-worker" / "golden" / "fixtures"
HYDROXY = "Hydroxy-Itraconazole"
pytestmark = pytest.mark.req("T-14")


@pytest.fixture(scope="module")
def system():
    snapshot = json.loads((FIXTURES / "Itraconazole-Model.json").read_text(encoding="utf-8"))
    return import_osp_system(snapshot).system


def _simulation() -> FitSimulation:
    observed = pi_observed("st", [0.0, 60.0], [0.0, 1.0], time_unit="min", unit="µmol/l", mol_weight=721.0,
                           dimension="Concentration (molar)")
    return FitSimulation(study_id="st", pkml="st.pkml", output_path="Organism|x", observed=observed)


def test_fit_ids_qualify_only_another_compounds_parameter():
    assert qualify("Itraconazole", "phys.logp", "Itraconazole") == "phys.logp"
    assert qualify(HYDROXY, "phys.logp", "Itraconazole") == f"{HYDROXY}::phys.logp"
    assert split_fit_id(f"{HYDROXY}::phys.logp") == (HYDROXY, "phys.logp")
    assert split_fit_id("phys.logp") == (None, "phys.logp")
    assert by_compound({"phys.logp": 1.0, f"{HYDROXY}::bind.fu": 2.0}, "Itraconazole") == {
        "Itraconazole": {"phys.logp": 1.0}, HYDROXY: {"bind.fu": 2.0}}


def test_a_qualified_target_resolves_against_its_own_compound(system):
    parent = system.cpf("Itraconazole")
    target = f"{HYDROXY}::elim.hepatic.{{enzyme}}.kcat"
    assert resolve_fit_ids(parent, target, system) == (f"{HYDROXY}::elim.hepatic.CYP3A4.kcat",)
    # the fitted compound's own qualified id is its bare id; outside a system, or for a stranger, nothing matches
    assert resolve_fit_ids(parent, "Itraconazole::phys.logp", system) == ("phys.logp",)
    assert resolve_fit_ids(parent, target) == ()
    assert resolve_fit_ids(parent, "Nobody::phys.logp", system) == ()
    # a bare target is still the fitted compound's, exactly as before
    assert resolve_fit_ids(parent, "elim.hepatic.{enzyme}.kcat", system) == ("elim.hepatic.CYP3A4.kcat",)


def test_the_fit_spec_places_another_compounds_parameter_at_its_own_path(system):
    parent, hydroxy = system.cpf("Itraconazole"), system.cpf(HYDROXY)
    kcat = f"{HYDROXY}::elim.hepatic.CYP3A4.kcat"
    spec = build_fit_spec(parent, ["phys.logp", kcat], [_simulation()], system=system,
                          bounds_override={"phys.logp": (3.0, 6.0), kcat: (0.001, 1.0)})
    by_name = {p["name"]: p for p in spec["parameters"]}
    assert by_name["phys.logp"]["paths"][0]["path"] == pksim_parameter_path(parent.get("phys.logp"), compound="Itraconazole")
    record = hydroxy.get("elim.hepatic.CYP3A4.kcat")
    assert by_name[kcat]["paths"][0]["path"] == pksim_parameter_path(record, compound=HYDROXY)
    assert HYDROXY in by_name[kcat]["paths"][0]["path"]
    assert by_name[kcat]["start"] == pytest.approx(record.numeric_value)  # the metabolite's own value, not the parent's


def test_a_qualified_id_needs_its_system(system):
    parent = system.cpf("Itraconazole")
    with pytest.raises(FitSpecError, match="not a compound of this fit's model system"):
        build_fit_spec(parent, [f"{HYDROXY}::phys.logp"], [_simulation()],
                       bounds_override={f"{HYDROXY}::phys.logp": (1.0, 5.0)})
