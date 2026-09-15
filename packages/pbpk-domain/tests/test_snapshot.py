import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from pbpk_domain.snapshot.builder import (
    CompoundSpec,
    DissolvedFormulationSpec,
    ExpressionSpec,
    FirstOrderMetabolism,
    GlomerularFiltration,
    IntravenousProtocolSpec,
    Measured,
    OralProtocolSpec,
    SimulationSpec,
    SnapshotBuilder,
    SnapshotBuildError,
    SubjectSpec,
)
from pbpk_domain.snapshot.models import Snapshot, ValueOrigin
from pbpk_domain.snapshot.validation import validate_references

REFERENCE_SNAPSHOT = os.environ.get("PBPK_REFERENCE_SNAPSHOT")

# Illustrative values only - not a qualified model of any real drug.
EXAMPLE_COMPOUND = CompoundSpec(
    name="Example-A",
    molecular_weight=Measured(value=325.8, unit="g/mol"),
    lipophilicity=Measured(value=3.1, unit="Log Units", origin=ValueOrigin(source="Publication", description="example")),
    fraction_unbound=Measured(value=0.03),
    solubility=Measured(value=0.05, unit="mg/ml"),
    intestinal_permeability=Measured(value=2.0e-4, unit="cm/min"),
    pka=[{"type": "Base", "pka": 6.0}],
    halogens={"Cl": 1, "F": 1},
    processes=[
        FirstOrderMetabolism(molecule="CYP3A4", data_source="Example", clearance_per_enzyme=Measured(value=0.5, unit="l/µmol/min")),
        GlomerularFiltration(data_source="assumed", gfr_fraction=Measured(value=1.0)),
    ],
)
EXAMPLE_SUBJECT = SubjectSpec(
    name="Adult male",
    gender="MALE",
    age_years=30,
    seed=12345,
    expression=[ExpressionSpec(molecule="CYP3A4", ontogeny="CYP3A4", reference_concentration=Measured(value=4.32, unit="µmol/l"))],
)


def example_builder() -> SnapshotBuilder:
    return (
        SnapshotBuilder()
        .add_compound(EXAMPLE_COMPOUND)
        .add_subject(EXAMPLE_SUBJECT)
        .add_protocol(IntravenousProtocolSpec(name="IV 2 mg", dose=Measured(value=2, unit="mg"), infusion_time_min=15))
        .add_protocol(OralProtocolSpec(name="PO 7.5 mg", dose=Measured(value=7.5, unit="mg")))
        .add_formulation(DissolvedFormulationSpec(name="Solution"))
        .add_simulation(SimulationSpec(name="IV", subject="Adult male", compound="Example-A", protocol="IV 2 mg", end_time_h=24))
        .add_simulation(
            SimulationSpec(name="PO", subject="Adult male", compound="Example-A", protocol="PO 7.5 mg", formulation="Solution", end_time_h=24)
        )
    )


def test_builder_produces_consistent_snapshot():
    snapshot = example_builder().build()
    assert validate_references(snapshot) == []
    data = snapshot.to_json_dict()
    assert data["Version"] == 80
    po = next(s for s in data["Simulations"] if s["Name"] == "PO")
    compound = po["Compounds"][0]
    assert compound["Protocol"] == {"Name": "PO 7.5 mg", "Formulations": [{"Name": "Solution", "Key": "Formulation"}]}
    assert {"Name": "CYP3A4-Example", "MoleculeName": "CYP3A4"} in compound["Processes"]
    assert {"Name": "Glomerular Filtration-assumed", "SystemicProcessType": "GFR"} in compound["Processes"]
    assert po["OutputSelections"] == ["Organism|PeripheralVenousBlood|Example-A|Plasma (Peripheral Venous Blood)"]
    assert data["Individuals"][0]["ExpressionProfiles"] == ["CYP3A4|Human|Healthy"]


def test_build_is_deterministic_and_round_trips():
    first, second = example_builder().build(), example_builder().build()
    assert first.sha256() == second.sha256()
    reparsed = Snapshot.model_validate_json(json.dumps(first.to_json_dict()))
    assert reparsed.to_json_dict() == first.to_json_dict()
    assert reparsed.sha256() == first.sha256()


def test_version_81_adds_application_name():
    builder = SnapshotBuilder(snapshot_version=81).add_compound(EXAMPLE_COMPOUND)
    data = builder.build().to_json_dict()
    assert list(data)[:2] == ["Version", "ApplicationName"]


def test_oral_simulation_without_formulation_is_rejected():
    builder = example_builder().add_simulation(
        SimulationSpec(name="PO no formulation", subject="Adult male", compound="Example-A", protocol="PO 7.5 mg", end_time_h=24)
    )
    with pytest.raises(SnapshotBuildError) as exc:
        builder.build()
    assert [i.code for i in exc.value.issues] == ["ORAL_WITHOUT_FORMULATION"]


def test_dangling_references_are_reported():
    builder = example_builder().add_simulation(
        SimulationSpec(name="Broken", subject="Nobody", compound="Example-A", protocol="IV 2 mg", end_time_h=1)
    )
    with pytest.raises(SnapshotBuildError) as exc:
        builder.build()
    assert "UNKNOWN_INDIVIDUAL" in {i.code for i in exc.value.issues}


def test_wrong_units_are_rejected_not_converted():
    with pytest.raises(ValidationError, match="Molecular weight must be given in 'g/mol'"):
        CompoundSpec(
            name="X",
            molecular_weight=Measured(value=0.3258, unit="kg/mol"),
            lipophilicity=Measured(value=3.1, unit="Log Units"),
            fraction_unbound=Measured(value=0.03),
        )
    with pytest.raises(ValidationError, match=r"\(0, 1\]"):
        CompoundSpec(
            name="X",
            molecular_weight=Measured(value=325.8, unit="g/mol"),
            lipophilicity=Measured(value=3.1, unit="Log Units"),
            fraction_unbound=Measured(value=3.0),
        )


def test_duplicate_names_are_rejected():
    with pytest.raises(ValueError, match="duplicate compound"):
        SnapshotBuilder().add_compound(EXAMPLE_COMPOUND).add_compound(EXAMPLE_COMPOUND)


@pytest.mark.skipif(not REFERENCE_SNAPSHOT, reason="set PBPK_REFERENCE_SNAPSHOT to a PK-Sim snapshot JSON file")
def test_real_pksim_snapshot_round_trips_losslessly():
    original = json.loads(Path(REFERENCE_SNAPSHOT).read_text(encoding="utf-8"))
    snapshot = Snapshot.model_validate(original)
    assert snapshot.to_json_dict() == original
    assert validate_references(snapshot) == []
