"""Build the platform example snapshot (compound, subject, IV + oral simulations, observed data).

Used by golden_roundtrip.R to prove that PK-Sim loads, converts and runs what the platform builds.
Values are illustrative and the observed data are synthetic; this is not a model of a real drug.

    uv run python services/engine-worker/golden/make_example_snapshot.py out/example_snapshot.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from modeler_intake.pksim import to_observed_data
from modeler_intake.records import ConcentrationObservation, SourceRef
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
    SubjectSpec,
)
from pbpk_domain.snapshot.models import Snapshot
from pbpk_domain.snapshot.validation import validate_references

COMPOUND = "Example-A"
MOLECULAR_WEIGHT = 325.8
PLASMA = f"Organism|PeripheralVenousBlood|{COMPOUND}|Plasma (Peripheral Venous Blood)"
SYNTHETIC_PO = [(0.5, 18.0, 5.0), (1, 31.0, 8.0), (2, 29.0, 7.5), (4, 19.0, 5.0), (8, 8.5, 2.5), (12, 4.1, 1.3), (24, 0.9, 0.4)]


def build() -> dict:
    snapshot = (
        SnapshotBuilder()
        .add_compound(
            CompoundSpec(
                name=COMPOUND,
                molecular_weight=Measured(value=MOLECULAR_WEIGHT, unit="g/mol"),
                lipophilicity=Measured(value=3.1, unit="Log Units"),
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
        )
        .add_subject(
            SubjectSpec(
                name="Adult male",
                gender="MALE",
                age_years=30,
                seed=12345,
                expression=[ExpressionSpec(molecule="CYP3A4", ontogeny="CYP3A4", reference_concentration=Measured(value=4.32, unit="µmol/l"))],
            )
        )
        .add_protocol(IntravenousProtocolSpec(name="IV 2 mg", dose=Measured(value=2, unit="mg"), infusion_time_min=15))
        .add_protocol(OralProtocolSpec(name="PO 7.5 mg", dose=Measured(value=7.5, unit="mg")))
        .add_formulation(DissolvedFormulationSpec(name="Solution"))
        .add_simulation(SimulationSpec(name="IV", subject="Adult male", compound=COMPOUND, protocol="IV 2 mg", end_time_h=24))
        .add_simulation(
            SimulationSpec(name="PO", subject="Adult male", compound=COMPOUND, protocol="PO 7.5 mg", formulation="Solution", end_time_h=24)
        )
        .build()
    )

    observations = [
        ConcentrationObservation(
            study_id="SYNTHETIC-EXAMPLE", analyte=COMPOUND, matrix="plasma", series="7.5 mg solution", statistic="arithmetic_mean",
            time=t, time_unit="h", value=mean, unit="ng/ml", sd=sd, lloq=0.5, n=12, dose=7.5, dose_unit="mg", route="oral", food_state="Fasted",
            source=SourceRef(file_sha256="0" * 64, recipe_id="synthetic", recipe_version=1, cells={"time": f"PK!A{i}", "value": f"PK!B{i}"}),
        )
        for i, (t, mean, sd) in enumerate(SYNTHETIC_PO, start=2)
    ]
    (observed,) = to_observed_data(observations, MOLECULAR_WEIGHT)

    data = snapshot.to_json_dict()
    data["ObservedData"] = [observed]
    po = next(s for s in data["Simulations"] if s["Name"] == "PO")
    po["ObservedData"] = [observed["Name"]]
    po["OutputMappings"] = [{"Scaling": "Linear", "Path": f"PO|{PLASMA}", "ObservedData": observed["Name"]}]

    issues = validate_references(Snapshot.model_validate(data))
    if issues:
        raise SystemExit("; ".join(map(str, issues)))
    return data


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "example_snapshot.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)
