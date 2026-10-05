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
from pbpk_domain.cpf import CPF, EngineBinding, FitPolicy, ParameterRecord, ParameterStatus, Provenance
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
    # the build hash is of the exact file bytes the engine downloads (the integrity check compares that), not
    # the canonical content hash — so a snapshot round-trips through EngineRunner's sha256 verification
    import hashlib
    assert build.snapshot_sha256 == hashlib.sha256(out.read_bytes()).hexdigest()
    # S1 trains from the IV study
    assert [s.name for s in snapshot.simulations] == ["iv"]
    assert snapshot.compounds[0].name == "Example-A"


def test_stage_without_scenarios_echoes_cpf(tmp_path: Path) -> None:
    _, cpf_uri, map_uri = _write_inputs(tmp_path)
    build = build_round_snapshot(_ctx(cpf_uri, map_uri, "S3"))  # no fed / formulation study: nothing trains S3
    assert build.snapshot_uri == cpf_uri
    assert build.snapshot_sha256 == "a" * 64
    assert build.notes and "S3" in build.notes[0]  # the reason travels with the build, not only the log


def test_internal_validation_rebuilds_every_trained_study(tmp_path: Path) -> None:
    _, cpf_uri, map_uri = _write_inputs(tmp_path)
    build = build_round_snapshot(_ctx(cpf_uri, map_uri, "S4"))
    snapshot = Snapshot.load(Path(build.snapshot_uri.removeprefix("file://")))
    assert sorted(s.name for s in snapshot.simulations) == ["iv", "po"]  # S1's and S2's studies, re-simulated


def test_validation_stage_simulates_what_it_can_and_names_the_rest(tmp_path: Path) -> None:
    """A modified-release study the builder cannot place yet must not stop the other external studies being judged."""
    cpf = _cpf()
    adult = Demographics(sex=Sex.MALE, age_years=35.0)
    base = dict(n=12, design="SD", route=Route.ORAL, dose_mg=10.0, food_state=FoodState.FASTED, n_timepoints=15,
                demographics=adult)
    studies = [
        StudyRecord(study_id="iv", route=Route.IV_BOLUS, infusion_time_min=5.0, **{k: v for k, v in base.items() if k != "route"}),
        StudyRecord(study_id="po_a", formulation=FormulationKind.SOLUTION, **base),
        StudyRecord(study_id="po_b", formulation=FormulationKind.SOLUTION, **{**base, "dose_mg": 10.0, "n": 6}),
        StudyRecord(study_id="tab", formulation=FormulationKind.MR, **{**base, "n": 6}),  # PO-MR: always external
    ]
    split = split_studies(studies, QuestionOfInterest())
    m = generate_map(
        compound="Example-A", cpf=cpf, studies=studies, split=split, objective="predict",
        context_of_use="MIDD", food_effect_in_question=False, model_risk=Rating.MEDIUM,
        engine_image_digest="sha256:abcd", software_versions={"ospsuite": "12.4.4"},
    )
    (tmp_path / "cpf.json").write_text(cpf.model_dump_json(), encoding="utf-8")
    (tmp_path / "map.json").write_text(m.model_dump_json(), encoding="utf-8")
    s5 = {sc.study_id for sc in m.scenarios if sc.stage == "S5"}
    assert "tab" in s5 and "po_b" in s5
    build = build_round_snapshot(_ctx((tmp_path / "cpf.json").as_uri(), (tmp_path / "map.json").as_uri(), "S5"))
    snapshot = Snapshot.load(Path(build.snapshot_uri.removeprefix("file://")))
    assert "tab" not in {s.name for s in snapshot.simulations} and "po_b" in {s.name for s in snapshot.simulations}
    assert any(n.startswith("NOT SIMULATED") and "'tab'" in n for n in build.notes)


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


# --- fit request (fit-apply loop step 2) ---------------------------------------------------------


def _fittable_inputs(tmp_path: Path, *, with_observed: bool) -> tuple[str, str, str]:
    prov = Provenance(source_type="measured", reference="x")
    cpf = CPF(compound="Example-A", parameters=(
        ParameterRecord(id="phys.mw", value=408.5, unit="g/mol", status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="phys.logp", value=2.6, unit="Log Units", status=ParameterStatus.PREDICTED, provenance=prov,
                        fit_policy=FitPolicy(stage=("S1",), lower=1.0, upper=4.0)),
        ParameterRecord(id="bind.fu", value=0.02, status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="phys.solubility.ref", value=0.1, unit="mg/ml", status=ParameterStatus.FIXED, provenance=prov),
    ))
    adult = Demographics(sex=Sex.MALE, age_years=35.0)
    studies = [StudyRecord(study_id="iv", n=12, design="SD", route=Route.IV_BOLUS, dose_mg=5.0, infusion_time_min=5.0,
                           formulation=FormulationKind.SOLUTION, food_state=FoodState.FASTED, n_timepoints=15, demographics=adult)]
    m = generate_map(compound="Example-A", cpf=cpf, studies=studies, split=split_studies(studies, QuestionOfInterest()),
                     objective="o", context_of_use="c", food_effect_in_question=False, model_risk=Rating.HIGH,
                     engine_image_digest="sha256:abcd", software_versions={"ospsuite": "12.4.4"})
    (tmp_path / "cpf.json").write_text(cpf.model_dump_json(), encoding="utf-8")
    (tmp_path / "map.json").write_text(m.model_dump_json(), encoding="utf-8")
    observed_uri = ""
    if with_observed:
        obs = {"iv": {"auc": 100.0, "cmax": 20.0,
                      "profile": {"times": [0.5, 1, 4], "values": [12.0, 20.0, 5.0], "time_unit": "h", "unit": "ng/ml",
                                  "sd": [1, 2, 0.5], "lloq": 0.1}}}
        (tmp_path / "observed.json").write_text(json.dumps(obs), encoding="utf-8")
        observed_uri = (tmp_path / "observed.json").as_uri()
    return (tmp_path / "cpf.json").as_uri(), (tmp_path / "map.json").as_uri(), observed_uri


def _fit_ctx(cpf_uri, map_uri, observed_uri, action) -> RoundContext:
    return RoundContext(campaign_id="camp1", tenant_id="t1", stage="S1", round_index=1, cpf_uri=cpf_uri,
                        cpf_sha256="a" * 64, pending_action=action, map_uri=map_uri, observed_uri=observed_uri)


def test_fit_action_emits_a_fit_request(tmp_path: Path) -> None:
    cpf_uri, map_uri, observed_uri = _fittable_inputs(tmp_path, with_observed=True)
    build = build_round_snapshot(_fit_ctx(cpf_uri, map_uri, observed_uri, "fit phys.logp"))
    assert build.needs_fit is True and build.fit_request is not None
    fr = build.fit_request
    assert [p.name for p in fr.parameters] == ["phys.logp"]
    assert fr.parameters[0].lower == 1.0 and fr.parameters[0].upper == 4.0
    assert fr.base_spec_uri.endswith("-pi_spec.json")
    assert fr.model_inputs == []  # pkml filled by the convert step
    # the persisted PI spec has the resolved PK-Sim path and the observed profile
    spec = json.loads(Path(fr.base_spec_uri.removeprefix("file://")).read_text())
    assert spec["parameters"][0]["paths"][0]["path"] == "Example-A|Lipophilicity"
    assert spec["output_mappings"][0]["observed"]["lloq"] == 0.1
    # the spec names the model exactly as the engine exports it ("snapshot-<simulation>.pkml", after the job's
    # snapshot.json input) — a name the engine does not produce means the fit can never start (found on PK-Sim)
    from modeler_orchestrator.campaign_activities import ROUND_SNAPSHOT_INPUT
    assert ROUND_SNAPSHOT_INPUT == "snapshot.json"
    assert [s["pkml"] for s in spec["simulations"]] == ["snapshot-iv.pkml"]
    # a mass-unit profile is declared as a mass concentration; a molar one (the canonical form) as molar
    assert spec["output_mappings"][0]["observed"]["dimension"] == "Concentration (mass)"


def test_fit_on_a_molar_profile_declares_the_molar_dimension(tmp_path: Path) -> None:
    """ospsuite reads the unit against the declared dimension; µmol/l declared as mass is wrong or fails."""
    cpf_uri, map_uri, observed_uri = _fittable_inputs(tmp_path, with_observed=True)
    path = Path(observed_uri.removeprefix("file://"))
    doc = json.loads(path.read_text())
    doc["iv"]["profile"].update(unit="µmol/l", time_unit="min")
    path.write_text(json.dumps(doc), encoding="utf-8")
    build = build_round_snapshot(_fit_ctx(cpf_uri, map_uri, observed_uri, "fit phys.logp"))
    spec = json.loads(Path(build.fit_request.base_spec_uri.removeprefix("file://")).read_text())
    assert spec["output_mappings"][0]["observed"]["dimension"] == "Concentration (molar)"


def test_fit_action_without_observed_profile_has_no_fit_request(tmp_path: Path) -> None:
    cpf_uri, map_uri, _ = _fittable_inputs(tmp_path, with_observed=False)
    build = build_round_snapshot(_fit_ctx(cpf_uri, map_uri, "", "fit phys.logp"))
    assert build.needs_fit is True and build.fit_request is None  # nothing to fit against -> round simulates


def test_fit_request_uses_strategist_bounds_override(tmp_path: Path) -> None:
    cpf_uri, map_uri, observed_uri = _fittable_inputs(tmp_path, with_observed=True)
    ctx = RoundContext(campaign_id="camp1", tenant_id="t1", stage="S1", round_index=1, cpf_uri=cpf_uri,
                       cpf_sha256="a" * 64, pending_action="fit phys.logp", map_uri=map_uri, observed_uri=observed_uri,
                       pending_bounds_override={"phys.logp": [0.5, 3.0]})  # strategist's bounds, tighter than the policy's 1..4
    build = build_round_snapshot(ctx)
    assert build.fit_request is not None
    assert build.fit_request.parameters[0].lower == 0.5 and build.fit_request.parameters[0].upper == 3.0
    spec = json.loads(Path(build.fit_request.base_spec_uri.removeprefix("file://")).read_text())
    p = spec["parameters"][0]
    assert p["min"] == 0.5 and p["max"] == 3.0
    assert p["start"] == 2.6  # within the override bounds -> unchanged


def test_a_fit_of_a_default_alternative_leaves_out_studies_selecting_another(tmp_path: Path) -> None:
    """A study whose simulation selects another solubility alternative (OSP Itraconazole capsule fed) does not use the
    default's value; fitting it there would overwrite the alternative, so it is left out of that fit only."""
    from pbpk_domain.campaign.round_build import scenarios_for_stage

    prov = Provenance(source_type="measured", reference="x")
    policy = FitPolicy(stage=("S1", "S2"), lower=0.001, upper=1.0)
    cpf = CPF(compound="Example-A", parameters=(
        ParameterRecord(id="phys.mw", value=408.5, unit="g/mol", status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="phys.logp", value=2.6, unit="Log Units", status=ParameterStatus.PREDICTED, provenance=prov,
                        fit_policy=FitPolicy(stage=("S1", "S2"), lower=1.0, upper=4.0)),
        ParameterRecord(id="bind.fu", value=0.02, status=ParameterStatus.FIXED, provenance=prov),
        ParameterRecord(id="phys.solubility.ref", value=0.1, unit="mg/ml", status=ParameterStatus.PREDICTED,
                        provenance=prov, fit_policy=policy),
        ParameterRecord(id="phys.solubility.ref@Solution FaSSIF", value=0.05, unit="mg/ml", status=ParameterStatus.FIXED,
                        provenance=prov),
        ParameterRecord(id="alt.select", status=ParameterStatus.FIXED, provenance=prov, value=json.dumps(
            [{"group": "Solubility", "formulation": None, "food": "fasted", "alternative": "Solution FaSSIF"}])),
    ))
    adult = Demographics(sex=Sex.MALE, age_years=35.0)
    studies = [StudyRecord(study_id="po", n=20, design="SD", route=Route.ORAL, dose_mg=10.0,
                           formulation=FormulationKind.SOLUTION, food_state=FoodState.FASTED, n_timepoints=15,
                           demographics=adult)]
    m = generate_map(compound="Example-A", cpf=cpf, studies=studies, split=split_studies(studies, QuestionOfInterest()),
                     objective="o", context_of_use="c", food_effect_in_question=False, model_risk=Rating.HIGH,
                     engine_image_digest="sha256:abcd", software_versions={"ospsuite": "12.4.4"})
    stage = next(s.stage for s in m.scenarios if s.study_id == "po")
    assert [s.study_id for s in scenarios_for_stage(m.scenarios, stage)] == ["po"]
    (tmp_path / "cpf.json").write_text(cpf.model_dump_json(), encoding="utf-8")
    (tmp_path / "map.json").write_text(m.model_dump_json(), encoding="utf-8")
    obs = {"po": {"auc": 100.0, "cmax": 20.0, "profile": {"times": [0.5, 1, 4], "values": [12.0, 20.0, 5.0],
                                                          "time_unit": "h", "unit": "ng/ml"}}}
    (tmp_path / "observed.json").write_text(json.dumps(obs), encoding="utf-8")

    def ctx(action):
        return RoundContext(campaign_id="camp1", tenant_id="t1", stage=stage, round_index=1,
                            cpf_uri=(tmp_path / "cpf.json").as_uri(), cpf_sha256="a" * 64, pending_action=action,
                            map_uri=(tmp_path / "map.json").as_uri(), observed_uri=(tmp_path / "observed.json").as_uri())

    assert build_round_snapshot(ctx("fit phys.solubility.ref")).fit_request is None  # its only study selects FaSSIF
    assert build_round_snapshot(ctx("fit phys.logp")).fit_request is not None
    # and the regenerated simulation selects the alternative
    doc = json.loads(Path(build_round_snapshot(ctx(None)).snapshot_uri.removeprefix("file://")).read_text())
    selected = {a["GroupName"]: a["AlternativeName"] for a in doc["Simulations"][0]["Compounds"][0]["Alternatives"]}
    assert selected["COMPOUND_SOLUBILITY"] == "Solution FaSSIF"
