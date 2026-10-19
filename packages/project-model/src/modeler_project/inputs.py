"""P4 model inputs (plan §5.2 P4, T-49): CPF v1 from the evidence, the study catalog from the datasets, and the
readiness of both for PK-Sim.

The CPF is regenerated from the evidence every time (CLAUDE.md: the CPF is the system of record, every simulation is
regenerated from it): one record per parameter, its value in the PK-Sim unit, its provenance carried into PK-Sim's
``ValueOrigin`` (Source and Method from the harvested enums only; the citation, locator, grade and the evidence id in
the description). Values flow in without a per-item decision (D-27): every value not excluded counts, unless a hold
flag keeps it for a person, and `sources.select` picks the one a parameter takes (D-32: agreeing values are one value
with all their sources, the best source wins within the conflict fold, values beyond it wait on a person; nothing is
averaged). A process parameter is bound to the PK-Sim process that carries it; when the harvested table offers several
(``CLspec/[Enzyme]`` on two process types), a person chooses (``InputChoices``).

Readiness is the S0 gate (completeness, placeable pathways, expression profiles) plus what P4 adds: every solid study
names a formulation the CPF defines, the MS-01 split has studies to train on, the observed data's origins, and a build
of every planned simulation with the software builder. Loading the snapshots into PK-Sim (the engine dry run) needs the
engine and is done on the server. The inputs are accepted by name when ready (no signature: the MAP signature in P5
covers them).
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from modeler_project.artifacts import ArtifactKind, ArtifactRef, ArtifactVersion
from modeler_project.brief import ProjectBrief
from modeler_project.datasets import ObservedDataset
from modeler_project.evidence import EvidenceItem, EvidenceState, SourceType, numeric_target, review_flags
from modeler_project.sources import held, included, rule, select
from modeler_project.workspace import Workspace
from pbpk_domain import parameters
from pbpk_domain.cpf.models import CPF, EngineBinding, ParameterRecord, ParameterStatus, Provenance
from pbpk_domain.cpf.process_bindings import binding_candidates, is_process_id
from pbpk_domain.data_origin import REAL_ORIGINS

MAIN = "main"
CHOICES = "choices"
PUBLISHED = "published"
SOLID = ("ir_tablet", "ir_capsule", "mr", "suspension")

# Evidence source -> PK-Sim ValueOrigin.Source (harvested: snapshot.models.VALUE_ORIGIN_SOURCES). The evidence's own
# source type stays readable in the description.
VALUE_ORIGIN_SOURCE = {
    SourceType.PUBLICATION: "Publication", SourceType.REGULATORY_REVIEW: "Publication", SourceType.OSP_LIBRARY: "Publication",
    SourceType.DATABASE: "Database", SourceType.CLIENT_REPORT: "Other", SourceType.CLIENT_FILE: "Other",
    SourceType.PROPOSAL: "Other", SourceType.PREDICTED: "Other", SourceType.ASSUMPTION: "Other",
}
# The unit PK-Sim's builder takes where the storage conversion leaves a dimensionless value without one
# (snapshot.builder: lipophilicity is checked against "Log Units"). From the parameter registry, like the tables below.
_BUILDER_UNIT = parameters.builder_units()
_IN_VIVO = parameters.origin_prefixes("in_vivo")

# CPF ids the model takes: the compound fields and families `pbpk_domain.cpf.build` reads (process parameters are
# checked against the harvested process table instead). An id outside these is never placed in PK-Sim, so it is kept
# out of the CPF and named: a value under an unknown name once satisfied S0 while the model had no clearance.
MODEL_IDS = parameters.model_ids()
MODEL_PREFIXES = parameters.model_prefixes()
# kept in the CPF for checks and the report, not set in PK-Sim (PK-Sim computes the blood-to-plasma ratio itself; the
# fraction excreted unchanged in urine and the fraction metabolised per pathway constrain the elimination fitted in S1)
REFERENCE_IDS = parameters.reference_ids()
REFERENCE_PREFIXES = parameters.reference_prefixes()
# what the S0 targets and the data plan's placeholders mean, for the person correcting a value's target
PLACEHOLDERS = {
    "elim": "an elimination pathway: give the concrete one (elim.renal.gfr_fraction, elim.hepatic.<enzyme>.clspec, …)",
    "phys.pka": "a pKa: say whether it is acidic or basic",
}


def placement(cpf_id: str) -> str | None:
    """"model" (PK-Sim takes it), "process" (a process parameter the harvested table places), "reference" (kept for
    checks, not set in PK-Sim), or None: not a parameter the model uses (`pbpk_domain.parameters.placement`)."""
    return parameters.placement(cpf_id)


def target_problem(target: str) -> str | None:
    """Why a value cannot be filed under `target` (None: it can). For corrections typed by a person."""
    if "{" in target or "<" in target:
        return f"{target} is a template: give the concrete parameter"
    if target == "phys.pka":
        return None
    if target in PLACEHOLDERS:
        return f"{target!r} means {PLACEHOLDERS[target]}"
    if reason := parameters.refusal(target):
        return f"{target}: {reason}"
    if placement(target) is None:
        if is_process_id(target):
            return f"{target}: no harvested PK-Sim process carries this parameter"
        return f"{target} is not a parameter the model uses"
    return None
_IN_VITRO = parameters.origin_prefixes("in_vitro")


def value_origin_method(item: EvidenceItem) -> str:
    """PK-Sim ValueOrigin.Method (harvested values) for an evidence item: how the value was obtained."""
    if item.source_type is SourceType.ASSUMPTION:
        return "Assumption"
    if item.source_type is SourceType.PREDICTED:
        return "Other"
    if item.target.startswith(_IN_VIVO):
        return "InVivo"
    if item.target.startswith(_IN_VITRO):
        return "InVitro"
    return "Unknown"


def provenance_for(item: EvidenceItem, version: int) -> Provenance:
    s = item.source
    citation = ", ".join(x for x in (s.authors, str(s.year) if s.year else "", s.title) if x) or "source"
    ids = " ".join(x for x in (f"doi:{s.doi}" if s.doi else "", f"pmid:{s.pmid}" if s.pmid else "", s.url or "") if x)
    where = " · ".join(x for x in (ids, s.locator, f"p.{s.page}" if s.page else "") if x)
    reference = f"{citation}{f' ({where})' if where else ''} · {item.source_type.value.lower()} · grade {item.confidence}"
    return Provenance(source_type=VALUE_ORIGIN_SOURCE[item.source_type], reference=reference,
                      method=value_origin_method(item), evidence=f"{item.id}@v{version}")


class InputChoices(BaseModel):
    """A person's model-structure choices that the evidence alone does not decide, each with its reason."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    process: dict[str, str] = Field(default_factory=dict)            # pathway prefix -> PK-Sim process (internal name)
    formulation: dict[str, str] = Field(default_factory=dict)        # study id -> CPF formulation name
    excluded_studies: dict[str, str] = Field(default_factory=dict)   # study id -> why it is left out
    reasons: dict[str, str] = Field(default_factory=dict)            # choice key -> why


def choices(ws: Workspace) -> InputChoices:
    version = ws.latest(ArtifactKind.CPF, CHOICES)
    return InputChoices.model_validate(version.content) if version else InputChoices()


def set_choice(ws: Workspace, *, kind: str, key: str, value: str | None, reason: str, by: str) -> InputChoices:
    current = choices(ws).model_dump()
    if kind not in ("process", "formulation", "excluded_studies"):
        raise ValueError(f"unknown choice {kind!r}")
    if value is None:
        current[kind].pop(key, None)
    else:
        current[kind][key] = value
    current["reasons"][f"{kind}:{key}"] = reason
    ws.commit(ArtifactKind.CPF, CHOICES, InputChoices.model_validate(current).model_dump(), actor=by,
              reason=f"{kind} {key}: {value or 'cleared'} ({reason})")
    return choices(ws)


# --- the CPF ---------------------------------------------------------------------------------------------------


def _included(ws: Workspace) -> list[tuple[EvidenceItem, ArtifactVersion]]:
    """Every evidence item not excluded, with its version (D-27: values flow in without a per-item decision)."""
    out = []
    for version in ws.list(ArtifactKind.EVIDENCE):
        if not version.id.startswith("ev-"):
            continue
        item = EvidenceItem.from_content(version.content)
        if included(item):
            out.append((item, version))
    return out


def _issue(issues: list[dict[str, Any]], problems: list[str], kind: str, target: str, evidence: list[str], message: str,
           *, blocking: bool = True) -> None:
    """One assembly issue: typed (what settles it on the page) and, when it blocks, in words (the readiness report)."""
    if blocking:
        problems.append(message)
    issues.append({"kind": kind, "target": target, "evidence": evidence, "message": message, "blocking": blocking})


def _pka_kind(item: EvidenceItem) -> str | None:
    """"neutral", "acid" or "base" from a pKa item's value and conditions; None when they do not say."""
    if isinstance(item.value, str) and item.value.strip().lower() == "neutral":
        return "neutral"
    text = " ".join(f"{k} {v}" for k, v in item.conditions.items()).lower()
    kinds = [k for k in ("acid", "base") if k in text]
    return kinds[0] if len(kinds) == 1 else None


def _cpf_id(item: EvidenceItem, pka_index: dict[str, int], problems: list[str], issues: list[dict[str, Any]]) -> str | None:
    """The CPF id an item fills, or None with an issue that says why. The issue blocks readiness only for a value a
    person accepted: one only proposed waits on the to-do list until it is corrected or excluded (D-27)."""
    target = item.target
    blocking = item.state is EvidenceState.ACCEPTED
    if "{" in target or "<" in target:
        _issue(issues, problems, "correct", target, [item.id], f"{item.id}: target {target} is a template; give the concrete parameter", blocking=blocking)
        return None
    if target == "phys.halogens":
        _issue(issues, problems, "correct", target, [item.id], f"{item.id}: give one value per atom (phys.halogens.F, .Cl, .Br, .I)", blocking=blocking)
        return None
    if target == "phys.pka":
        kind = _pka_kind(item)
        if kind == "neutral":
            return "phys.pka.neutral"
        if kind is None:
            _issue(issues, problems, "pka", target, [item.id], f"{item.id}: pKa {item.value} — the conditions must say acid or base", blocking=blocking)
            return None
        index = pka_index[kind]
        pka_index[kind] += 1
        return f"phys.pka.{kind}.{index}"
    if isinstance(item.value, str) and numeric_target(target):
        _issue(issues, problems, "correct", target, [item.id],
               f"{item.id}: {item.value[:80]!r} is a description, not a value for {target}: give the number it states (and "
               "the parameter), or reject it (kept out of the CPF)", blocking=blocking)
        return None
    if reason := parameters.refusal(target):
        _issue(issues, problems, "correct", target, [item.id], f"{item.id}: {target}: {reason} (kept out of the CPF)", blocking=blocking)
        return None
    target = parameters.canonical(target)   # an alias is filed under the id it stands for (registry `alias_of`)
    if not is_process_id(target) and placement(target) is None:
        what = PLACEHOLDERS.get(target)
        _issue(issues, problems, "correct", target, [item.id],
               f"{item.id}: {target!r} " + (f"means {what}" if what else "is not a parameter the model uses: correct its "
                                                                        "target or reject it") + " (kept out of the CPF)", blocking=blocking)
        return None
    return target


def _pka_groups(candidates: list[tuple[EvidenceItem, ArtifactVersion]], problems: list[str],
                issues: list[dict[str, Any]]) -> list[tuple[EvidenceItem, ArtifactVersion]]:
    """pKa values of one kind (acid or base) are separate ionizable groups only when a person accepted each of them.
    Two sources for what may be the same group are never made two groups by code: they wait on a person."""
    by_kind: dict[str, list[tuple[EvidenceItem, ArtifactVersion]]] = defaultdict(list)
    for item, version in candidates:
        if item.target == "phys.pka" and (kind := _pka_kind(item)) in ("acid", "base"):
            by_kind[kind].append((item, version))
    waiting: set[str] = set()
    for kind, group in by_kind.items():
        if len(group) > 1 and any(i.state is not EvidenceState.ACCEPTED for i, _v in group):
            waiting |= {i.id for i, _v in group}
            listed = ", ".join(f"{i.id} {i.value}" for i, _v in group)
            _issue(issues, problems, "pka", "phys.pka", [i.id for i, _v in group],
                   f"phys.pka: {len(group)} {kind}ic pKa values ({listed}): keep one per ionizable group (accept it) and "
                   "exclude the others")
    return [(i, v) for i, v in candidates if i.id not in waiting]


def assemble_cpf(ws: Workspace, compound: str, picked: InputChoices) -> tuple[CPF, dict[str, Any], list[ArtifactVersion]]:
    """CPF v1 from the evidence not excluded: (cpf, report, the evidence versions it read)."""
    problems: list[str] = []
    issues: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    by_id: dict[str, list[tuple[EvidenceItem, ArtifactVersion]]] = defaultdict(list)
    pka_index: dict[str, int] = defaultdict(int)
    candidates = []
    for item, version in sorted(_included(ws), key=lambda iv: (iv[0].target, iv[0].proposed_at)):
        holds = held(item)
        if holds:
            _issue(issues, problems, "review", item.target, [item.id],
                   f"{item.id}: {item.target} = {item.value} {item.unit or ''}".rstrip() + " is held until a person accepts or "
                   f"corrects it ({'; '.join(holds)})", blocking=False)
            continue
        candidates.append((item, version))
    for item, version in _pka_groups(candidates, problems, issues):
        cpf_id = _cpf_id(item, pka_index, problems, issues)
        if cpf_id:
            by_id[cpf_id].append((item, version))
    records, used, sources = [], [], {}
    for cpf_id, group in sorted(by_id.items()):
        versions = {i.id: (i, v) for i, v in group}
        selection = select([i for i, _v in group])
        sources[cpf_id] = selection.to_content()
        used += [v for _i, v in group]
        if selection.conflict:
            listed = ", ".join(f"{i.id} {i.value_pksim if i.value_pksim is not None else i.value}" for i, _v in group)
            _issue(issues, problems, "conflict", cpf_id, [i.id for i, _v in group],
                   f"{cpf_id}: values more than {rule().conflict_fold:g}-fold apart ({listed}); keep one — values are "
                   "never averaged")
            continue
        item, version = versions[selection.kept]
        value = item.value_pksim if isinstance(item.value, int | float) else item.value
        unit = item.unit_pksim if isinstance(item.value, int | float) else None
        unit = unit or _BUILDER_UNIT.get(cpf_id)
        binding = None
        if is_process_id(cpf_id) and placement(cpf_id) == "process":
            candidates = binding_candidates(cpf_id)
            prefix = cpf_id.rpartition(".")[0]
            chosen = [c for c in candidates if len(candidates) == 1 or picked.process.get(prefix) == c.process]
            if not candidates:
                _issue(issues, problems, "correct", cpf_id, [item.id],
                       f"{cpf_id}: no harvested PK-Sim process carries this parameter; it cannot be placed")
            elif len(chosen) != 1:
                _issue(issues, problems, "process", prefix, [item.id], f"{cpf_id}: choose the process type for {prefix} "
                                                                        f"({' or '.join(c.process for c in candidates)})")
            else:
                c = chosen[0]
                if (unit or None) != (c.unit or None):
                    _issue(issues, problems, "unit", cpf_id, [item.id],
                           f"{cpf_id}: value in {unit!r}, PK-Sim places {c.parameter} in {c.unit!r}; convert it")
                binding = c.binding("Client" if item.provider == "CLIENT" else "Literature")
                bindings.append({"id": cpf_id, "process": binding.process, "parameter": c.parameter, "unit": c.unit})
        elif (path := parameters.individual_paths().get(cpf_id)) is not None:
            # set on the Individual at its harvested path (registry 1.2: elim.ehc_fraction), as a published model's
            # indiv.* value is (cpf.build.individual_parameters)
            binding = EngineBinding(building_block="Individual", parameter=path)
            bindings.append({"id": cpf_id, "process": None, "parameter": path, "unit": unit})
        status = ParameterStatus.PREDICTED if item.source_type is SourceType.PREDICTED else ParameterStatus.FIXED
        provenance = provenance_for(item, version.version)
        if selection.agreeing:   # the review and the MAP see every source that agrees (D-32)
            provenance = provenance.model_copy(update={
                "reference": f"{provenance.reference} · agreed by {len(selection.agreeing)} other source(s): "
                             f"{', '.join(selection.agreeing)}"})
        records.append(ParameterRecord(id=cpf_id, value=value, unit=unit, status=status, provenance=provenance,
                                       engine_binding=binding))
    cpf = CPF(compound=compound, parameters=tuple(records))
    return cpf, {"problems": problems, "issues": issues, "bindings": bindings, "records": len(records),
                 "sources": sources}, used


# --- the study catalog -----------------------------------------------------------------------------------------


def _profile(dataset: ObservedDataset) -> dict[str, Any] | None:
    """The profile the campaign judges: the first mean / median series (values below LLOQ left out, LLOQ kept)."""
    series = next((s for s in dataset.series if s.statistic != "individual"), None)
    if series is None:
        return None
    pairs = [(t, v, (series.error[i] if series.error is not None else None))
             for i, (t, v) in enumerate(zip(series.times, series.values, strict=True)) if v is not None]
    if not pairs:
        return None
    sd = [e for _t, _v, e in pairs] if series.error_kind == "SD" and all(e is not None for _t, _v, e in pairs) else None
    return {"times": [t for t, _v, _e in pairs], "values": [v for _t, v, _e in pairs], "time_unit": dataset.time_unit,
            "unit": dataset.unit, "sd": sd, "lloq": dataset.study.get("lloq")}


def usable_dataset(dataset: ObservedDataset) -> bool:
    """A dataset counts unless excluded (REJECTED, with a reason; D-27); one read from a figure only once the person
    approved the overlay of its computed points."""
    from modeler_project.datasets import Origin

    if dataset.state is EvidenceState.REJECTED:
        return False
    if dataset.origin is Origin.FIGURE_DIGITIZED and dataset.state is not EvidenceState.ACCEPTED:
        return bool(dataset.digitization and dataset.digitization.overlay_approved_by)
    return True


def study_catalog(ws: Workspace, picked: InputChoices) -> tuple[list[dict[str, Any]], list[str], list[ArtifactVersion]]:
    """One row per study from the datasets not excluded, in the study-upload shape the campaign path reads: (rows,
    notes, versions). Two datasets for one study id: a person's accepted one first, then the client's, then the
    earlier; the other is named and not used."""
    rows, notes, used = [], [], []
    versions = sorted(ws.list(ArtifactKind.DATASET), key=lambda v: v.created_at)
    usable = [(v, d) for v in versions if usable_dataset(d := ObservedDataset.from_content(v.content))]
    winner: dict[str, str] = {}
    for _v, d in sorted(usable, key=lambda vd: (vd[1].state is not EvidenceState.ACCEPTED, vd[1].provider != "CLIENT",
                                                  vd[0].created_at)):
        winner.setdefault(str(d.study["study_id"]), d.id)
    for version, dataset in usable:
        study = dict(dataset.study)
        sid = study["study_id"]
        if sid in picked.excluded_studies:
            if winner[sid] == dataset.id:
                notes.append(f"{sid}: left out ({picked.excluded_studies[sid]})")
            continue
        if winner[sid] != dataset.id:
            notes.append(f"{sid}: also in {winner[sid]}; {dataset.id} is not used (two datasets for one study)")
            continue
        profile = _profile(dataset)
        row: dict[str, Any] = {**study, "origin": dataset.origin.value, "dataset_id": dataset.id,
                               "purpose": dataset.purpose, "evaluable": profile is not None,
                               "demographics_choice": dataset.demographics_choice}
        if profile is not None:
            row["profile"] = profile
        elif dataset.kind == "pk_parameters":
            notes.append(f"{sid}: PK parameters only — it can judge a prediction once the evaluation reads reported NCA; "
                         "it trains no fit")
        else:
            notes.append(f"{sid}: individual profiles only — population evaluation (PE %, GMR, 90 % CI) is the "
                         "evaluation lane's; not judged by the current campaign")
        if study.get("formulation") in SOLID and sid in picked.formulation:
            row["formulation_name"] = picked.formulation[sid]
        rows.append(row)
        used.append(version)
    return rows, notes, used


# --- readiness -------------------------------------------------------------------------------------------------


def unstated_demographics(rows: list[dict[str, Any]]) -> list[str]:
    """Studies with no demographics, no published individual and no explicit healthy adult default (D-29: the default
    is never applied silently)."""
    return [r["study_id"] for r in rows if not (r.get("demographics") or r.get("published_individual")
                                                or r.get("demographics_choice") == "healthy_adult_default")]


def _check(name: str, ok: bool, detail: str | list[str] = "") -> dict[str, Any]:
    return {"check": name, "ok": ok, "detail": detail if isinstance(detail, list) else ([detail] if detail else [])}


def readiness(cpf: CPF, rows: list[dict[str, Any]], assembly: dict[str, Any], brief: ProjectBrief | None) -> dict[str, Any]:
    from pbpk_domain.campaign.map import generate_map
    from pbpk_domain.campaign.round_build import ScenarioBuildError, build_stage_snapshot
    from pbpk_domain.campaign.split import QuestionOfInterest, StudyRecord, split_studies
    from pbpk_domain.cpf import check_completeness
    from pbpk_domain.cpf.build import missing_expression_profiles, unplaceable_parameters
    from pbpk_domain.cpf.formulations import FormulationError, cpf_formulation, resolve_formulation_name
    from pbpk_domain.m15 import Rating

    checks = [_check("assembly", not assembly["problems"], assembly["problems"])]
    completeness = check_completeness(cpf)
    checks.append(_check("S0 completeness (MS-01 §2.2)", completeness.ready, list(completeness.missing)))
    unplaced: tuple[str, ...] = ()
    if completeness.ready:
        try:
            unplaced = unplaceable_parameters(cpf)
        except ValueError as exc:
            unplaced = (str(exc),)
    checks.append(_check("every pathway placeable", not unplaced, [f"{p}: not placed by the builder" for p in unplaced]))
    expression = missing_expression_profiles(cpf)
    checks.append(_check("expression profiles", not expression,
                         [f"{m}: no harvested expression profile" for m in expression]))
    fields = set(StudyRecord.model_fields)
    records, formulation_problems = [], []
    for row in rows:
        try:
            records.append(StudyRecord.model_validate({k: v for k, v in row.items() if k in fields}))
        except ValueError as exc:
            formulation_problems.append(f"{row['study_id']}: study record: {exc}")
            continue
        if row.get("formulation") in SOLID:
            try:
                name, _note = resolve_formulation_name(cpf, row.get("formulation_name"))
                cpf_formulation(cpf, name)
            except FormulationError as exc:
                formulation_problems.append(f"{row['study_id']}: {exc}")
    checks.append(_check("formulations of solid studies", not formulation_problems, formulation_problems))
    regimen = [f"{r['study_id']}: a multiple-dose study needs its number of doses and dosing interval" for r in rows
               if r.get("design") == "MD" and not (r.get("n_doses") and r.get("dosing_interval_h"))]
    checks.append(_check("multiple-dose regimens", not regimen, regimen))
    checks.append(_check("demographics stated (D-29)", not (unstated := unstated_demographics(rows)),
                         [f"{sid}: give the demographics, or choose the healthy adult default" for sid in unstated]))
    evaluable = [r for r in rows if r.get("evaluable")]
    not_real = [f"{r['study_id']} ({r['origin'].lower()})" for r in evaluable if r["origin"] not in {o.value for o in REAL_ORIGINS}]
    checks.append(_check("observed data to judge on", bool(evaluable), [] if evaluable else ["no dataset with a profile"]))
    checks.append(_check("observed data are real (plan §9.4)", not not_real,
                         [f"{x}: test data, cannot sign off a model outside an exploratory project" for x in not_real]))
    split_view: dict[str, list[str]] = {}
    build_notes: list[str] = []
    build_ok = False
    if records and completeness.ready and not unplaced:
        from modeler_project.plan import applications

        food = "APP-12" in applications(brief)
        split = split_studies(records, QuestionOfInterest(food_effect=food))
        # each study simulated over its whole sampled window, as campaign:prepare does
        hours = {"min": 1 / 60, "h": 1.0, "day": 24.0}
        sampling_end_h = {r["study_id"]: max(r["profile"]["times"]) * hours.get(r["profile"]["time_unit"], 1.0)
                          for r in evaluable if r["profile"]["time_unit"] in hours}
        map_doc = generate_map(compound=cpf.compound, cpf=cpf, studies=records, split=split,
                               objective="P4 readiness: the default MS-01 plan", context_of_use="readiness check",
                               food_effect_in_question=food, model_risk=Rating.MEDIUM,
                               engine_image_digest="sha256:" + "0" * 64, software_versions={"ospsuite": "12.4.4"},
                               sampling_end_h=sampling_end_h)
        for s in map_doc.studies:
            split_view.setdefault(s.assignment, []).append(s.study_id)
        stages = sorted({sc.stage for sc in map_doc.scenarios})
        build_ok = True
        for stage in stages:
            try:
                built = build_stage_snapshot(cpf, list(map_doc.scenarios), stage=stage, skip_unbuildable=True)
                build_notes += [f"{stage}: {n}" for n in built.notes]
                build_notes.append(f"{stage}: {len(built.simulations)} simulation(s) built")
            except (ScenarioBuildError, ValueError) as exc:
                build_ok = False
                build_notes.append(f"{stage}: {exc}")
    checks.append(_check("every planned simulation builds (software)", build_ok,
                         build_notes or ["not attempted: the CPF is not complete and placeable yet"]))
    ready = all(c["ok"] for c in checks if c["check"] != "observed data are real (plan §9.4)")
    return {"ready": ready, "checks": checks, "split": split_view,
            "engine_dry_run": "not run here: loading the snapshots into PK-Sim needs the engine (server)"}


# --- the whole step --------------------------------------------------------------------------------------------


def assemble(ws: Workspace, *, by: str) -> dict[str, Any]:
    """Regenerate CPF v1, the study catalog and the readiness report (each a new version only when it changed)."""
    brief_version = ws.latest(ArtifactKind.BRIEF, "main")
    if brief_version is None:
        raise ValueError("no brief: start from P0/P1")
    brief = ProjectBrief.from_content(brief_version.content)
    matrix_version = ws.latest(ArtifactKind.REQUIREMENTS, "main")
    picked_version = ws.latest(ArtifactKind.CPF, CHOICES)
    picked = choices(ws)
    cpf, report, evidence_used = assemble_cpf(ws, brief.drug_name, picked)
    rows, notes, datasets_used = study_catalog(ws, picked)
    extra = [v.ref for v in (matrix_version, picked_version) if v is not None]
    cpf_version = ws.commit(ArtifactKind.CPF, MAIN, {"cpf": cpf.model_dump(mode="json", exclude={"created_at"}), "assembly": report},
                            derived_from=[brief_version.ref, *extra, *[v.ref for v in evidence_used]], actor=by,
                            reason=f"assembled from {len(evidence_used)} evidence items")
    catalog_version = ws.commit(ArtifactKind.STUDY_CATALOG, MAIN, {"studies": rows, "notes": notes},
                                derived_from=[*([picked_version.ref] if picked_version else []), *[v.ref for v in datasets_used]],
                                actor=by, reason=f"{len(rows)} studies from accepted datasets")
    result = {**readiness(cpf, rows, report, brief), "inputs_key": inputs_key(ws)}
    ready_version = ws.commit(ArtifactKind.READINESS, MAIN, result, derived_from=[cpf_version.ref, catalog_version.ref],
                              actor=by, reason="ready" if result["ready"] else "not ready")
    return {"cpf": cpf_version, "catalog": catalog_version, "readiness": ready_version}


def inputs_key(ws: Workspace) -> str:
    """What the assembly read, as one key: the brief, the data checklist, the choices and every evidence item and dataset
    at its latest version. A new value is a new artifact, which makes nothing stale, so the key is what says the inputs
    have changed since they were assembled."""
    read = [ws.latest(ArtifactKind.BRIEF, "main"), ws.latest(ArtifactKind.REQUIREMENTS, "main"),
            ws.latest(ArtifactKind.CPF, CHOICES), *ws.list(ArtifactKind.EVIDENCE), *ws.list(ArtifactKind.DATASET)]
    text = "\n".join(sorted(f"{v.ref.kind.value}:{v.ref.id}:{v.ref.version}" for v in read if v is not None))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _changed(ws: Workspace, ready: ArtifactVersion) -> bool:
    from modeler_project.artifacts import ArtifactStatus

    return ws.status(ready) is ArtifactStatus.STALE or ready.content.get("inputs_key") != inputs_key(ws)


def refresh_inputs(ws: Workspace, *, by: str) -> bool:
    """Assemble again when the inputs are missing or have changed (redesign §3.2: the CPF is assembled continuously, not
    on a button). Called after every change to the evidence, the datasets or the choices. True when assembled."""
    if ws.latest(ArtifactKind.BRIEF, "main") is None:
        return False
    ready = ws.latest(ArtifactKind.READINESS, MAIN)
    if ready is not None and not _changed(ws, ready):
        return False
    assemble(ws, by=by)
    return True


def inputs_ready(ws: Workspace) -> tuple[bool, str]:
    """Whether the plan can read the inputs: assembled, current and ready (no acceptance needed, D-27). The reason when
    not."""
    version = ws.latest(ArtifactKind.READINESS, MAIN)
    if version is None:
        return False, "the model inputs are not assembled yet"
    if _changed(ws, version):
        return False, "the model inputs changed since they were checked: assemble them again"
    if not version.content["ready"]:
        failing = [c["check"] for c in version.content["checks"] if not c["ok"]]
        return False, "the model inputs are not ready: " + "; ".join(failing)
    return True, ""


def accept_inputs(ws: Workspace, *, by: str, printed_name: str = "", note: str = "") -> None:
    """Close P4 with a named approval of the readiness report; refused unless it is ready and current."""
    version = ws.latest(ArtifactKind.READINESS, MAIN)
    if version is None:
        raise ValueError("assemble the inputs first")
    if not version.content["ready"]:
        failing = [c["check"] for c in version.content["checks"] if not c["ok"]]
        raise ValueError("the inputs are not ready: " + "; ".join(failing))
    ws.approve(version.ref, by=by, printed_name=printed_name, meaning="Reviewed", note=note)


def current_cpf(ws: Workspace) -> CPF | None:
    version = ws.latest(ArtifactKind.CPF, MAIN)
    return CPF.model_validate(version.content["cpf"]) if version else None


def cpf_assembly(ws: Workspace) -> dict[str, Any] | None:
    """The latest assembly report: which evidence made each value, and the open issues."""
    version = ws.latest(ArtifactKind.CPF, MAIN)
    return version.content["assembly"] if version else None


def catalog_rows(ws: Workspace) -> list[dict[str, Any]]:
    """The study catalog's rows (a StudyRecord each, with its profile and whether it is evaluable); [] before P4."""
    version = ws.latest(ArtifactKind.STUDY_CATALOG, MAIN)
    return list(version.content["studies"]) if version else []


def readiness_report(ws: Workspace) -> dict[str, Any] | None:
    """The latest readiness report: whether the inputs are ready, and each check with its detail."""
    version = ws.latest(ArtifactKind.READINESS, MAIN)
    return version.content if version else None


class Publication(BaseModel):
    """CPF/published: the accepted CPF and readiness versions handed to the campaign path, and the studies sent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    compound: str
    studies: list[str]
    cpf: ArtifactRef
    readiness: ArtifactRef

    def to_content(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def record_publication(ws: Workspace, *, studies: list[str], by: str) -> ArtifactVersion:
    """Record the hand-off of the accepted inputs (the CPF and the judged studies) to the campaign path."""
    cpf_version, ready = ws.latest(ArtifactKind.CPF, MAIN), ws.latest(ArtifactKind.READINESS, MAIN)
    if cpf_version is None or ready is None:
        raise ValueError("assemble and accept the inputs first")
    record = Publication(compound=CPF.model_validate(cpf_version.content["cpf"]).compound, studies=studies,
                         cpf=cpf_version.ref, readiness=ready.ref)
    return ws.commit(ArtifactKind.CPF, PUBLISHED, record.to_content(), derived_from=[cpf_version.ref, ready.ref], actor=by,
                     reason=f"handed to the campaign path: {len(studies)} studies")


def publication(ws: Workspace) -> Publication | None:
    version = ws.latest(ArtifactKind.CPF, PUBLISHED)
    return Publication.model_validate(version.content) if version else None


# --- what is left to do (the page's to-do list) ----------------------------------------------------------------

# the concrete targets an elimination placeholder can become (harvested process table; <enzyme> from the expression
# library), offered to the person correcting it
PATHWAY_TARGETS = ("elim.fe_urine", "elim.fm.<enzyme>", "elim.renal.gfr_fraction", "elim.renal.total.plasma_clearance",
                   "elim.hepatic.total.plasma_clearance", "elim.hepatic.<enzyme>.clspec", "elim.hepatic.<enzyme>.cl_intrinsic",
                   "elim.hepatic.<enzyme>.km", "elim.hepatic.<enzyme>.vmax")
_MW_IN_RECORD = re.compile(r'"MolecularWeight"\s*:\s*"?(\d+(?:\.\d+)?)"?')


def evidence_view(item: EvidenceItem) -> dict[str, Any]:
    """An evidence item as the to-do list shows it: the value in both units, where it comes from, how it was graded."""
    s = item.source
    return {"id": item.id, "target": item.target, "value": item.value, "unit": item.unit, "value_pksim": item.value_pksim,
            "unit_pksim": item.unit_pksim, "state": item.state.value, "confidence": item.confidence,
            "flags": list(dict.fromkeys([*item.flags, *review_flags(item)])),
            "provider": item.provider, "source_type": item.source_type.value, "conditions": item.conditions,
            "source": {"title": s.title, "authors": s.authors, "year": s.year, "doi": s.doi, "page": s.page,
                       "locator": s.locator},
            "quote": item.quote[:300]}


def _suggestions(target: str) -> dict[str, Any]:
    from pbpk_domain.expression import expression_library

    molecules = sorted(expression_library())
    if target.startswith("elim.hepatic.{enzyme}."):
        quantities = target.removeprefix("elim.hepatic.{enzyme}.").split("/")
        return {"targets": [f"elim.hepatic.<enzyme>.{q}" for q in quantities], "molecules": molecules}
    if target == "elim" or target.startswith("elim."):
        return {"targets": list(PATHWAY_TARGETS), "molecules": molecules}
    return {"targets": sorted(MODEL_IDS - {"alt.select"}) + ["phys.pka"], "molecules": []}


def identity_mw(ws: Workspace) -> dict[str, Any] | None:
    """The molecular weight in the brief's PubChem record (the stored document), quoted as PubChem returned it."""
    from modeler_project.documents import DocumentLibrary

    version = ws.latest(ArtifactKind.BRIEF, MAIN)
    if version is None:
        return None
    brief = ProjectBrief.from_content(version.content)
    record = brief.get("drug.pubchem_cid")
    cite = next((c for c in (record.citations if record else ()) if c.doc_sha256), None)
    if cite is None:
        return None
    text = DocumentLibrary(ws).page_text(cite.doc_sha256, 1) or ""
    match = _MW_IN_RECORD.search(text)
    if match is None:
        return None
    return {"value": float(match.group(1)), "unit": "g/mol", "quote": match.group(0), "doc_sha256": cite.doc_sha256,
            "cid": brief.value("drug.pubchem_cid"), "name": brief.drug_name}


def propose_identity_mw(ws: Workspace, *, by: str) -> EvidenceItem:
    """Propose phys.mw from the brief's PubChem record (a database value, quoted from the stored record; the person
    accepts it like any other evidence)."""
    from modeler_project.evidence import Extraction, SourceRef, new_id
    from modeler_project.evidence_register import propose

    found = identity_mw(ws)
    if found is None:
        raise ValueError("the brief has no PubChem record with a molecular weight: resolve the drug's identity on the Brief "
                         "page (the generic name, e.g. 'desvenlafaxine'), or add the value on the Literature page")
    item = EvidenceItem(id=new_id(), target="phys.mw", value=found["value"], unit="g/mol", source_type=SourceType.DATABASE,
                        source=SourceRef(doc_sha256=found["doc_sha256"], page=1, locator=f"PubChem CID {found['cid']}",
                                         title=f"PubChem compound record ({found['name']})"),
                        quote=found["quote"], extraction=Extraction.TEXT,
                        note="from the brief's identity record; PubChem gives the molecular weight of the record's form "
                             "(check free base vs salt)")
    return propose(ws, item, actor=by, value_in_quote=True)


def dataset_warnings(observed: list[ObservedDataset]) -> list[str]:
    """What is wrong with the datasets' study records before they are judged on (seen on a real project: two arms
    under one study id, an IV study recorded as oral, oral studies with no food state)."""
    out = []
    by_study: dict[str, list[str]] = defaultdict(list)
    for d in observed:
        by_study[str(d.study.get("study_id"))].append(d.id)
    out += [f"{sid}: {len(ids)} datasets share this study id ({', '.join(ids)}); give each arm its own id, or reject the "
            "duplicates" for sid, ids in by_study.items() if len(ids) > 1]
    out += [f"{d.study.get('study_id')}: oral study without a food state (fasted or fed)" for d in observed
            if d.study.get("route") == "oral" and not d.study.get("food_state")]
    return out


def todo(ws: Workspace) -> list[dict[str, Any]]:
    """What stands between the inputs and readiness, each with what settles it. Computed when read, from the latest
    assembly and readiness, the evidence register and the datasets; nothing here decides anything."""
    from modeler_project.dataset_register import datasets
    from modeler_project.evidence_register import items
    from pbpk_domain.cpf import check_completeness

    cpf_version = ws.latest(ArtifactKind.CPF, MAIN)
    ready = ws.latest(ArtifactKind.READINESS, MAIN)
    if cpf_version is None or ready is None:
        return []
    evidence = {e.id: e for e in items(ws)}
    out: list[dict[str, Any]] = []
    settled_by_issue: set[str] = set()
    for issue in cpf_version.content["assembly"].get("issues", []):
        entry = {**issue, "items": [evidence_view(evidence[i]) for i in issue["evidence"] if i in evidence]}
        if issue["kind"] == "correct":
            entry["suggestions"] = _suggestions(issue["target"])
        out.append(entry)
        # an open issue on a parameter (or on any elimination pathway) is what settles its S0 gap: not listed twice
        settled_by_issue.update({issue["target"], "elim"} if issue["target"].startswith("elim") else {issue["target"]})
    cpf = CPF.model_validate(cpf_version.content["cpf"])
    labels = dict(zip(check_completeness(cpf).missing_ids, check_completeness(cpf).missing, strict=True))
    for target, label in labels.items():
        if target in settled_by_issue:
            continue
        proposed = [evidence_view(e) for e in evidence.values() if included(e)
                    and (e.target == target or e.target.startswith(target + "."))]
        entry: dict[str, Any] = {"kind": "missing", "target": target, "message": f"missing: {label}", "items": proposed}
        if target == "phys.mw":
            entry["identity"] = identity_mw(ws)
        out.append(entry)
    observed = [d for d in datasets(ws) if d.state is not EvidenceState.REJECTED]
    checks = {c["check"]: c for c in ready.content["checks"]}
    warnings = dataset_warnings(observed)
    if not checks.get("observed data to judge on", {"ok": True})["ok"] or warnings:
        out.append({"kind": "datasets", "target": "observed data", "warnings": warnings,
                    "message": "no dataset with a mean profile to judge on" if not checks.get(
                        "observed data to judge on", {"ok": True})["ok"] else "; ".join(warnings),
                    "items": [{"id": d.id, "study_id": d.study.get("study_id"), "purpose": d.purpose, "origin": d.origin.value,
                               "provider": d.provider, "state": d.state.value, "kind": d.kind,
                               "statistics": sorted({s.statistic for s in d.series}), "series": len(d.series)}
                              for d in observed]})
    dataset_of = {str(r["study_id"]): r.get("dataset_id") for r in catalog_rows(ws)}
    for name, kind in (("multiple-dose regimens", "regimen"), ("demographics stated (D-29)", "demographics")):
        check = checks.get(name)
        for detail in (check or {"detail": []})["detail"] if check and not check["ok"] else []:
            sid = detail.split(":", 1)[0]
            out.append({"kind": kind, "target": sid, "message": detail, "items": [], "tab": "studies",
                        "dataset_id": dataset_of.get(sid)})
    formulations = checks.get("formulations of solid studies")
    if formulations and not formulations["ok"]:
        proposed = [evidence_view(e) for e in evidence.values() if e.target.startswith("form.") and included(e)]
        out.append({"kind": "formulation", "target": "form.*", "message": "; ".join(formulations["detail"]), "items": proposed})
    build = checks.get("every planned simulation builds (software)")
    if build and not build["ok"] and not out:
        out.append({"kind": "check", "target": "build", "message": "; ".join(build["detail"]), "items": []})
    return out
