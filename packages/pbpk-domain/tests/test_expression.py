"""Every protein a process acts through gets its harvested expression profile (MS-01 §S0, plan item 1.2)."""

from __future__ import annotations

from pbpk_domain.cpf import CPF, EngineBinding, ParameterRecord, ParameterStatus, Provenance
from pbpk_domain.cpf.build import build_from_cpf, missing_expression_profiles
from pbpk_domain.expression import expression_library, library_expression
from pbpk_domain.snapshot.builder import IntravenousProtocolSpec, Measured, SimulationSpec, SubjectSpec

PROV = Provenance(source_type="measured", reference="x")


def _cpf(enzyme: str) -> CPF:
    def rec(pid, value, unit=None, binding=None):
        return ParameterRecord(id=pid, value=value, unit=unit, status=ParameterStatus.FIXED, provenance=PROV,
                               engine_binding=binding)
    return CPF(compound="Drug", parameters=(
        rec("phys.mw", 408.9, "g/mol"), rec("phys.logp", 2.4, "Log Units"), rec("bind.fu", 0.09),
        rec(f"elim.hepatic.{enzyme}.clspec", 0.4, "l/µmol/min",
            EngineBinding(building_block="Compound", process=f"MetabolizationSpecific_FirstOrder:{enzyme}",
                          parameter="CLspec/[Enzyme]", data_source="Optimized")),
    ))


def _build(cpf: CPF):
    from pbpk_domain.cpf.build import Scenario

    subject = SubjectSpec(name="adult", gender="MALE", age_years=30, seed=1)
    protocol = IntravenousProtocolSpec(name="iv", dose=Measured(value=10, unit="mg"), infusion_time_min=5)
    sim = SimulationSpec(name="iv", subject="adult", compound="Drug", protocol="iv", end_time_h=24)
    return build_from_cpf(cpf, [subject], [Scenario(simulation=sim, protocol=protocol)])


def test_library_is_harvested_verbatim_from_the_osp_models():
    library = expression_library()
    assert {"CYP3A4", "UGT1A9", "UGT2B7", "P-gp", "OATP1B1"} <= set(library)
    ugt1a9 = library["UGT1A9"]
    assert ugt1a9["source"] == {"model": "Dapagliflozin", "category": "Healthy"}
    kidney = [p for p in ugt1a9["profile"]["Parameters"] if p["Path"] == "Organism|Kidney|Intracellular|UGT1A9|Relative expression"]
    assert kidney and kidney[0]["Value"] == 1.0  # the per-organ table PK-Sim needs, not an empty profile


def test_enzyme_process_gets_its_profile_on_every_subject():
    snapshot, report = _build(_cpf("UGT1A9"))
    assert report.expression_profiles == ("UGT1A9",) and report.missing_expression == ()
    assert snapshot.individuals[0].expression_profiles == ["UGT1A9|Human|Healthy"]
    profile = next(p for p in snapshot.expression_profiles if p.molecule == "UGT1A9")
    assert profile.category == "Healthy"
    assert sum(1 for p in profile.parameters if (p.path or "").endswith("Relative expression")) >= 10


def test_transporter_profile_keeps_its_transport_directions_and_type():
    spec = library_expression("OATP1B1")
    dumped = spec.to_profile().model_dump(by_alias=True, exclude_none=True)
    assert dumped["TransportType"] == "Influx" and dumped["Expression"]  # influx, not a defaulted efflux


def test_unharvested_protein_is_reported_and_blocks_s0():
    cpf = _cpf("CYP2C99")  # no reference model carries it
    assert missing_expression_profiles(cpf) == ("CYP2C99",)
    _snapshot, report = _build(cpf)
    assert report.missing_expression == ("CYP2C99",)


def test_reference_concentration_override_replaces_the_harvested_value():
    spec = library_expression("CYP3A4").model_copy(update={"reference_concentration": Measured(value=2.0, unit="µmol/l")})
    params = spec.to_profile().parameters
    ref = [p for p in params if p.path == "CYP3A4|Reference concentration"]
    assert len(ref) == 1 and ref[0].value == 2.0
