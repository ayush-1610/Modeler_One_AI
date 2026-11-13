"""_build_fit_request passes the profile's error type into the PI spec (contracts §8.2, D1a; plan 2026-11-12 L-c).

On today's fixture (an arithmetic SD) the spec bytes and their sha256 are unchanged; a profile whose SD is a geometric
factor (`sd_type`, written by modeler_project.profile_landing) gets `error_type` in its observed block, its SD unscaled.
No engine: the activity writes the spec next to the CPF and returns its hash.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from modeler_contracts.runs import RoundContext
from modeler_orchestrator.campaign_activities import build_round_snapshot
from pbpk_domain import spread
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
from pbpk_domain.cpf import CPF, FitPolicy, ParameterRecord, ParameterStatus, Provenance
from pbpk_domain.m15 import Rating

pytestmark = pytest.mark.req("T-13")
# the spec test_build_round_activity.py's fixture gave at 045ffc3, before the error type existed (1013 bytes)
TODAY_SPEC_SHA256 = "5ea1a0d14444d3421cd4296b79728d71e398eebc14e52bba3398bb5a4fe871b1"
PROFILE = {"times": [0.5, 1, 4], "values": [12.0, 20.0, 5.0], "time_unit": "h", "unit": "ng/ml", "sd": [1, 2, 0.5], "lloq": 0.1}


def _inputs(tmp_path: Path, profile: dict) -> tuple[str, str, str]:
    """The fixture of test_build_round_activity.py's fit tests: one IV study, phys.logp fitted in S1."""
    tmp_path.mkdir(parents=True, exist_ok=True)
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
    (tmp_path / "observed.json").write_text(json.dumps({"iv": {"auc": 100.0, "cmax": 20.0, "profile": profile}}),
                                            encoding="utf-8")
    return (tmp_path / "cpf.json").as_uri(), (tmp_path / "map.json").as_uri(), (tmp_path / "observed.json").as_uri()


def _spec(tmp_path: Path, profile: dict) -> tuple[bytes, str]:
    cpf_uri, map_uri, observed_uri = _inputs(tmp_path, profile)
    build = build_round_snapshot(RoundContext(campaign_id="camp1", tenant_id="t1", stage="S1", round_index=1, cpf_uri=cpf_uri,
                                              cpf_sha256="a" * 64, pending_action="fit phys.logp", map_uri=map_uri,
                                              observed_uri=observed_uri))
    assert build.fit_request is not None
    return Path(build.fit_request.base_spec_uri.removeprefix("file://")).read_bytes(), build.fit_request.base_spec_sha256


def test_todays_fixture_gives_todays_spec_bytes(tmp_path):
    data, sha = _spec(tmp_path, PROFILE)
    assert sha == hashlib.sha256(data).hexdigest() == TODAY_SPEC_SHA256 and len(data) == 1013
    assert b"error_type" not in data
    # an arithmetic SD labelled as such is still today's spec
    data, sha = _spec(tmp_path / "labelled", {**PROFILE, "sd_type": spread.ARITHMETIC_SD})
    assert sha == TODAY_SPEC_SHA256


def test_a_geometric_sd_reaches_the_pi_spec_with_its_error_type(tmp_path):
    data, sha = _spec(tmp_path, {**PROFILE, "sd": [1.4, 1.5, 1.9], "sd_type": spread.GEOMETRIC_SD})
    observed = json.loads(data)["output_mappings"][0]["observed"]
    assert observed["error_type"] == "GeometricStdDev" and observed["sd"] == [1.4, 1.5, 1.9]
    assert sha == hashlib.sha256(data).hexdigest() != TODAY_SPEC_SHA256
    assert {k: v for k, v in observed.items() if k not in ("error_type", "sd")} == \
        {k: v for k, v in json.loads(_spec(tmp_path / "today", PROFILE)[0])["output_mappings"][0]["observed"].items()
         if k != "sd"}
