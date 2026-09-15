"""Build a snapshot that exercises the T-10 compound processes so the engine can round-trip them.

A single hypothetical compound cleared by saturable (Michaelis-Menten) metabolism through CYP3A4 and by
active transport through P-gp, plus glomerular filtration, with the enzyme and transporter expression
profiles those processes require. Values are illustrative; this is a structure/round-trip fixture, not a
model of a real drug. Regenerate with:

    uv run python services/engine-worker/golden/make_process_coverage_snapshot.py out/process_coverage_snapshot.json

Then verify it loads and runs in the engine (on Linux):

    LC_ALL=en_US.UTF-8 Rscript services/engine-worker/golden/golden_roundtrip.R <snapshot.json> /tmp/pc
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pbpk_domain.snapshot.builder import (
    CompoundSpec,
    DissolvedFormulationSpec,
    ExpressionSpec,
    GlomerularFiltration,
    IntravenousProtocolSpec,
    Measured,
    MichaelisMentenMetabolism,
    OralProtocolSpec,
    SimulationSpec,
    SnapshotBuilder,
    SubjectSpec,
    TransporterMichaelisMenten,
)

COMPOUND = "ProcessProbe"


def build() -> dict:
    compound = CompoundSpec(
        name=COMPOUND,
        molecular_weight=Measured(value=450.0, unit="g/mol"),
        lipophilicity=Measured(value=2.2, unit="Log Units"),
        fraction_unbound=Measured(value=0.08),
        solubility=Measured(value=0.2, unit="mg/ml"),
        intestinal_permeability=Measured(value=1.5e-4, unit="cm/min"),
        pka=[{"type": "Base", "pka": 7.2}],
        processes=[
            MichaelisMentenMetabolism(
                molecule="CYP3A4", data_source="illustrative",
                vmax=Measured(value=6.5, unit="µmol/l/min"), km=Measured(value=180.0, unit="µmol/l"),
            ),
            TransporterMichaelisMenten(
                molecule="P-gp", data_source="illustrative",
                vmax=Measured(value=2.9, unit="µmol/l/min"), km=Measured(value=55.0, unit="µmol/l"),
            ),
            GlomerularFiltration(data_source="assumed", gfr_fraction=Measured(value=1.0)),
        ],
    )
    subject = SubjectSpec(
        name="Adult male", gender="MALE", age_years=35, seed=1234,
        expression=[
            ExpressionSpec(type="Enzyme", molecule="CYP3A4"),
            ExpressionSpec(type="Transporter", molecule="P-gp"),
        ],
    )
    snapshot = (
        SnapshotBuilder()
        .add_compound(compound)
        .add_subject(subject)
        .add_protocol(IntravenousProtocolSpec(name="IV 1 mg", dose=Measured(value=1.0, unit="mg"), infusion_time_min=15))
        .add_protocol(OralProtocolSpec(name="PO 10 mg", dose=Measured(value=10.0, unit="mg")))
        .add_formulation(DissolvedFormulationSpec(name="Dissolved"))
        .add_simulation(SimulationSpec(name="IV 1 mg", subject="Adult male", compound=COMPOUND, protocol="IV 1 mg", end_time_h=24))
        .add_simulation(SimulationSpec(name="PO 10 mg", subject="Adult male", compound=COMPOUND, protocol="PO 10 mg", formulation="Dissolved", end_time_h=24))
        .build()
    )
    return snapshot.to_json_dict()


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("process_coverage_snapshot.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build(), indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
