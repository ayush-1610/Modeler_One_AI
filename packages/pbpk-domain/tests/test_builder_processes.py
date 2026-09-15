"""T-10: new compound processes (Michaelis-Menten metabolism, transporters, competitive inhibition,
induction, specific binding) and transporter expression profiles. Names and units are the ones harvested
from the OSP models (see services/engine-worker/golden/catalog.json)."""

from __future__ import annotations

import pytest

from pbpk_domain.cpf import CPF, EngineBinding, ParameterRecord, ParameterStatus, Provenance, build_from_cpf
from pbpk_domain.cpf.build import Scenario
from pbpk_domain.snapshot.builder import (
    CompetitiveInhibition,
    CompoundSpec,
    ExpressionSpec,
    Induction,
    IntravenousProtocolSpec,
    Measured,
    MichaelisMentenMetabolism,
    SimulationSpec,
    SnapshotBuilder,
    SpecificBinding,
    SubjectSpec,
    TransporterMichaelisMenten,
)
from pbpk_domain.snapshot.validation import process_selection_for


def um(v):  # µmol/l
    return Measured(value=v, unit="µmol/l")


def umin(v):  # µmol/l/min
    return Measured(value=v, unit="µmol/l/min")


# --- process specs emit the exact engine names/units ---------------------------------------------


def test_mm_metabolism_process() -> None:
    proc = MichaelisMentenMetabolism(molecule="CYP3A4", data_source="lit", vmax=umin(6.5), km=um(195.1)).to_process()
    assert proc.internal_name == "MetabolizationSpecific_MM"
    assert proc.molecule == "CYP3A4"
    assert [p.name for p in proc.parameters] == ["Vmax", "Km"]
    assert proc.parameters[0].unit == "µmol/l/min"


def test_mm_metabolism_optional_params() -> None:
    proc = MichaelisMentenMetabolism(
        molecule="CYP3A4", data_source="lit", vmax=umin(6.5), km=um(195.1),
        kcat=Measured(value=9.8, unit="1/min"), enzyme_concentration=um(1.0),
    ).to_process()
    assert [p.name for p in proc.parameters] == ["Enzyme concentration", "Vmax", "Km", "kcat"]


def test_transporter_process() -> None:
    proc = TransporterMichaelisMenten(
        molecule="P-gp", data_source="Collett 2004", vmax=umin(2.87), km=um(55),
        transporter_concentration=Measured(value=60, unit="nmol/l"),
    ).to_process()
    assert proc.internal_name == "ActiveTransportSpecific_MM"
    assert [p.name for p in proc.parameters] == ["Transporter concentration", "Vmax", "Km"]


def test_competitive_inhibition_and_induction() -> None:
    inh = CompetitiveInhibition(molecule="CYP2C8", data_source="lit", ki=um(30.2)).to_process()
    assert inh.internal_name == "CompetitiveInhibition"
    assert inh.parameters[0].name == "Ki"
    ind = Induction(molecule="CYP1A2", data_source="lit", ec50=um(0.34), emax=Measured(value=0.65)).to_process()
    assert [p.name for p in ind.parameters] == ["EC50", "Emax"]
    assert ind.parameters[1].unit is None  # Emax is dimensionless


def test_specific_binding_process() -> None:
    proc = SpecificBinding(molecule="GABRG2", data_source="Buhr 1997",
                           koff=Measured(value=1, unit="1/min"), kd=Measured(value=1.8, unit="nmol/l")).to_process()
    assert proc.internal_name == "SpecificBinding"
    assert [p.name for p in proc.parameters] == ["koff", "Kd"]


def test_wrong_units_rejected() -> None:
    with pytest.raises(ValueError, match="Vmax"):
        MichaelisMentenMetabolism(molecule="X", data_source="d", vmax=um(1.0), km=um(1.0))  # vmax in µmol/l, not µmol/l/min
    with pytest.raises(ValueError, match="Ki"):
        CompetitiveInhibition(molecule="X", data_source="d", ki=Measured(value=1.0, unit="nmol/l"))


def test_new_processes_get_molecule_dash_datasource_selection() -> None:
    for proc in (
        MichaelisMentenMetabolism(molecule="CYP3A4", data_source="lit", vmax=umin(6.5), km=um(195)).to_process(),
        TransporterMichaelisMenten(molecule="P-gp", data_source="Collett 2004", vmax=umin(2.87), km=um(55)).to_process(),
        CompetitiveInhibition(molecule="CYP2C8", data_source="Kajosaari 2005", ki=um(30.2)).to_process(),
    ):
        sel = process_selection_for(proc)
        assert sel is not None
        assert sel.name == f"{proc.molecule}-{proc.data_source}"


# --- transporter expression profile --------------------------------------------------------------


def test_transporter_expression_profile_has_no_localization() -> None:
    profile = ExpressionSpec(type="Transporter", molecule="P-gp").to_profile()
    dumped = profile.model_dump(by_alias=True, exclude_none=True)
    assert dumped["Type"] == "Transporter"
    assert "Localization" not in dumped
    assert profile.reference_name == "P-gp|Human|Healthy"


def test_enzyme_expression_keeps_localization() -> None:
    profile = ExpressionSpec(type="Enzyme", molecule="CYP3A4").to_profile()
    dumped = profile.model_dump(by_alias=True, exclude_none=True)
    assert "Localization" in dumped


def test_transporter_type_emitted_when_set() -> None:
    profile = ExpressionSpec(type="Transporter", molecule="P-gp", transporter_type="Efflux").to_profile()
    dumped = profile.model_dump(by_alias=True, exclude_none=True)
    assert dumped["TransporterType"] == "Efflux"


# --- full snapshot with the new processes builds and validates -----------------------------------


def test_snapshot_with_mm_and_transporter_builds() -> None:
    compound = CompoundSpec(
        name="Perp-A",
        molecular_weight=Measured(value=822.9, unit="g/mol"),
        lipophilicity=Measured(value=2.5, unit="Log Units"),
        fraction_unbound=Measured(value=0.1),
        processes=[
            MichaelisMentenMetabolism(molecule="CYP3A4", data_source="lit", vmax=umin(6.5), km=um(195)),
            TransporterMichaelisMenten(molecule="P-gp", data_source="Collett 2004", vmax=umin(2.87), km=um(55)),
        ],
    )
    subject = SubjectSpec(
        name="Adult", gender="MALE", age_years=35, seed=1,
        expression=[ExpressionSpec(type="Enzyme", molecule="CYP3A4"), ExpressionSpec(type="Transporter", molecule="P-gp")],
    )
    snapshot = (
        SnapshotBuilder().add_compound(compound).add_subject(subject)
        .add_protocol(IntravenousProtocolSpec(name="IV 1 mg", dose=Measured(value=1.0, unit="mg"), infusion_time_min=15))
        .add_simulation(SimulationSpec(name="IV 1 mg", subject="Adult", compound="Perp-A", protocol="IV 1 mg", end_time_h=24))
        .build()
    )
    # both process selections present on the simulation compound
    sim_procs = {p.name for p in snapshot.simulations[0].compounds[0].processes}
    assert "CYP3A4-lit" in sim_procs
    assert "P-gp-Collett 2004" in sim_procs
    assert {p.type for p in snapshot.expression_profiles} == {"Enzyme", "Transporter"}


# --- CPF grouping maps multi-record processes ----------------------------------------------------


def _prov():
    return Provenance(source_type="in vitro")


def _rec(param_id, value, unit, process, parameter):
    return ParameterRecord(
        id=param_id, value=value, unit=unit, status=ParameterStatus.FIXED, provenance=_prov(),
        engine_binding=EngineBinding(building_block="Compound", process=process, parameter=parameter, data_source="lit"),
    )


def _base_records():
    return [
        ParameterRecord(id="phys.mw", value=822.9, unit="g/mol", status=ParameterStatus.FIXED, provenance=_prov()),
        ParameterRecord(id="phys.logp", value=2.5, unit="Log Units", status=ParameterStatus.FIXED, provenance=_prov()),
        ParameterRecord(id="bind.fu", value=0.1, status=ParameterStatus.FIXED, provenance=_prov()),
    ]


def _subjects_scenarios():
    subject = SubjectSpec(name="Adult", gender="MALE", age_years=35, seed=1)
    scen = Scenario(
        simulation=SimulationSpec(name="IV", subject="Adult", compound="Perp-A", protocol="IV", end_time_h=24),
        protocol=IntravenousProtocolSpec(name="IV", dose=Measured(value=1.0, unit="mg"), infusion_time_min=15),
    )
    return [subject], [scen]


def test_cpf_maps_mm_metabolism_from_two_records() -> None:
    cpf = CPF(compound="Perp-A", parameters=tuple(_base_records() + [
        _rec("elim.hepatic.CYP3A4.vmax", 6.5, "µmol/l/min", "MetabolizationSpecific_MM:CYP3A4", "Vmax"),
        _rec("elim.hepatic.CYP3A4.km", 195.1, "µmol/l", "MetabolizationSpecific_MM:CYP3A4", "Km"),
    ]))
    subjects, scenarios = _subjects_scenarios()
    snapshot, report = build_from_cpf(cpf, subjects, scenarios)
    assert "elim.hepatic.CYP3A4.vmax" in report.bindings_used
    assert "elim.hepatic.CYP3A4.km" in report.bindings_used
    assert report.unresolved == ()
    proc = snapshot.compounds[0].processes[0]
    assert proc.internal_name == "MetabolizationSpecific_MM"
    assert {p.name for p in proc.parameters} == {"Vmax", "Km"}


def test_cpf_maps_transporter_inhibition_induction() -> None:
    cpf = CPF(compound="Perp-A", parameters=tuple(_base_records() + [
        _rec("transp.Pgp.vmax", 2.87, "µmol/l/min", "ActiveTransportSpecific_MM:P-gp", "Vmax"),
        _rec("transp.Pgp.km", 55.0, "µmol/l", "ActiveTransportSpecific_MM:P-gp", "Km"),
        _rec("ddi.perp.CYP2C8.ki", 30.2, "µmol/l", "CompetitiveInhibition:CYP2C8", "Ki"),
        _rec("ddi.perp.CYP1A2.ec50", 0.34, "µmol/l", "Induction:CYP1A2", "EC50"),
        _rec("ddi.perp.CYP1A2.emax", 0.65, None, "Induction:CYP1A2", "Emax"),
    ]))
    subjects, scenarios = _subjects_scenarios()
    snapshot, report = build_from_cpf(cpf, subjects, scenarios)
    internal = {p.internal_name for p in snapshot.compounds[0].processes}
    assert {"ActiveTransportSpecific_MM", "CompetitiveInhibition", "Induction"} <= internal
    assert report.unresolved == ()


def test_cpf_reports_unsupported_process_as_unresolved() -> None:
    cpf = CPF(compound="Perp-A", parameters=tuple(_base_records() + [
        # MetabolizationLiverMicrosomes_MM is a real engine process but not yet built (special Vmax unit).
        _rec("elim.hepatic.CYP3A4.vmax_hlm", 850, "pmol/min/mg mic. protein", "MetabolizationLiverMicrosomes_MM:CYP3A4", "In vitro Vmax for liver microsomes"),
    ]))
    subjects, scenarios = _subjects_scenarios()
    _, report = build_from_cpf(cpf, subjects, scenarios)
    assert "elim.hepatic.CYP3A4.vmax_hlm" in report.unresolved


def test_cpf_incomplete_mm_is_unresolved_not_error() -> None:
    # Vmax without Km cannot form an MM process; it must be reported, not raise.
    cpf = CPF(compound="Perp-A", parameters=tuple(_base_records() + [
        _rec("elim.hepatic.CYP3A4.vmax", 6.5, "µmol/l/min", "MetabolizationSpecific_MM:CYP3A4", "Vmax"),
    ]))
    subjects, scenarios = _subjects_scenarios()
    _, report = build_from_cpf(cpf, subjects, scenarios)
    assert "elim.hepatic.CYP3A4.vmax" in report.unresolved
