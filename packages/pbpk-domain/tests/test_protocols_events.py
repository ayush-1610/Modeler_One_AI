"""T-10: multiple-dose protocols (DosingInterval + End time) and meal events (template + simulation
reference). Structures match the OSP Itraconazole/Midazolam models."""

from __future__ import annotations

import pytest

from pbpk_domain.cpf import CPF, ParameterRecord, ParameterStatus, Provenance, build_from_cpf
from pbpk_domain.cpf.build import Scenario
from pbpk_domain.snapshot.builder import (
    CompoundSpec,
    DissolvedFormulationSpec,
    IntravenousProtocolSpec,
    MealEventSpec,
    Measured,
    OralProtocolSpec,
    SimulationSpec,
    SnapshotBuilder,
    SnapshotBuildError,
    SubjectSpec,
)


def _compound_records():
    prov = Provenance(source_type="measured")
    return (
        ParameterRecord(id="phys.mw", value=450.0, unit="g/mol", status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="phys.logp", value=2.2, unit="Log Units", status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="bind.fu", value=0.08, status=ParameterStatus.FIXED, provenance=prov),
    )


# --- multiple-dose protocols ---------------------------------------------------------------------


def test_single_dose_default_unchanged() -> None:
    proto = OralProtocolSpec(name="PO 10 mg", dose=Measured(value=10.0, unit="mg")).to_protocol()
    assert proto.dosing_interval == "Single"
    assert {p.name for p in proto.parameters} == {"Start time", "InputDose", "Volume of water/body weight"}


def test_oral_multiple_dose_bid() -> None:
    proto = OralProtocolSpec(
        name="PO 10 mg BID", dose=Measured(value=10.0, unit="mg"),
        dosing_interval="DI_12_12", end_time=Measured(value=16, unit="day(s)"),
    ).to_protocol()
    assert proto.dosing_interval == "DI_12_12"
    end = next(p for p in proto.parameters if p.name == "End time")
    assert end.value == 16
    assert end.unit == "day(s)"


def test_iv_multiple_dose_qd() -> None:
    proto = IntravenousProtocolSpec(
        name="IV 100 mg QD", dose=Measured(value=100.0, unit="mg"), infusion_time_min=30,
        dosing_interval="DI_24", end_time=Measured(value=7, unit="day(s)"),
    ).to_protocol()
    assert proto.dosing_interval == "DI_24"
    assert any(p.name == "End time" for p in proto.parameters)


def test_multiple_dose_requires_end_time() -> None:
    with pytest.raises(ValueError, match="needs an end_time"):
        OralProtocolSpec(name="x", dose=Measured(value=10.0, unit="mg"), dosing_interval="DI_24")


def test_end_time_unit_validated() -> None:
    with pytest.raises(ValueError, match="End time must be"):
        OralProtocolSpec(name="x", dose=Measured(value=10.0, unit="mg"), dosing_interval="DI_24",
                         end_time=Measured(value=7, unit="min"))


# --- meal events ---------------------------------------------------------------------------------


def test_meal_event_builds_and_is_referenced() -> None:
    snapshot = (
        SnapshotBuilder()
        .add_compound(_compound())
        .add_subject(SubjectSpec(name="Adult", gender="MALE", age_years=35, seed=1))
        .add_protocol(OralProtocolSpec(name="PO 10 mg", dose=Measured(value=10.0, unit="mg")))
        .add_formulation(DissolvedFormulationSpec(name="Dissolved"))
        .add_event(MealEventSpec(name="breakfast", template="Meal: High-fat breakfast (Human)"))
        .add_simulation(SimulationSpec(name="PO fed", subject="Adult", compound="Probe", protocol="PO 10 mg",
                                       formulation="Dissolved", end_time_h=24, events=("breakfast",)))
        .build()
    )
    assert len(snapshot.events) == 1
    assert snapshot.events[0].template == "Meal: High-fat breakfast (Human)"
    sim_events = snapshot.simulations[0].events
    assert sim_events[0]["Name"] == "breakfast"
    assert sim_events[0]["StartTime"]["Unit"] == "h"


def test_simulation_referencing_unknown_event_fails() -> None:
    with pytest.raises(SnapshotBuildError, match="event"):
        (
            SnapshotBuilder()
            .add_compound(_compound())
            .add_subject(SubjectSpec(name="Adult", gender="MALE", age_years=35, seed=1))
            .add_protocol(OralProtocolSpec(name="PO 10 mg", dose=Measured(value=10.0, unit="mg")))
            .add_formulation(DissolvedFormulationSpec(name="Dissolved"))
            .add_simulation(SimulationSpec(name="PO fed", subject="Adult", compound="Probe", protocol="PO 10 mg",
                                           formulation="Dissolved", end_time_h=24, events=("no-such-meal",)))
            .build()
        )


def _compound():
    return CompoundSpec(
        name="Probe",
        molecular_weight=Measured(value=450.0, unit="g/mol"),
        lipophilicity=Measured(value=2.2, unit="Log Units"),
        fraction_unbound=Measured(value=0.08),
    )


# --- fed scenario through build_from_cpf ---------------------------------------------------------


def test_fed_scenario_via_cpf_build() -> None:
    cpf = CPF(compound="Probe", parameters=_compound_records())
    subjects = [SubjectSpec(name="Adult", gender="MALE", age_years=35, seed=1)]
    fed = Scenario(
        simulation=SimulationSpec(name="PO 10 mg fed BID", subject="Adult", compound="Probe",
                                  protocol="PO 10 mg BID", formulation="Dissolved", end_time_h=48, events=("breakfast",)),
        protocol=OralProtocolSpec(name="PO 10 mg BID", dose=Measured(value=10.0, unit="mg"),
                                  dosing_interval="DI_12_12", end_time=Measured(value=2, unit="day(s)")),
        formulation=DissolvedFormulationSpec(name="Dissolved"),
        events=(MealEventSpec(name="breakfast", template="Meal: High-fat breakfast (Human)"),),
    )
    snapshot, _ = build_from_cpf(cpf, subjects, [fed])
    assert len(snapshot.events) == 1
    assert snapshot.protocols[0].dosing_interval == "DI_12_12"
    assert snapshot.simulations[0].events[0]["Name"] == "breakfast"
