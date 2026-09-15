import pytest

from pbpk_domain.snapshot.builder import (
    CompoundSpec,
    DissolvedFormulationSpec,
    IntravenousProtocolSpec,
    Measured,
    OralProtocolSpec,
    SimulationSpec,
    SnapshotBuilder,
    SubjectSpec,
)


@pytest.fixture
def example_snapshot():
    """Small IV + oral snapshot with illustrative values (not a model of a real drug)."""
    return (
        SnapshotBuilder()
        .add_compound(
            CompoundSpec(
                name="Example-A",
                molecular_weight=Measured(value=325.8, unit="g/mol"),
                lipophilicity=Measured(value=3.1, unit="Log Units"),
                fraction_unbound=Measured(value=0.03),
            )
        )
        .add_subject(SubjectSpec(name="Adult male", gender="MALE", age_years=30, seed=12345))
        .add_protocol(IntravenousProtocolSpec(name="IV 2 mg", dose=Measured(value=2, unit="mg"), infusion_time_min=15))
        .add_protocol(OralProtocolSpec(name="PO 7.5 mg", dose=Measured(value=7.5, unit="mg")))
        .add_formulation(DissolvedFormulationSpec(name="Solution"))
        .add_simulation(SimulationSpec(name="IV", subject="Adult male", compound="Example-A", protocol="IV 2 mg", end_time_h=24))
        .add_simulation(
            SimulationSpec(name="PO", subject="Adult male", compound="Example-A", protocol="PO 7.5 mg", formulation="Solution", end_time_h=24)
        )
        .build()
    )
