"""Round-trip inputs: the published model's own simulations against the ones the pipeline regenerates from the CPF.

For every imported study the published model simulates, the pipeline builds its simulation from the imported CPF
exactly as a campaign would (MAP scenario → round build), and the pair is compared on PK-Sim at the same time points
(`services/engine-worker/golden/reference_compare.R`). Identical inputs must give identical plasma curves; any
difference is a defect in the importer or the builder, or a modelling choice the pipeline makes differently.
"""

from __future__ import annotations

import json
from typing import Any

from pbpk_domain.campaign.map import generate_map
from pbpk_domain.campaign.round_build import build_stage_snapshot
from pbpk_domain.campaign.split import QuestionOfInterest, StudyRecord, split_studies
from pbpk_domain.m15 import Rating
from pbpk_domain.reference.osp_import import ReferenceImport

ROUNDTRIP_STAGE = "RT"


def study_records(imported: ReferenceImport) -> list[StudyRecord]:
    fields = StudyRecord.model_fields
    return [StudyRecord.model_validate({k: v for k, v in s.items() if k in fields}) for s in imported.studies]


def roundtrip_inputs(imported: ReferenceImport) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """Our snapshot of every linked study, the (ours, published, offset) pairs, and the notes of the build."""
    studies = study_records(imported)
    sampling_end_h = {s["study_id"]: max(s["profile"]["times"]) / 60.0 if s["profile"]["time_unit"] == "min"
                      else max(s["profile"]["times"]) for s in imported.studies}
    map_doc = generate_map(
        compound=imported.compound, cpf=imported.cpf, studies=studies,
        split=split_studies(studies, QuestionOfInterest()), objective="round trip", context_of_use="round trip",
        food_effect_in_question=False, model_risk=Rating.MEDIUM, engine_image_digest="roundtrip",
        software_versions={}, sampling_end_h=sampling_end_h,
    )
    # One scenario per linked study, whichever stage the MAP gave it (special populations get none: build them too).
    by_study: dict[str, Any] = {}
    for scenario in map_doc.scenarios:
        by_study.setdefault(scenario.study_id, scenario)
    scenarios = [by_study[sid].model_copy(update={"stage": ROUNDTRIP_STAGE})
                 for sid in imported.simulation_of if sid in by_study]
    built = build_stage_snapshot(imported.cpf, scenarios, stage=ROUNDTRIP_STAGE, skip_unbuildable=True)
    ours = json.loads(built.snapshot.model_dump_json(by_alias=True, exclude_none=True))
    placed = set(built.simulations)
    pairs = [{"ours": sid, "published": imported.simulation_of[sid], "offset_min": imported.offset_min.get(sid, 0.0),
              "end_h": _sim_end_h(ours, sid)}
             for sid in imported.simulation_of if sid in placed]
    missing = [sid for sid in imported.simulation_of if sid not in by_study]
    notes = list(built.notes) + [f"{sid}: no MAP scenario (not simulated by the pipeline)" for sid in missing]
    return ours, pairs, notes


def _sim_end_h(snapshot: dict[str, Any], name: str) -> float:
    sim = next(s for s in snapshot["Simulations"] if s["Name"] == name)
    ends = [p["Value"] for block in sim.get("OutputSchema", []) for p in block["Parameters"] if p["Name"] == "End time"]
    return float(max(ends)) if ends else 24.0
