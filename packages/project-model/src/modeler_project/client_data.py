"""Client data (plan §10, P3): workbooks and files from the client, read into datasets and evidence, and reconciled
against what the data plan says the client will provide.

An uploaded file is stored as a document first (the cells become quotable rows), then:

* the client-data template (`modeler_intake.client_template`) is read with no AI: each study arm becomes an observed
  dataset (origin CLIENT, extraction CELL, every series traceable to its rows), each physico-chemical or in vitro row an
  evidence item quoted from its row; dissolution, product and urine/feces rows are kept with their cells for the steps
  that use them (T-48 dissolution, T-49 inputs);
* any other workbook is triaged sheet by sheet (`modeler_intake.triage`); its data are read once a person confirms a
  mapping recipe for a sheet;
* PDF, Word, CSV and Markdown files are documents the literature agents and people read and cite (owner, §3 #15).

Every file is a CLIENT_SUBMISSION artifact. Reconciliation is computed when read: per client item of the data plan,
delivered / partial / missing / not available, and what was delivered that the plan did not promise. The P3 register
(CLIENT_SUBMISSION/register) snapshots it at approval; a missing required item must first be skipped (not available)
or switched to a literature cross-check (owner, R-07).
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import PurePath
from typing import Any

from modeler_intake.client_template import ClientWorkbook, Row, read_client_workbook
from modeler_intake.grid import read_workbook_bytes
from modeler_intake.triage import SheetTriage, triage
from modeler_project.artifacts import ArtifactKind
from modeler_project.brief import ProjectBrief
from modeler_project.datasets import DatasetError, ObservedDataset, Origin, ReportedPK, Series, new_dataset_id
from modeler_project.documents import DocumentLibrary
from modeler_project.evidence import EvidenceItem, EvidenceState, Extraction, SourceRef, SourceType, new_id
from modeler_project.requirements import RequirementItem, RequirementMatrix, _slug, client_items
from modeler_project.workspace import Workspace
from pbpk_domain.issues import Issue

REGISTER = "register"
SPREADSHEETS = (".xlsx", ".xlsm", ".csv")
_STATISTIC = {"arithmetic_mean": "arithmetic_mean", "geometric_mean": "geometric_mean", "median": "median"}
_ERROR_KIND = {"SD": "SD", "SE": "SE", "CV%": "CV%"}
_PROMISED_COUNT = re.compile(r"\b(\d+|two|three|four|five|six)\s+(?:dissolution\s+)?(?:media|medium|buffers?|ph\s+values?|conditions)",
                             re.IGNORECASE)
_NUMBER_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6}


class ClientDataError(ValueError):
    pass


def submission_id(sha256: str) -> str:
    return f"file-{sha256[:12]}"


def submissions(ws: Workspace) -> list[dict[str, Any]]:
    return [v.content | {"id": v.id} for v in ws.list(ArtifactKind.CLIENT_SUBMISSION) if v.id != REGISTER]


# --- reading one file -------------------------------------------------------------------------------------------


def _row_line(library: DocumentLibrary, sha: str, sheet: str, row: int) -> tuple[int | None, str]:
    """The document page and the verbatim line of a sheet row (`[Sheet row N] A1=… | B1=…`), for quoting it."""
    prefix = f"[{sheet} row {row}]"
    for number, text in enumerate(library.pages(sha), start=1):
        for line in text.splitlines():
            if line.startswith(prefix):
                return number, line
    return None, ""


def _arm(row: Row) -> tuple[str, str]:
    return str(row.values.get("study_id", "")), str(row.values.get("treatment") or "")


def _arm_id(study_id: str, treatment: str) -> str:
    return f"{study_id}-{treatment}" if treatment else study_id


def _study_record(row: Row, *, filename: str, n_timepoints: int, statistic: str) -> dict[str, Any]:
    v = row.values
    study_id, treatment = _arm(row)
    record: dict[str, Any] = {
        "study_id": _arm_id(study_id, treatment), "reference": v.get("reference") or filename,
        "population_type": v.get("population", "healthy"), "n": int(v["n"]), "design": v.get("design", "SD"),
        "crossover": v.get("crossover") == "yes", "route": v["route"], "dose_mg": float(v["dose"]),
        "dose_per_kg": v.get("dose_unit") == "mg/kg", "formulation": v.get("formulation", "solution"),
        "food_state": v.get("food_state", "fasted"), "statistic": statistic, "n_timepoints": max(1, n_timepoints),
        "matrices": [v.get("matrix") or "plasma"],
    }
    optional = {"special_population": "special_population", "infusion_time_min": "infusion_time_min",
                "dosing_interval_h": "dosing_interval_h", "meal_type": "meal_type", "co_medication": "co_medication",
                "genotype": "genotype"}
    for key, column in optional.items():
        if v.get(column) is not None:
            record[key] = v[column]
    if v.get("n_doses") is not None:
        record["n_doses"] = int(v["n_doses"])
    return record


def _series_from_summary(rows: list[Row], issues: list[Issue]) -> tuple[list[Series], str, str]:
    by_stat: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        by_stat[r.values["statistic"]].append(r)
    units = {(r.values.get("time_unit"), r.values.get("unit")) for r in rows}
    if len(units) > 1:
        issues.append(Issue("MIXED_UNITS", rows[0].locator, f"one arm reported in several units {sorted(map(str, units))}"))
        return [], "", ""
    time_unit, unit = units.pop()
    out = []
    for stat, group in by_stat.items():
        group = sorted(group, key=lambda r: r.values["time"])
        times = [r.values["time"] for r in group]
        if len(set(times)) != len(times):
            issues.append(Issue("DUPLICATE_TIME", group[0].locator, f"{stat}: a time appears twice"))
            continue
        variability = [r.values.get("variability") for r in group]
        kinds = {r.values.get("variability_kind") for r in group if r.values.get("variability") is not None}
        has_error = all(x is not None for x in variability) and len(kinds) == 1
        n = next((int(r.values["n"]) for r in group if r.values.get("n") is not None), None)
        out.append(Series(name=stat.replace("_", " "), statistic=_STATISTIC[stat], times=tuple(times),
                          values=tuple(r.values.get("value") for r in group),
                          error=tuple(variability) if has_error else None,  # type: ignore[arg-type]
                          error_kind=_ERROR_KIND[kinds.pop()] if has_error else "none", n=n))
    return out, time_unit, unit


def _series_from_individuals(rows: list[Row], issues: list[Issue]) -> tuple[list[Series], str, str]:
    units = {(r.values.get("time_unit"), r.values.get("unit")) for r in rows}
    if len(units) > 1:
        issues.append(Issue("MIXED_UNITS", rows[0].locator, f"one arm reported in several units {sorted(map(str, units))}"))
        return [], "", ""
    time_unit, unit = units.pop()
    by_subject: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        by_subject[str(r.values["subject_id"])].append(r)
    out = []
    for subject, group in sorted(by_subject.items()):
        # actual sampling times when every row has one, else the nominal times
        use_actual = all(r.values.get("actual_time") is not None for r in group)
        key = "actual_time" if use_actual else "nominal_time"
        group = sorted(group, key=lambda r: r.values[key])
        times = [r.values[key] for r in group]
        if len(set(times)) != len(times):
            issues.append(Issue("DUPLICATE_TIME", group[0].locator, f"subject {subject}: a time appears twice"))
            continue
        out.append(Series(name=subject, statistic="individual", times=tuple(times),
                          values=tuple(None if "concentration" in r.below_lloq else r.values.get("concentration") for r in group)))
    return out, time_unit, unit


def _datasets_from_template(read: ClientWorkbook, *, library: DocumentLibrary, sha: str, filename: str,
                            issues: list[Issue]) -> list[ObservedDataset]:
    studies = {_arm(r): r for r in read.sheet("Studies")}
    pk: dict[str, dict[tuple[str, str], list[Row]]] = {name: defaultdict(list) for name in
                                                       ("PK_Summary", "PK_Individual", "PK_Parameters")}
    for name, by_arm in pk.items():
        for r in read.sheet(name):
            if "study_id" in r.values:
                by_arm[_arm(r)].append(r)
    arms = sorted({arm for by_arm in pk.values() for arm in by_arm})
    out = []
    for arm in arms:
        study = studies.get(arm)
        first = next(rows[0] for by_arm in pk.values() if (rows := by_arm.get(arm)))
        if study is None:
            issues.append(Issue("UNKNOWN_STUDY", first.locator,
                                f"study {_arm_id(*arm)} has PK rows but no row on the Studies sheet; it is not read"))
            continue
        if any(study.values.get(k) is None for k in ("n", "route", "dose")):
            issues.append(Issue("INCOMPLETE_STUDY", study.locator, f"study {_arm_id(*arm)}: n, route and dose are required"))
            continue
        series: list[Series] = []
        time_unit = unit = ""
        if pk["PK_Individual"].get(arm):
            series, time_unit, unit = _series_from_individuals(pk["PK_Individual"][arm], issues)
        if pk["PK_Summary"].get(arm):
            summary, t_unit, c_unit = _series_from_summary(pk["PK_Summary"][arm], issues)
            if series and summary and (t_unit, c_unit) != (time_unit, unit):
                issues.append(Issue("MIXED_UNITS", pk["PK_Summary"][arm][0].locator,
                                    f"study {_arm_id(*arm)}: summary and individual rows in different units"))
            elif summary:
                series, time_unit, unit = series + summary, t_unit, c_unit
        reported = tuple(ReportedPK(parameter=r.values["parameter"], value=r.values["value"], unit=r.values["unit"],
                                    statistic=r.values.get("statistic", "arithmetic_mean"),
                                    variability=(f"{r.values['variability']} {r.values.get('variability_kind', '')}".strip()
                                                 if r.values.get("variability") is not None else ""))
                         for r in pk["PK_Parameters"].get(arm, []) if "value" in r.values and "parameter" in r.values)
        if not series and not reported:
            continue
        individual = any(s.statistic == "individual" for s in series)
        has_sd = any(s.error_kind != "none" for s in series)
        record = _study_record(study, filename=filename, n_timepoints=max((len(s.times) for s in series), default=1),
                               statistic="individual" if individual else "mean_sd" if has_sd else "mean")
        lloq = study.values.get("lloq")
        if lloq is not None:
            if study.values.get("lloq_unit") in (None, unit):
                record["lloq"] = lloq
            else:
                issues.append(Issue("LLOQ_UNIT", study.cells.get("lloq_unit", study.locator),
                                    f"LLOQ in {study.values.get('lloq_unit')}, data in {unit}: not converted, give it in {unit}"))
        page, line = _row_line(library, sha, first.sheet, first.row)
        rows_used = [r for by_arm in pk.values() for r in by_arm.get(arm, [])]
        locator = f"{study.locator}; " + "; ".join(f"{s}!{min(r.row for r in rows_used if r.sheet == s)}:"
                                                   f"{max(r.row for r in rows_used if r.sheet == s)}"
                                                   for s in sorted({r.sheet for r in rows_used}))
        out.append(ObservedDataset(
            id=new_dataset_id(), kind="profile" if series else "pk_parameters", study=record,
            analyte=study.values.get("analyte") or "parent", matrix=study.values.get("matrix") or "plasma",
            time_unit=time_unit or "h", unit=unit or (reported[0].unit.partition("*")[0] if reported else "ng/ml"),
            series=tuple(series), reported=reported, origin=Origin.CLIENT, extraction="CELL",
            source=SourceRef(doc_sha256=sha, page=page, locator=locator, title=filename), quote=line,
            purpose=study.values.get("intended_use") or "model_building", provider="CLIENT",
            note="; ".join(f"{k} {study.values[k]}" for k in ("product", "product_role", "batch", "strength_mg",
                                                               "age_mean", "weight_mean_kg", "percent_female",
                                                               "ethnicity", "salt_or_base") if study.values.get(k) is not None),
        ))
    return out


def _requirement_for(parameter: str, matrix: RequirementMatrix | None) -> RequirementItem | None:
    """The data-plan item a client row names: by its id, label or target exactly, else the most specific target that
    the parameter id falls under (``elim.hepatic.CYP3A4.clint`` under ``elim``)."""
    if matrix is None:
        return None
    key = parameter.strip().lower()
    exact = next((i for i in matrix.items if key in (i.target.lower(), i.label.lower(), i.req_id.lower())), None)
    if exact is not None:
        return exact
    under = [(len(base), i) for i in matrix.items if (base := i.target.split("{", 1)[0].rstrip(".").lower())
             and key.startswith(base + ".")]
    return max(under, key=lambda t: t[0])[1] if under else None


def _evidence_from_template(read: ClientWorkbook, *, library: DocumentLibrary, sha: str, filename: str,
                            matrix: RequirementMatrix | None, issues: list[Issue]) -> list[tuple[EvidenceItem, RequirementItem | None]]:
    out = []
    for r in read.sheet("Physchem_InVitro"):
        if "parameter" not in r.values or "value" not in r.values:
            continue
        parameter = str(r.values["parameter"]).strip()
        requirement = _requirement_for(parameter, matrix)
        # a parameter id is kept as given; a data-plan name stands for its item's target when that is one parameter
        target = parameter if "." in parameter else (requirement.target if requirement and "{" not in requirement.target else "")
        if not target:
            issues.append(Issue("UNKNOWN_PARAMETER", r.cells["parameter"],
                                f"{parameter!r} is neither a parameter id nor the name of a single data-plan parameter"))
            continue
        page, line = _row_line(library, sha, r.sheet, r.row)
        conditions = {k: str(r.values[k]) for k in ("conditions", "method") if r.values.get(k)}
        out.append((EvidenceItem(
            id=new_id(), req_id=requirement.req_id if requirement else None, target=target, value=r.values["value"],
            unit=r.values.get("unit"), source_type=SourceType.CLIENT_FILE,
            source=SourceRef(doc_sha256=sha, page=page, locator=r.locator, title=filename), quote=line,
            extraction=Extraction.CELL, conditions=conditions, provider="CLIENT",
            note=f"report {r.values['report_reference']}" if r.values.get("report_reference") else "",
        ), requirement))
    return out


def _kept_rows(read: ClientWorkbook, sheet: str) -> list[dict[str, Any]]:
    return [{"row": r.row, "values": r.values, "cells": r.cells, "below_lloq": sorted(r.below_lloq)} for r in read.sheet(sheet)]


def _brief_mismatches(read: ClientWorkbook, brief: ProjectBrief | None) -> list[str]:
    """Doses and products in the client file that the brief does not mention (plan §10.1 step 7): questions, not errors."""
    if brief is None:
        return []
    doses = {float(d.value) for item in brief.groups.get("scenarios", ()) if (d := item.get("dose")) is not None
             and isinstance(d.value, int | float)}
    products = {str(p.value).strip().lower() for item in brief.groups.get("products", ()) if (p := item.get("name")) is not None
                and p.value}
    out = []
    for r in read.sheet("Studies"):
        dose = r.values.get("dose")
        if doses and dose is not None and r.values.get("dose_unit") == "mg" and float(dose) not in doses:
            out.append(f"{r.cells['dose']}: dose {dose:g} mg is not a dose of the brief's scenarios "
                       f"({', '.join(f'{d:g}' for d in sorted(doses))} mg)")
    for sheet in ("Studies", "Product", "Dissolution"):
        for r in read.sheet(sheet):
            name = r.values.get("product")
            if products and name and str(name).strip().lower() not in products:
                out.append(f"{r.cells['product']}: product {name!r} is not one of the brief's products")
    return list(dict.fromkeys(out))


def ingest(ws: Workspace, library: DocumentLibrary, data: bytes, filename: str, *, by: str,
           matrix: RequirementMatrix | None = None, brief: ProjectBrief | None = None) -> dict[str, Any]:
    """Store one client file and read what can be read without a person's mapping. Uploading the same bytes again
    returns the earlier submission unchanged."""
    from modeler_project.dataset_register import propose_dataset
    from modeler_project.evidence_register import propose

    doc = library.add(data, filename, role="client_file", by=by)
    sha = doc.content["sha256"]
    sid = submission_id(sha)
    existing = ws.latest(ArtifactKind.CLIENT_SUBMISSION, sid)
    if existing is not None:
        return existing.content | {"id": sid, "repeat": True}
    content: dict[str, Any] = {"file": PurePath(filename).name, "sha256": sha, "kind": doc.content["kind"],
                               "template": False, "triage": [], "datasets": [], "evidence": [], "dissolution": [],
                               "products": [], "urine_feces": [], "studies": [], "issues": [], "brief_mismatches": [],
                               "other_sheets": [], "mappings": []}
    if PurePath(filename).suffix.lower() in SPREADSHEETS:
        workbook = read_workbook_bytes(data, filename)
        content["triage"] = [t.to_content() for t in triage(workbook)]
        read = read_client_workbook(workbook)
        if read.template:
            issues = list(read.issues)
            for dataset in _datasets_from_template(read, library=library, sha=sha, filename=content["file"], issues=issues):
                try:
                    content["datasets"].append(propose_dataset(ws, dataset, actor=by).id)
                except DatasetError as exc:
                    issues.append(Issue("DATASET_REFUSED", dataset.source.locator, f"{dataset.study['study_id']}: {exc}"))
            for item, requirement in _evidence_from_template(read, library=library, sha=sha, filename=content["file"],
                                                             matrix=matrix, issues=issues):
                content["evidence"].append(propose(ws, item, actor=by, requirement=requirement, value_in_quote=True).id)
            content.update(template=True, dissolution=_kept_rows(read, "Dissolution"), products=_kept_rows(read, "Product"),
                           urine_feces=_kept_rows(read, "Urine_Feces"), studies=_kept_rows(read, "Studies"),
                           brief_mismatches=_brief_mismatches(read, brief), other_sheets=read.other_sheets)
            content["issues"] = [asdict(i) for i in issues]
    ws.commit(ArtifactKind.CLIENT_SUBMISSION, sid, content, derived_from=[doc.ref], actor=by,
              reason=f"client file {content['file']}" + (" (template)" if content["template"] else ""))
    if content["dissolution"]:
        from modeler_project.dissolution_register import rebuild

        rebuild(ws, by=by)
    return content | {"id": sid}


def set_triage(ws: Workspace, sid: str, triaged: SheetTriage, *, by: str, reason: str) -> dict[str, Any]:
    """A person's (or agent A4's checked) classification of one sheet replaces the earlier one."""
    version = ws.latest(ArtifactKind.CLIENT_SUBMISSION, sid)
    if version is None:
        raise ClientDataError(f"no client file {sid}")
    rows = [t for t in version.content["triage"] if t["sheet"] != triaged.sheet] + [triaged.to_content()]
    content = {**version.content, "triage": sorted(rows, key=lambda t: t["sheet"])}
    ws.commit(ArtifactKind.CLIENT_SUBMISSION, sid, content, actor=by, reason=f"{triaged.sheet}: {triaged.category.value} ({reason})")
    return content | {"id": sid}


def datasets_from_observations(observations: list[Any], *, study: dict[str, Any], sha: str, filename: str,
                               library: DocumentLibrary) -> list[ObservedDataset]:
    """Datasets from the concentration records of a confirmed mapping recipe (`modeler_intake.apply`): one per study id,
    one series per subject / group. What the sheet does not state about the study (n, design, population …) comes from
    `study`, which a person filled in; the recipe's constants (dose, route, formulation, food state) take precedence."""
    by_study: dict[str, list[Any]] = defaultdict(list)
    for o in observations:
        by_study[o.study_id].append(o)
    out = []
    for study_id, records in sorted(by_study.items()):
        units = {(o.time_unit, o.unit) for o in records}
        if len(units) > 1:
            raise ClientDataError(f"{study_id}: records in several units {sorted(units)}")
        time_unit, unit = units.pop()
        by_series: dict[str, list[Any]] = defaultdict(list)
        for o in records:
            by_series[o.series].append(o)
        series = []
        for name, group in sorted(by_series.items()):
            group = sorted(group, key=lambda o: o.time)
            sds = [o.sd for o in group]
            series.append(Series(name=name, statistic=group[0].statistic, times=tuple(o.time for o in group),
                                 values=tuple(None if o.below_lloq else o.value for o in group),
                                 error=tuple(sds) if all(x is not None for x in sds) else None,  # type: ignore[arg-type]
                                 error_kind="SD" if all(x is not None for x in sds) else "none",
                                 n=next((o.n for o in group if o.n is not None), None)))
        first = records[0]
        # what the study is for is the dataset's, not the study record's (MS-01 §3.3 classes read the record)
        record = {**{k: v for k, v in study.items() if k != "purpose"}, "study_id": study_id,
                  "n_timepoints": max(len(s.times) for s in series),
                  "statistic": "individual" if first.statistic == "individual" else "mean_sd" if series[0].error else "mean"}
        for key, value in (("dose_mg", first.dose), ("route", first.route), ("formulation", first.formulation),
                           ("food_state", first.food_state), ("lloq", first.lloq)):
            if value is not None:
                record[key] = value
        sheet, _, cell = first.source.cells["value"].partition("!")
        row = int("".join(ch for ch in cell if ch.isdigit()) or 0)
        page, line = _row_line(library, sha, sheet, row)
        out.append(ObservedDataset(
            id=new_dataset_id(), kind="profile", study=record, analyte=first.analyte or "parent", matrix=first.matrix or "plasma",
            time_unit=time_unit, unit=unit, series=tuple(series), origin=Origin.CLIENT, extraction="CELL",
            source=SourceRef(doc_sha256=sha, page=page, locator=f"{sheet} (recipe {first.source.recipe_id} v{first.source.recipe_version})",
                             title=filename),
            quote=line, purpose=str(study.get("purpose") or "model_building"), provider="CLIENT"))
    return out


def record_mapping(ws: Workspace, sid: str, *, recipe: dict[str, Any], dataset_ids: list[str],
                   dissolution: list[dict[str, Any]], by: str) -> dict[str, Any]:
    """Keep the confirmed recipe (re-used for the same layout) and what it produced on the client file's record."""
    version = ws.latest(ArtifactKind.CLIENT_SUBMISSION, sid)
    if version is None:
        raise ClientDataError(f"no client file {sid}")
    content = dict(version.content)
    content["mappings"] = [*content.get("mappings", []), {"recipe": recipe, "datasets": dataset_ids,
                                                          "dissolution_records": len(dissolution)}]
    content["datasets"] = [*content.get("datasets", []), *dataset_ids]
    content["dissolution_records"] = [*content.get("dissolution_records", []), *dissolution]
    ws.commit(ArtifactKind.CLIENT_SUBMISSION, sid, content, actor=by,
              reason=f"mapping recipe {recipe.get('recipe_id')} confirmed: {len(dataset_ids)} datasets")
    if dissolution:
        from modeler_project.dissolution_register import rebuild

        rebuild(ws, by=by)
    return content | {"id": sid}


# --- reconciliation (plan §10.1 step 6) ------------------------------------------------------------------------


@dataclass(frozen=True)
class Reconciled:
    req_id: str
    label: str
    criticality: str
    applies: str
    status: str            # DELIVERED | PARTIAL | MISSING | NOT_AVAILABLE | WAIVED
    delivered: tuple[str, ...] = ()
    detail: str = ""
    cross_check: bool = False
    literature_accepted: tuple[str, ...] = ()


@dataclass
class Reconciliation:
    rows: list[Reconciled] = field(default_factory=list)
    unpromised: list[str] = field(default_factory=list)

    def blocking(self) -> list[Reconciled]:
        """Required, applicable client items with nothing delivered and no decision (skip, or a literature cross-check
        that found accepted evidence): the P3 gate."""
        return [r for r in self.rows if r.criticality == "REQUIRED" and r.applies == "yes" and r.status == "MISSING"
                and not (r.cross_check and r.literature_accepted)]

    def to_content(self) -> dict[str, Any]:
        return {"rows": [asdict(r) for r in self.rows], "unpromised": self.unpromised,
                "blocking": [r.req_id for r in self.blocking()]}


def _dissolution_rows(subs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every delivered dissolution row: the client-data template's rows and the records of confirmed mapping recipes."""
    return [v for sub in subs for v in [*(row["values"] for row in sub.get("dissolution", [])), *sub.get("dissolution_records", [])]]


def _dissolution_keys(rows: list[dict[str, Any]], product: str | None) -> set[tuple[str, str, str]]:
    """(role, medium, pH) of the rows for `product` (any product when None); names compare as the data plan's slugs."""
    keys = set()
    for v in rows:
        name = str(v.get("product") or "").strip()
        if product is None or (name and _slug(name) == _slug(product)):
            ph = v.get("ph")
            keys.add((str(v.get("role") or "").strip().upper(), str(v.get("medium") or ""), "" if ph is None else f"{float(ph):g}"))
    return keys


def _test_vs_reference(keys: set[tuple[str, str, str]]) -> tuple[tuple[str, ...], str]:
    """REQ-vbe.rld_dissolution: media in which a TEST and an RLD / REFERENCE profile were both delivered."""
    def media(roles: tuple[str, ...]) -> set[tuple[str, str]]:
        return {(m, p) for r, m, p in keys if r in roles}
    both = media(("TEST",)) & media(("RLD", "REFERENCE"))
    if both:
        return tuple(sorted(f"{m} pH {p}" if p else m for m, p in both)), ""
    roles = sorted({r or "no role" for r, _m, _p in keys})
    return (), (f"profiles delivered ({', '.join(roles)}) but no TEST and RLD / REFERENCE pair in the same medium; name each "
                "profile's product and role in the mapping recipe" if keys else "")


def reconcile(ws: Workspace, matrix: RequirementMatrix) -> Reconciliation:
    from modeler_project.dataset_register import dataset_matches, datasets
    from modeler_project.evidence_register import _matches, items

    subs = submissions(ws)
    client_ds = [d for d in datasets(ws) if d.provider == "CLIENT" and d.state is not EvidenceState.REJECTED]
    evidence = [e for e in items(ws) if e.state is not EvidenceState.REJECTED]
    client_ev = [e for e in evidence if e.provider == "CLIENT"]
    used_ds: set[str] = set()
    used_ev: set[str] = set()
    used_diss = False
    result = Reconciliation()
    diss_rows = _dissolution_rows(subs)
    for item in client_items(matrix):
        detail, delivered, partial = "", (), False
        if item.data_category == "dissolution" and item.target == "dissolution":
            delivered, detail = _test_vs_reference(_dissolution_keys(diss_rows, item.product))
            used_diss = used_diss or bool(delivered)
            partial = bool(detail)
        elif item.kind == "dataset":
            if item.target == "urine":
                delivered = tuple(f"{s['file']}: {len(s.get('urine_feces', []))} urine/feces rows" for s in subs if s.get("urine_feces"))
            else:
                mine = [d for d in client_ds if dataset_matches(item, d)]
                used_ds.update(d.id for d in mine)
                delivered = tuple(d.id for d in mine)
        elif item.kind == "formulation" or item.data_category == "dissolution":
            media = {(m, p) for _r, m, p in _dissolution_keys(diss_rows, item.product)}
            used_diss = used_diss or bool(media)
            # a release model proposed from a client profile (form.<name>.*) serves this item
            used_ev.update(e.id for e in client_ev if e.target.startswith("form."))
            delivered = tuple(sorted(f"{m} pH {p}" if p else m for m, p in media))
            promised = _PROMISED_COUNT.search(item.provider_statement or "")
            count = (_NUMBER_WORDS.get(promised.group(1).lower()) or int(promised.group(1))) if promised else 0
            if media and len(media) < count:
                detail, partial = f"{len(media)} of {count} promised media ({item.provider_statement!r})", True
            elif not media and item.product and diss_rows:
                named = sorted({str(v.get("product") or "") for v in diss_rows} - {""})
                detail = (f"dissolution delivered for {', '.join(repr(n) for n in named)}, not for {item.product!r}: name the "
                          "product as the brief does" if named else "dissolution delivered without a product name: name the "
                          "product in the mapping recipe")
        else:
            mine_ev = [e for e in client_ev if _matches(item, e)]
            used_ev.update(e.id for e in mine_ev)
            delivered = tuple(e.id for e in mine_ev)
        if item.status in ("NOT_AVAILABLE", "WAIVED"):
            status = item.status
        elif partial:
            status = "PARTIAL"
        elif delivered:
            status = "DELIVERED"
        else:
            status = "MISSING"
        literature = tuple(e.id for e in evidence if e.provider == "LITERATURE" and e.state is EvidenceState.ACCEPTED
                           and _matches(item, e)) if item.cross_check else ()
        result.rows.append(Reconciled(req_id=item.req_id, label=item.label, criticality=item.criticality,
                                      applies=item.applies, status=status, delivered=delivered, detail=detail,
                                      cross_check=item.cross_check, literature_accepted=literature))
    for d in client_ds:
        if d.id not in used_ds:
            result.unpromised.append(f"dataset {d.study.get('study_id')} ({d.id}): delivered, not promised by the data plan")
    for e in client_ev:
        if e.id not in used_ev:
            result.unpromised.append(f"{e.target} = {e.value} {e.unit or ''} ({e.id}): delivered, not promised".replace("  ", " "))
    if not used_diss and diss_rows:
        result.unpromised.append("dissolution profiles: delivered, not promised by the data plan")
    return result


def close_register(ws: Workspace, matrix_ref, matrix: RequirementMatrix, *, by: str, note: str = "",
                   printed_name: str = "") -> None:
    """Snapshot the client files and the reconciliation and approve them (named approval, D-07): the P3 gate."""
    recon = reconcile(ws, matrix)
    gaps = recon.blocking()
    if gaps:
        raise ClientDataError("required client items still missing (skip them as not available, or switch on the literature "
                              "cross-check): " + ", ".join(r.req_id for r in gaps))
    files = [v for v in ws.list(ArtifactKind.CLIENT_SUBMISSION) if v.id != REGISTER]
    content = {"files": [v.ref.model_dump(mode="json") for v in files], "reconciliation": recon.to_content()}
    version = ws.commit(ArtifactKind.CLIENT_SUBMISSION, REGISTER, content, derived_from=[matrix_ref, *[v.ref for v in files]],
                        actor=by, reason="client data reconciled")
    ws.approve(version.ref, by=by, printed_name=printed_name, meaning="Reviewed", note=note)
