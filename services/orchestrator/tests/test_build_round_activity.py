"""build_round_snapshot regenerates the stage snapshot from a local CPF and MAP (T-13 <-> T-16 wiring).

No Docker or engine needed: the activity reads a `file://` CPF and MAP, writes the built snapshot next to the
CPF, and returns its URI and content hash. When no scenario trains the stage it falls back to echoing the CPF.
"""

from __future__ import annotations

import json
from pathlib import Path

from modeler_contracts.runs import RoundContext
from modeler_orchestrator.campaign_activities import build_round_snapshot
from pbpk_domain.campaign.map import generate_map
from pbpk_domain.campaign.split import (
    Demographics,
    FoodState,
    FormulationKind,
    QuestionOfInterest,
    Route,
    Sex,
    StudyRecord,
    split_studies,
)
from pbpk_domain.cpf import CPF, EngineBinding, ParameterRecord, ParameterStatus, Provenance
from pbpk_domain.m15 import Rating
from pbpk_domain.snapshot.models import Snapshot


def _cpf() -> CPF:
    prov = Provenance(source_type="measured", reference="Example 2020")

    def rec(pid, value, unit=None, binding=None):
        return ParameterRecord(id=pid, value=value, unit=unit, status=ParameterStatus.FIXED,
                               provenance=prov, engine_binding=binding)

    return CPF(compound="Example-A", parameters=(
        rec("phys.mw", 408.5, "g/mol"),
        rec("phys.logp", 2.6, "Log Units"),
        rec("bind.fu", 0.02),
        rec("phys.solubility.ref", 0.1, "mg/ml"),
        rec("elim.hepatic.CYP3A4.clspec", 0.8, "l/µmol/min",
            EngineBinding(building_block="Compound", process="MetabolizationSpecific_FirstOrder:CYP3A4",
                          parameter="CLspec/[Enzyme]", data_source="Optimized")),
    ))


def _write_inputs(tmp_path: Path) -> tuple[CPF, str, str]:
    cpf = _cpf()
    adult = Demographics(sex=Sex.MALE, age_years=35.0)
    studies = [
        StudyRecord(study_id="iv", n=12, design="SD", route=Route.IV_BOLUS, dose_mg=5.0, infusion_time_min=5.0,
                    formulation=FormulationKind.SOLUTION, food_state=FoodState.FASTED, n_timepoints=15, demographics=adult),
        StudyRecord(study_id="po", n=20, design="SD", route=Route.ORAL, dose_mg=10.0,
                    formulation=FormulationKind.SOLUTION, food_state=FoodState.FASTED, n_timepoints=15, demographics=adult),
    ]
    split = split_studies(studies, QuestionOfInterest())
    m = generate_map(
        compound="Example-A", cpf=cpf, studies=studies, split=split, objective="predict",
        context_of_use="MIDD", food_effect_in_question=False, model_risk=Rating.MEDIUM,
        engine_image_digest="sha256:abcd", software_versions={"ospsuite": "12.4.4"},
    )
    cpf_path = tmp_path / "cpf.json"
    cpf_path.write_text(cpf.model_dump_json(), encoding="utf-8")
    map_path = tmp_path / "map.json"
    map_path.write_text(m.model_dump_json(), encoding="utf-8")
    return cpf, cpf_path.as_uri(), map_path.as_uri()


def _ctx(cpf_uri: str, map_uri: str, stage: str) -> RoundContext:
    return RoundContext(
        campaign_id="camp1", tenant_id="t1", stage=stage, round_index=1,
        cpf_uri=cpf_uri, cpf_sha256="a" * 64, pending_action=None, map_uri=map_uri, map_sha256="b" * 64,
    )


def test_builds_snapshot_for_a_training_stage(tmp_path: Path) -> None:
    _, cpf_uri, map_uri = _write_inputs(tmp_path)
    build = build_round_snapshot(_ctx(cpf_uri, map_uri, "S1"))

    # a new snapshot file was written next to the CPF, not the CPF echoed back
    assert build.snapshot_uri != cpf_uri
    out = tmp_path / "snapshots" / "camp1-S1-r1.json"
    assert build.snapshot_uri == out.as_uri()
    snapshot = Snapshot.load(out)
    assert build.snapshot_sha256 == snapshot.sha256()
    # S1 trains from the IV study
    assert [s.name for s in snapshot.simulations] == ["iv"]
    assert snapshot.compounds[0].name == "Example-A"


def test_stage_without_scenarios_echoes_cpf(tmp_path: Path) -> None:
    _, cpf_uri, map_uri = _write_inputs(tmp_path)
    build = build_round_snapshot(_ctx(cpf_uri, map_uri, "S4"))  # validation stage: no training scenarios
    assert build.snapshot_uri == cpf_uri
    assert build.snapshot_sha256 == "a" * 64


def test_missing_map_echoes_cpf(tmp_path: Path) -> None:
    _, cpf_uri, _ = _write_inputs(tmp_path)
    ctx = _ctx(cpf_uri, "", "S1")  # no MAP uri
    build = build_round_snapshot(ctx)
    assert build.snapshot_uri == cpf_uri


def test_snapshot_is_valid_pksim_json(tmp_path: Path) -> None:
    _, cpf_uri, map_uri = _write_inputs(tmp_path)
    build = build_round_snapshot(_ctx(cpf_uri, map_uri, "S2"))
    doc = json.loads(Path(build.snapshot_uri.removeprefix("file://")).read_text())
    assert doc["Version"] == 80
    assert doc["Simulations"][0]["Name"] == "po"
