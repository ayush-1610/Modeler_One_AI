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
from pbpk_domain.reference.osp_import import ReferenceImport, SystemImport

ROUNDTRIP_STAGE = "RT"


def study_records(imported: ReferenceImport) -> list[StudyRecord]:
    fields = StudyRecord.model_fields
    return [StudyRecord.model_validate({k: v for k, v in s.items() if k in fields}) for s in imported.studies]


def study_snapshot(imported: ReferenceImport, *, linked_only: bool) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    """One snapshot simulating each study once, as a campaign builds it (MAP scenario -> round build): every study
    with a MAP scenario, or only those the published model links to a simulation. Returns the snapshot, each placed
    study's MAP assignment (INTERNAL / EXTERNAL), and the build notes (studies not simulated, and why)."""
    studies = study_records(imported)
    sampling_end_h = {s["study_id"]: max(s["profile"]["times"]) / 60.0 if s["profile"]["time_unit"] == "min"
                      else max(s["profile"]["times"]) for s in imported.studies}
    map_doc = generate_map(
        compound=imported.compound, cpf=imported.cpf, studies=studies,
        split=split_studies(studies, QuestionOfInterest()), objective="round trip", context_of_use="round trip",
        food_effect_in_question=False, model_risk=Rating.MEDIUM, engine_image_digest="roundtrip",
        software_versions={}, sampling_end_h=sampling_end_h,
    )
    # One scenario per study, whichever stage the MAP gave it. A study with no MAP scenario (a special population or
    # a DDI arm, MS-01 §3.3 rule 4) is not simulated in the healthy-volunteer model and is named instead.
    by_study: dict[str, Any] = {}
    for scenario in map_doc.scenarios:
        by_study.setdefault(scenario.study_id, scenario)
    wanted = list(imported.simulation_of) if linked_only else [s.study_id for s in studies]
    scenarios = [by_study[sid].model_copy(update={"stage": ROUNDTRIP_STAGE}) for sid in wanted if sid in by_study]
    built = build_stage_snapshot(imported.cpf, scenarios, stage=ROUNDTRIP_STAGE, skip_unbuildable=True)
    ours = json.loads(built.snapshot.model_dump_json(by_alias=True, exclude_none=True))
    assignment = {s.study_id: s.assignment for s in map_doc.studies}
    notes = list(built.notes) + [f"{sid}: no MAP scenario ({assignment.get(sid, '?')}); not simulated"
                                 for sid in wanted if sid not in by_study]
    return ours, {sid: assignment.get(sid, "") for sid in built.simulations}, notes


def roundtrip_inputs(imported: ReferenceImport) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """Our snapshot of every linked study, the (ours, published, offset) pairs, and the notes of the build."""
    ours, assignment, notes = study_snapshot(imported, linked_only=True)
    placed = set(assignment)
    pairs = [{"ours": sid, "published": imported.simulation_of[sid], "offset_min": imported.offset_min.get(sid, 0.0),
              "end_h": _sim_end_h(ours, sid), "by_design": imported.differs_by_design.get(sid, "")}
             for sid in imported.simulation_of if sid in placed]
    return ours, pairs, notes


def _sim_end_h(snapshot: dict[str, Any], name: str) -> float:
    sim = next(s for s in snapshot["Simulations"] if s["Name"] == name)
    ends = [p["Value"] for block in sim.get("OutputSchema", []) for p in block["Parameters"] if p["Name"] == "End time"]
    return float(max(ends)) if ends else 24.0


def system_roundtrip_inputs(imported: SystemImport) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """The round trip of a model system: every linked study built as the system simulates it, each pair compared on
    the study's analyte (a compound's plasma, or a published sum observer) at the same output path on both sides."""
    system = imported.system
    studies = [StudyRecord.model_validate({k: v for k, v in s.items() if k in StudyRecord.model_fields})
               for s in imported.studies]
    main_cpf = system.cpf(system.parents[0])
    sampling_end_h = {s["study_id"]: max(s["profile"]["times"]) / 60.0 if s["profile"]["time_unit"] == "min"
                      else max(s["profile"]["times"]) for s in imported.studies}
    map_doc = generate_map(
        compound=system.name, cpf=main_cpf, studies=studies, split=split_studies(studies, QuestionOfInterest()),
        objective="round trip", context_of_use="round trip", food_effect_in_question=False, model_risk=Rating.MEDIUM,
        engine_image_digest="roundtrip", software_versions={}, sampling_end_h=sampling_end_h,
    )
    by_study: dict[str, Any] = {}
    for scenario in map_doc.scenarios:
        by_study.setdefault(scenario.study_id, scenario)
    wanted = [sid for sid in imported.simulation_of if sid in by_study]
    built = build_stage_snapshot(main_cpf, [by_study[sid].model_copy(update={"stage": ROUNDTRIP_STAGE}) for sid in wanted],
                                 stage=ROUNDTRIP_STAGE, skip_unbuildable=True, system=system)
    ours = json.loads(built.snapshot.model_dump_json(by_alias=True, exclude_none=True))
    analyte_of = {s["study_id"]: s.get("analyte") for s in imported.studies}
    placed = set(built.simulations)
    pairs = [{"ours": sid, "published": imported.simulation_of[sid], "offset_min": imported.offset_min.get(sid, 0.0),
              "end_h": _sim_end_h(ours, sid), "by_design": imported.differs_by_design.get(sid, ""),
              "analyte": analyte_of[sid], "output": system.analytes[analyte_of[sid]].output_path}
             for sid in wanted if sid in placed]
    notes = list(built.notes) + [f"{sid}: no MAP scenario; not simulated" for sid in imported.simulation_of
                                 if sid not in by_study]
    return ours, pairs, notes
