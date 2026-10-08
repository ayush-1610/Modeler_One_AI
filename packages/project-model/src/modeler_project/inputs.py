"""P4 model inputs (plan §5.2 P4, T-49): CPF v1 from the accepted evidence, the study catalog from the accepted
datasets, and the readiness of both for PK-Sim.

The CPF is regenerated from the evidence every time (CLAUDE.md: the CPF is the system of record, every simulation is
regenerated from it): one record per accepted evidence item, its value in the PK-Sim unit, its provenance carried into
PK-Sim's ``ValueOrigin`` (Source and Method from the harvested enums only; the citation, locator, grade and the
evidence id in the description). Two accepted values for one parameter are not averaged or chosen between: the
parameter is left out and named. A process parameter is bound to the PK-Sim process that carries it; when the
harvested table offers several (``CLspec/[Enzyme]`` on two process types), a person chooses (``InputChoices``).

Readiness is the S0 gate (completeness, placeable pathways, expression profiles) plus what P4 adds: every solid study
names a formulation the CPF defines, the MS-01 split has studies to train on, the observed data's origins, and a build
of every planned simulation with the software builder. Loading the snapshots into PK-Sim (the engine dry run) needs the
engine and is done on the server. The inputs are accepted by name when ready (no signature: the MAP signature in P5
covers them).
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from modeler_project.artifacts import ArtifactKind, ArtifactVersion
from modeler_project.brief import ProjectBrief
from modeler_project.datasets import ObservedDataset
from modeler_project.evidence import EvidenceItem, EvidenceState, SourceType, numeric_target, review_flags
from modeler_project.workspace import Workspace
from pbpk_domain import parameters
from pbpk_domain.cpf.models import CPF, ParameterRecord, ParameterStatus, Provenance
from pbpk_domain.cpf.process_bindings import binding_candidates, is_process_id
from pbpk_domain.data_origin import REAL_ORIGINS

MAIN = "main"
CHOICES = "choices"
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


def _accepted(ws: Workspace) -> list[tuple[EvidenceItem, ArtifactVersion]]:
    out = []
    for version in ws.list(ArtifactKind.EVIDENCE):
        if not version.id.startswith("ev-"):
            continue
        item = EvidenceItem.from_content(version.content)
        if item.state is EvidenceState.ACCEPTED:
            out.append((item, version))
    return out


def _issue(issues: list[dict[str, Any]], problems: list[str], kind: str, target: str, evidence: list[str], message: str) -> None:
    """One assembly problem: in words (the readiness report) and typed (what settles it on the page)."""
    problems.append(message)
    issues.append({"kind": kind, "target": target, "evidence": evidence, "message": message})


def _cpf_id(item: EvidenceItem, pka_index: dict[str, int], problems: list[str], issues: list[dict[str, Any]]) -> str | None:
    target = item.target
    if "{" in target or "<" in target:
        _issue(issues, problems, "correct", target, [item.id], f"{item.id}: target {target} is a template; give the concrete parameter")
        return None
    if target == "phys.halogens":
        _issue(issues, problems, "correct", target, [item.id], f"{item.id}: give one value per atom (phys.halogens.F, .Cl, .Br, .I)")
        return None
    if target == "phys.pka":
        if isinstance(item.value, str) and item.value.strip().lower() == "neutral":
            return "phys.pka.neutral"
        text = " ".join(f"{k} {v}" for k, v in item.conditions.items()).lower()
        kinds = [k for k in ("acid", "base") if k in text]
        if len(kinds) != 1:
            _issue(issues, problems, "pka", target, [item.id], f"{item.id}: pKa {item.value} — the conditions must say acid or base")
            return None
        index = pka_index[kinds[0]]
        pka_index[kinds[0]] += 1
        return f"phys.pka.{kinds[0]}.{index}"
    if isinstance(item.value, str) and numeric_target(target):
        _issue(issues, problems, "correct", target, [item.id],
               f"{item.id}: {item.value[:80]!r} is a description, not a value for {target}: give the number it states (and "
               "the parameter), or reject it (kept out of the CPF)")
        return None
    if not is_process_id(target) and placement(target) is None:
        what = PLACEHOLDERS.get(target)
        _issue(issues, problems, "correct", target, [item.id],
               f"{item.id}: {target!r} " + (f"means {what}" if what else "is not a parameter the model uses: correct its "
                                                                        "target or reject it") + " (kept out of the CPF)")
        return None
    return target


def assemble_cpf(ws: Workspace, compound: str, picked: InputChoices) -> tuple[CPF, dict[str, Any], list[ArtifactVersion]]:
    """CPF v1 from the accepted evidence: (cpf, report, the evidence versions used)."""
    problems: list[str] = []
    issues: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    by_id: dict[str, list[tuple[EvidenceItem, ArtifactVersion]]] = defaultdict(list)
    pka_index: dict[str, int] = defaultdict(int)
    for item, version in sorted(_accepted(ws), key=lambda iv: (iv[0].target, iv[0].proposed_at)):
        cpf_id = _cpf_id(item, pka_index, problems, issues)
        if cpf_id:
            by_id[cpf_id].append((item, version))
    records, used = [], []
    for cpf_id, accepted in sorted(by_id.items()):
        if len(accepted) > 1:
            _issue(issues, problems, "conflict", cpf_id, [i.id for i, _v in accepted],
                   f"{cpf_id}: {len(accepted)} accepted values ({', '.join(i.id for i, _v in accepted)}); "
                   "reject all but one — values are never averaged or chosen between by code")
            continue
        item, version = accepted[0]
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
        status = ParameterStatus.PREDICTED if item.source_type is SourceType.PREDICTED else ParameterStatus.FIXED
        records.append(ParameterRecord(id=cpf_id, value=value, unit=unit, status=status,
                                       provenance=provenance_for(item, version.version), engine_binding=binding))
        used.append(version)
    cpf = CPF(compound=compound, parameters=tuple(records))
    return cpf, {"problems": problems, "issues": issues, "bindings": bindings, "records": len(records)}, used


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


def study_catalog(ws: Workspace, picked: InputChoices) -> tuple[list[dict[str, Any]], list[str], list[ArtifactVersion]]:
    """One row per accepted dataset, in the study-upload shape the campaign path reads: (rows, notes, versions)."""
    rows, notes, used = [], [], []
    seen: dict[str, str] = {}
    for version in sorted(ws.list(ArtifactKind.DATASET), key=lambda v: v.created_at):
        dataset = ObservedDataset.from_content(version.content)
        if dataset.state is not EvidenceState.ACCEPTED:
            continue
        study = dict(dataset.study)
        sid = study["study_id"]
        if sid in picked.excluded_studies:
            notes.append(f"{sid}: left out ({picked.excluded_studies[sid]})")
            continue
        if sid in seen:
            notes.append(f"{sid}: also in {seen[sid]}; {dataset.id} is not used (two accepted datasets for one study)")
            continue
        seen[sid] = dataset.id
        profile = _profile(dataset)
        row: dict[str, Any] = {**study, "origin": dataset.origin.value, "dataset_id": dataset.id,
                               "purpose": dataset.purpose, "evaluable": profile is not None}
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
    evaluable = [r for r in rows if r.get("evaluable")]
    not_real = [f"{r['study_id']} ({r['origin'].lower()})" for r in evaluable if r["origin"] not in {o.value for o in REAL_ORIGINS}]
    checks.append(_check("observed data to judge on", bool(evaluable), [] if evaluable else ["no accepted dataset with a profile"]))
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
                            reason=f"assembled from {len(evidence_used)} accepted evidence items")
    catalog_version = ws.commit(ArtifactKind.STUDY_CATALOG, MAIN, {"studies": rows, "notes": notes},
                                derived_from=[*([picked_version.ref] if picked_version else []), *[v.ref for v in datasets_used]],
                                actor=by, reason=f"{len(rows)} studies from accepted datasets")
    result = readiness(cpf, rows, report, brief)
    ready_version = ws.commit(ArtifactKind.READINESS, MAIN, result, derived_from=[cpf_version.ref, catalog_version.ref],
                              actor=by, reason="ready" if result["ready"] else "not ready")
    return {"cpf": cpf_version, "catalog": catalog_version, "readiness": ready_version}


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
        proposed = [evidence_view(e) for e in evidence.values() if e.state is EvidenceState.PROPOSED
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
                    "message": "no accepted dataset with a mean profile to judge on" if not checks.get(
                        "observed data to judge on", {"ok": True})["ok"] else "; ".join(warnings),
                    "items": [{"id": d.id, "study_id": d.study.get("study_id"), "purpose": d.purpose, "origin": d.origin.value,
                               "provider": d.provider, "state": d.state.value, "kind": d.kind,
                               "statistics": sorted({s.statistic for s in d.series}), "series": len(d.series)}
                              for d in observed]})
    formulations = checks.get("formulations of solid studies")
    if formulations and not formulations["ok"]:
        proposed = [evidence_view(e) for e in evidence.values() if e.target.startswith("form.") and e.state is EvidenceState.PROPOSED]
        out.append({"kind": "formulation", "target": "form.*", "message": "; ".join(formulations["detail"]), "items": proposed})
    build = checks.get("every planned simulation builds (software)")
    if build and not build["ok"] and not out:
        out.append({"kind": "check", "target": "build", "message": "; ".join(build["detail"]), "items": []})
    return out
