"""Guard the committed engine catalog (services/engine-worker/golden/catalog.json).

This is the authoritative catalog harvested on the Linux engine (T-02). CI pins its invariants so a bad
re-harvest, or an accidental edit, cannot slip in: every reference snapshot must have loaded in the engine,
the process-selection naming convention the builder relies on must hold, and the process/formulation names
the builder binds to must be present. It also proves a CPF binds against the real catalog end to end.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pbpk_domain.catalog import Catalog
from pbpk_domain.cpf import CPF, EngineBinding, ParameterRecord, ParameterStatus, Provenance, bind

CATALOG_PATH = Path(__file__).parents[3] / "services" / "engine-worker" / "golden" / "catalog.json"


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    if not CATALOG_PATH.exists():
        pytest.skip("authoritative catalog.json not present (run scripts/harvest_catalog.sh on the engine server)")
    return Catalog.load(CATALOG_PATH)


def test_engine_metadata(catalog: Catalog) -> None:
    assert catalog.engine.ospsuite == "12.4.4"
    assert catalog.engine.snapshot_version == 80
    assert catalog.engine.platform is not None and "linux" in catalog.engine.platform


def test_all_reference_snapshots_loaded_in_engine(catalog: Catalog) -> None:
    assert len(catalog.fixtures) >= 4
    names = {f.name for f in catalog.fixtures}
    assert {"Dapagliflozin-Model", "Midazolam-Model", "Itraconazole-Model", "Rifampicin-Model"} <= names
    assert all(f.roundtrip_ok is True for f in catalog.fixtures), "every reference snapshot must load in the engine on Linux"


def test_selection_naming_convention_holds(catalog: Catalog) -> None:
    # Confirms the {molecule}-{data_source} convention that validation.process_selection_for relies on.
    assert catalog.selection_pattern_confirmed()


def test_process_and_formulation_types_present(catalog: Catalog) -> None:
    procs = {p.internal_name for p in catalog.process_types}
    assert "MetabolizationSpecific_FirstOrder" in procs
    assert "GlomerularFiltration" in procs
    forms = {f.internal_name for f in catalog.formulation_types}
    assert "Formulation_Dissolved" in forms
    assert "Formulation_Tablet_Weibull" in forms


def test_units_the_builder_requires_are_known(catalog: Catalog) -> None:
    assert catalog.is_unit("Molecular weight", "g/mol")
    assert catalog.is_unit("Log Units", "Log Units")
    assert catalog.is_unit("Concentration (mass)", "µg/l")
    assert catalog.has_pk_parameter("AUC_inf")
    assert catalog.has_species("Human")
    assert catalog.has_population("Human", "European_ICRP_2002")


def test_first_order_metabolism_clspec_binds(catalog: Catalog) -> None:
    proc = catalog.require_process_type("MetabolizationSpecific_FirstOrder")
    assert "CLspec/[Enzyme]" in proc.parameter_names()
    clspec_unit = next(p.unit for p in proc.parameters if p.name == "CLspec/[Enzyme]")
    cpf = CPF(
        compound="Probe",
        parameters=(
            ParameterRecord(
                id="elim.hepatic.CYP3A4.clspec", value=0.5, unit=clspec_unit, status=ParameterStatus.FITTED,
                provenance=Provenance(source_type="IVIVE"),
                engine_binding=EngineBinding(building_block="Compound", process="MetabolizationSpecific_FirstOrder:CYP3A4", parameter="CLspec/[Enzyme]"),
            ),
        ),
    )
    plan = bind(cpf, catalog)
    assert len(plan.for_process("MetabolizationSpecific_FirstOrder", "CYP3A4")) == 1
