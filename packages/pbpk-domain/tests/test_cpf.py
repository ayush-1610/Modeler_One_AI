from __future__ import annotations

from pathlib import Path

import pytest

from pbpk_domain.catalog import Catalog
from pbpk_domain.cpf import (
    CPF,
    EngineBinding,
    FitPolicy,
    ParameterRecord,
    ParameterStatus,
    Plausibility,
    Provenance,
    Scenario,
    bind,
    build_from_cpf,
    check_completeness,
)
from pbpk_domain.cpf.binding import BindingError
from pbpk_domain.snapshot.builder import (
    DissolvedFormulationSpec,
    IntravenousProtocolSpec,
    Measured,
    OralProtocolSpec,
    SimulationSpec,
    SnapshotBuilder,
    SubjectSpec,
)

CATALOG = Catalog.load(Path(__file__).parent / "fixtures" / "catalog_sample.json")


def prov(source: str = "measured", ref: str = "Example 2020") -> Provenance:
    return Provenance(source_type=source, reference=ref)


def rec(param_id: str, value, unit=None, status=ParameterStatus.FIXED, binding=None, provenance=None, **kw) -> ParameterRecord:
    return ParameterRecord(
        id=param_id, value=value, unit=unit, status=status,
        engine_binding=binding, provenance=provenance or prov(), **kw
    )


def minimal_cpf(**extra_params) -> CPF:
    params = [
        rec("phys.mw", 408.5, "g/mol"),
        rec("phys.logp", 2.6, "Log Units"),
        rec("bind.fu", 0.02),
        rec("phys.solubility.ref", 0.1, "mg/ml"),
        rec("phys.pka.base.0", 6.4),
        rec("elim.hepatic.CYP3A4.clspec", 0.8, "l/µmol/min",
            binding=EngineBinding(building_block="Compound", process="MetabolizationSpecific_FirstOrder:CYP3A4",
                                  parameter="CLspec/[Enzyme]", data_source="Optimized")),
    ]
    params.extend(extra_params.get("extra", []))
    return CPF(compound="Example-A", parameters=tuple(params))


# --- models --------------------------------------------------------------------------------------


def test_missing_must_not_have_value() -> None:
    with pytest.raises(ValueError, match="MISSING"):
        ParameterRecord(id="x", value=1.0, status=ParameterStatus.MISSING)


def test_non_missing_needs_value() -> None:
    with pytest.raises(ValueError, match="must carry a value"):
        ParameterRecord(id="x", status=ParameterStatus.FIXED)


def test_fit_policy_within_plausibility() -> None:
    with pytest.raises(ValueError, match="within the plausibility range"):
        ParameterRecord(
            id="x", value=1.0, status=ParameterStatus.FITTED,
            fit_policy=FitPolicy(stage=("S1",), lower=1e-3, upper=1e3, scale="log"),
            plausibility=Plausibility(lower=1e-2, upper=1e2),
        )


def test_cpf_versioning_and_replace() -> None:
    cpf = minimal_cpf()
    assert cpf.version == 1
    updated = cpf.replace(rec("bind.fu", 0.05), note="refit")
    assert updated.version == 2
    assert updated.require("bind.fu").numeric_value == 0.05
    assert cpf.require("bind.fu").numeric_value == 0.02  # original unchanged (immutable)


def test_duplicate_ids_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate parameter ids"):
        CPF(compound="X", parameters=(rec("phys.mw", 1.0, "g/mol"), rec("phys.mw", 2.0, "g/mol")))


def test_categorical_value_and_prefix() -> None:
    cpf = minimal_cpf(extra=[rec("bind.partner", "Albumin")])
    assert cpf.require("bind.partner").value == "Albumin"
    assert {p.id for p in cpf.with_prefix("phys")} >= {"phys.mw", "phys.logp", "phys.solubility.ref", "phys.pka.base.0"}


def test_json_schema_exports() -> None:
    schema = CPF.json_schema()
    assert schema["title"] == "CPF"
    assert "parameters" in schema["properties"]


# --- completeness (S0) ---------------------------------------------------------------------------


def test_completeness_ready() -> None:
    report = check_completeness(minimal_cpf())
    assert report.ready
    assert report.missing == ()


def test_completeness_missing_items() -> None:
    cpf = CPF(compound="X", parameters=(rec("phys.mw", 408.5, "g/mol"),))
    report = check_completeness(cpf)
    assert not report.ready
    assert "phys.logp" in report.missing_ids
    assert "bind.fu" in report.missing_ids
    assert "phys.solubility.ref" in report.missing_ids
    assert "phys.pka" in report.missing_ids
    assert "elim" in report.missing_ids


def test_completeness_neutral_declaration_satisfies_pka() -> None:
    params = [
        rec("phys.mw", 408.5, "g/mol"), rec("phys.logp", 2.6, "Log Units"),
        rec("bind.fu", 0.02), rec("phys.solubility.ref", 0.1, "mg/ml"),
        rec("phys.pka.neutral", 1.0), rec("elim.hepatic.total_cl", 5.0, "ml/min/kg"),
    ]
    assert check_completeness(CPF(compound="X", parameters=tuple(params))).ready


def test_completeness_requires_provenance() -> None:
    bad = ParameterRecord(id="phys.mw", value=1.0, unit="g/mol", status=ParameterStatus.FIXED)  # no provenance
    others = [p for p in minimal_cpf().parameters if p.id != "phys.mw"]
    report = check_completeness(CPF(compound="X", parameters=(bad, *others)))
    assert "phys.mw" in report.missing_ids


# --- binding (against the catalog) ---------------------------------------------------------------


def test_bind_success() -> None:
    plan = bind(minimal_cpf(), CATALOG)
    fo = plan.for_process("MetabolizationSpecific_FirstOrder", "CYP3A4")
    assert len(fo) == 1
    assert fo[0].catalog_verified
    # phys.* records have no engine binding here -> unbound
    assert "phys.mw" in plan.unbound


def test_bind_unknown_process_raises() -> None:
    cpf = minimal_cpf(extra=[
        rec("elim.hepatic.CYP1A2.clspec", 0.5, "l/µmol/min",
            binding=EngineBinding(building_block="Compound", process="MetabolizationSpecific_Nonsense:CYP1A2", parameter="CLspec/[Enzyme]")),
    ])
    with pytest.raises(BindingError) as exc:
        bind(cpf, CATALOG)
    assert exc.value.code == "NO_ENGINE_BINDING"
    assert "MetabolizationSpecific_Nonsense" in str(exc.value)


def test_bind_unknown_parameter_raises() -> None:
    cpf = minimal_cpf(extra=[
        rec("elim.x.clspec", 0.5, "l/µmol/min",
            binding=EngineBinding(building_block="Compound", process="MetabolizationSpecific_FirstOrder:X", parameter="NoSuchParam")),
    ])
    with pytest.raises(BindingError, match="no parameter"):
        bind(cpf, CATALOG)


def test_bind_wrong_unit_raises() -> None:
    cpf = minimal_cpf(extra=[
        rec("elim.y.clspec", 0.5, "mg/ml",  # wrong unit for CLspec/[Enzyme]
            binding=EngineBinding(building_block="Compound", process="MetabolizationSpecific_FirstOrder:Y", parameter="CLspec/[Enzyme]")),
    ])
    with pytest.raises(BindingError, match="does not match the engine unit"):
        bind(cpf, CATALOG)


# --- build (regenerate a snapshot) ---------------------------------------------------------------


def _subjects_and_scenarios():
    subject = SubjectSpec(name="Adult", gender="MALE", age_years=35, seed=1)
    iv = Scenario(
        simulation=SimulationSpec(name="IV 1 mg", subject="Adult", compound="Example-A", protocol="IV 1 mg", end_time_h=24),
        protocol=IntravenousProtocolSpec(name="IV 1 mg", dose=Measured(value=1.0, unit="mg"), infusion_time_min=15),
    )
    po = Scenario(
        simulation=SimulationSpec(name="PO 10 mg", subject="Adult", compound="Example-A", protocol="PO 10 mg",
                                  formulation="Dissolved", end_time_h=24),
        protocol=OralProtocolSpec(name="PO 10 mg", dose=Measured(value=10.0, unit="mg")),
        formulation=DissolvedFormulationSpec(name="Dissolved"),
    )
    return [subject], [iv, po]


def test_build_from_cpf_produces_valid_snapshot() -> None:
    cpf = minimal_cpf(extra=[
        rec("elim.renal.gfr_fraction", 1.0,
            binding=EngineBinding(building_block="Compound", process="GlomerularFiltration", parameter="GFR fraction", data_source="assumed")),
        rec("phys.halogens.F", 2.0),
    ])
    subjects, scenarios = _subjects_and_scenarios()
    snapshot, report = build_from_cpf(cpf, subjects, scenarios)
    assert len(snapshot.compounds) == 1
    assert len(snapshot.simulations) == 2
    assert report.compound == "Example-A"
    assert "elim.hepatic.CYP3A4.clspec" in report.bindings_used
    assert "elim.renal.gfr_fraction" in report.bindings_used


def test_build_reports_unresolved_for_unsupported_process() -> None:
    cpf = minimal_cpf(extra=[
        rec("elim.hepatic.CYP3A4.km", 3.0, "µmol/l",
            binding=EngineBinding(building_block="Compound", process="MetabolizationLiverMicrosomes_MM:CYP3A4", parameter="Km")),
        rec("transp.OATP1B1.clspec", 0.2, "l/µmol/min",
            binding=EngineBinding(building_block="Compound", process="ActiveTransportSpecific_MM:OATP1B1", parameter="Vmax")),
    ])
    subjects, scenarios = _subjects_and_scenarios()
    _, report = build_from_cpf(cpf, subjects, scenarios)
    assert "elim.hepatic.CYP3A4.km" in report.unresolved
    assert "transp.OATP1B1.clspec" in report.unresolved


def test_build_is_deterministic() -> None:
    cpf = minimal_cpf(extra=[
        rec("elim.renal.gfr_fraction", 1.0,
            binding=EngineBinding(building_block="Compound", process="GlomerularFiltration", parameter="GFR fraction", data_source="assumed")),
    ])
    subjects, scenarios = _subjects_and_scenarios()
    snap1, _ = build_from_cpf(cpf, subjects, scenarios)
    snap2, _ = build_from_cpf(cpf, subjects, scenarios)
    assert snap1.sha256() == snap2.sha256()


def test_from_cpf_classmethod_matches_function() -> None:
    cpf = minimal_cpf()
    subjects, scenarios = _subjects_and_scenarios()
    snap_cls, _ = SnapshotBuilder.from_cpf(cpf, subjects, scenarios)
    snap_fn, _ = build_from_cpf(cpf, subjects, scenarios)
    assert snap_cls.sha256() == snap_fn.sha256()


def test_build_missing_required_parameter_raises() -> None:
    cpf = CPF(compound="X", parameters=(rec("phys.logp", 2.0, "Log Units"),))  # no phys.mw
    subjects, scenarios = _subjects_and_scenarios()
    with pytest.raises(ValueError, match="missing required parameter"):
        build_from_cpf(cpf, subjects, scenarios)
