"""What a signed Delivery confirmation lands (contracts §6.6, decision I; plan G6): the subject's datasets, its
dissolution rows and its compound and product evidence, each written by its owner module.

The ledger keeps every value as written (decision I: nothing refused, nothing renamed). The landing writes only what the
model's code accepts and holds the rest back, listed with its reason, while the rest of the subject lands (§11.23):

- **concentration values** of one (arm, analyte, matrix): one `ObservedDataset`, origin and provider CLIENT, extraction
  CELL (sheets) or TABLE (PDF, Word), purpose the study's `intended_use`, its `study` the `StudyRecord` the facts give
  (`study_id` the study's label, or `<label>-<arm>` when its values name several arms, as `client_data._arm_id`
  writes it); series: individuals by subject, then one per statistic. Held back: a unit `pbpk_domain.units` does not
  know, a negative value, more than one occasion (`OCCASIONS_NOT_LANDED`, §11.27), two or more LLOQs with no person's
  `lloq` entry, a time unit outside `validate.TIME_UNITS`. A time unit lands as `min`, `h` or `day` (the three that
  `inputs` and `dissolution` read); the actual times when every point of a series has one, else the nominal, named in
  the note. A BLQ point is None with the LLOQ in the study record (today's rule, D1a names it). n per time is
  `Series.n_at`;
- **spreads** by the rules' `landing.spreads_landed` (an arithmetic mean's SD, SE or CV%; a geometric mean's geoSD as
  SD): every other pair lands no error, stays in the ledger and is named in the note. A spread of no stated kind
  (`SPREAD_KIND_MISSING`) is held back. Intervals (CI, range) land nothing (a `Series` has none) and are named;
- **the dose**: in mg as written; in g or µg the ledger's derived mg fact (`compute-1/dose_to_mg`, always verified with
  its input); mg/kg as `dose_mg` with `dose_per_kg`. A dose unit outside the mass table holds its arm back;
- **cross-file values** (a profile's value, a reported parameter, or a fact the study record was read from, joined
  from another file): the dataset's `flags` gain `cross_file: <file> via <link>` (D1a's `check_dataset` keeps it) and
  the note names it;
- **PK parameters**: `reported`, the unit as written; one subject's parameter names its subject in its statistic
  ("individual (subject 001)") and stands before the summary statistics;
- **dissolution** (a product): template-shaped rows through `client_data.record_delivery_rows` (tag
  `delivery-<cf id>`), so the register rebuilds (`profiles_from_rows` keeps a summary's SD and n). Held back: two runs
  whose `ProfileKey` is equal while their temperature or surfactant differ (`DISSOLUTION_RUNS_NOT_KEYED`), and a file
  with no client-file record (today's `ingest` refused it, §11.13);
- **compound and product evidence** (a CPF id field): `evidence_register.propose(value_in_quote=True)`, then
  `decide(ACCEPTED)`; an item `evidence.assess` flags with a hold flag of `source_selection.yaml` stays PROPOSED for a
  person and is listed;
- excretion, product attributes other than dissolution, relations, and a study's facts that the study record has
  no field for land nothing (§11.8, §11.28, §11.33): listed.

`plan_landing` builds and checks all of it (`check_dataset`, `StudyRecord`, `evidence.assess`) and writes nothing; a
`StudyRecord` field the facts do not give is a `LandingError` that names it, so the confirmation is refused before it
is signed. `land` writes the plan, idempotently: what already exists is skipped, a second land of the same confirmation
writes nothing, and each dataset's note and decision reason name the confirmation. What an earlier confirmation of the
subject landed and the new one does not (a correction changed the values) is rejected with the reason, the subject
followed through merges and the `supersedes` chain; a dataset both bind (the same values, so the same id) is decided
again under the later one, and written again by the register when the later plan gives it other content (the study's
label after a merge, a spread the rules no longer land). `land` writes a plan only under a confirmation that bound the
plan's subject in the plan's state (its digest), and takes a version another landing of the same confirmation wrote
first as that landing's work.

Nothing is loaded twice (§2). Overlap with a legacy client dataset is decided by source, never by name
(`legacy_overlap`): it comes from a file the subject's values come from, from one of the bound sheets (a recipe of that
file's submission naming the sheet lists it) or pages, and either its study key equals the subject's label key or one
of its points is a bound value of that sheet or page (the same time in minutes and the same number). `land` rejects the
still proposed ones and records a Delivery recipe on each file, so `sheet_intake` counts the sheets as read. A
dissolution reading of the client-review card is replaced only when every profile it holds is landed here (listed);
one that holds a landed profile together with others is not replaced, and that run is held back (listed).

Held-back reasons and notes name no value, LLOQ or count of the subject's values: a blinded study's (D-15) card shows
them too.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from modeler_intake.anchors import AnchorError, DocxCell, SheetCell, format_locator, parse_anchor
from modeler_intake.client_template import FORMULATIONS, ROUTES, USES
from modeler_intake.fields import field as field_def
from modeler_intake.fields import known_unit, read_choice
from modeler_intake.validate import TIME_UNITS, canonical_unit
from modeler_project import client_data
from modeler_project.dataset_register import dataset, datasets, decide_dataset, propose_dataset, revise_dataset
from modeler_project.datasets import DatasetError, ObservedDataset, Origin, ReportedPK, Series, check_dataset
from modeler_project.documents import DocumentLibrary
from modeler_project.evidence import EvidenceItem, EvidenceState, Extraction, SourceRef, SourceType, assess
from modeler_project.intake_records import Confirmation, FileRecord, Landed
from modeler_project.intake_rules import IntakeRules
from modeler_project.intake_rules import rules as load_rules
from modeler_project.intake_store import ChainEntry, IntakeStore
from modeler_project.ledger_entities import label_key
from modeler_project.ledger_models import ValueState
from modeler_project.ledger_view import LedgerReader, LedgerView, is_compound_field
from modeler_project.requirements import RequirementMatrix
from modeler_project.sources import rule as selection_rule
from modeler_project.store import ImmutableVersionError
from modeler_project.study_routing import matrix_choice, study_matrix, subject_values
from modeler_project.workspace import Workspace
from pbpk_domain.campaign.split import StudyRecord
from pbpk_domain.dissolution import ProfileKey, profiles_from_records, profiles_from_rows
from pbpk_domain.units import UnitError, minutes_per, umol_per_l_per

SubjectType = Literal["study", "product", "compound"]
COMPOUND = "compound"                          # the compound's subject id (§6.6)
LOCATOR = "Delivery confirmation"              # a landed dataset's `source.locator`: "Delivery confirmation cf-n"
_STATISTICS = ("arithmetic_mean", "geometric_mean", "median")
_STATISTIC_WORDS = {"arithmetic_mean": "arithmetic mean", "geometric_mean": "geometric mean", "median": "median"}
_LANDED_TIME = {"min": "min", "h": "h", "day(s)": "day"}       # validate.TIME_UNITS' canonical -> what inputs reads
_DISSOLUTION_KEY = ("apparatus", "rpm", "medium", "ph", "volume_ml")     # pbpk_domain.dissolution.ProfileKey's conditions
_DISSOLUTION_UNKEYED = ("temperature_c", "surfactant")                    # conditions ProfileKey does not hold (§11.28)
_NUMERIC_CONDITIONS = ("rpm", "ph", "volume_ml", "temperature_c")
_VESSELS = 12                                                             # the template's vessel_1 … vessel_12
# What a study's values are, beside its concentrations and PK parameters: the constants that name an entity (they are
# the dataset's labels), and the fields `_Record` reads the study record from. Any other study fact has no place in a
# dataset's study record: `not_landed` lists it
_NAMING = ("study_id", "treatment", "analyte", "product", "batch")
_USED_FOR_RECORD = ("n", "dose", "route", "formulation", "food_state", "intended_use", "design", "crossover",
                    "population", "special_population", "infusion_time_min", "dosing_interval_h", "n_doses", "meal_type",
                    "co_medication", "genotype", "reference", "species", "lloq", "matrix")
# A field whose own name carries its unit: its number lands only when the value states no unit or that unit (its
# canonical spelling, `fields.known_unit`: "hr" is h). Any other unit holds the arm or the run back; nothing is
# converted at the landing (a named, derived conversion would be the ledger's, as the dose in mg is)
_NAME_UNIT = {"infusion_time_min": "min", "dosing_interval_h": "h", "strength_mg": "mg", "percent_dissolved": "%"}
_EXTRACTION = {"cell": "CELL", "digitized": "FIGURE_DIGITIZED"}           # else TABLE (PDF, Word, prose)
_EVIDENCE_EXTRACTION = {"cell": Extraction.CELL, "pdf_table": Extraction.TABLE, "docx_table": Extraction.TABLE,
                        "prose": Extraction.TEXT, "digitized": Extraction.FIGURE_DIGITIZED, "person": Extraction.MANUAL,
                        "derived": Extraction.COMPUTED}


class LandingError(ValueError):
    """The landing cannot be planned: a `StudyRecord` field no active value gives (named), or two values of one."""


class _B(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LandingPlan(_B):
    """What `land` writes, checked, and what it holds back (contracts §6.6), and whose plan it is: the subject as the
    ledger had it and its digest, so `land` writes it only under a confirmation that bound that subject in that state."""

    subject_type: SubjectType
    subject: str
    subject_digest: str
    datasets: tuple[ObservedDataset, ...]
    dissolution: tuple[tuple[str, tuple[dict[str, Any], ...]], ...]   # (client file sid, template-shaped rows)
    evidence: tuple[EvidenceItem, ...]                                # each already through evidence.assess
    held: tuple[str, ...]                                             # "<what>: <reason>"
    reject_legacy: tuple[str, ...]                                    # still proposed overlapping legacy datasets
    sheets: tuple[tuple[str, str], ...]                               # (sid, sheet or "p<page>") the bound values are in


# --- the subject -------------------------------------------------------------------------------------------------------


def resolve_subject(reader: LedgerReader, subject_type: str, subject: str) -> str:
    """The subject's id as the ledger has it now (a study or product followed through merges; the compound is
    "compound"); KeyError for a subject that is not one of the project's."""
    if subject_type == "compound":
        if subject != COMPOUND:
            raise KeyError(subject)
        return COMPOUND
    if subject_type not in ("study", "product"):
        raise ValueError(f"a subject is a study, a product or the compound, not {subject_type!r}")
    entity = reader.entity(subject)
    if entity is None or entity.type != subject_type:
        raise KeyError(subject)
    return entity.id


def subject_label(reader: LedgerReader, subject_type: str, subject: str) -> str:
    if subject_type == "compound":
        return COMPOUND
    entity = reader.entity(subject)
    return entity.label if entity is not None else subject


def subject_digest(reader: LedgerReader, subject_type: str, subject: str) -> str:
    """The subject's digest (`LedgerReader.digest`): the sorted (id, value, unit, anchor) of its active values."""
    if subject_type == "study":
        return reader.digest(study=subject)
    if subject_type == "product":
        return reader.digest(product=subject)
    return reader.digest(compound=True)


def file_records(store: IntakeStore) -> dict[str, FileRecord]:
    """Each arrived file's first `file` line, by sha256."""
    out: dict[str, FileRecord] = {}
    for entry in store.files.entries("file"):
        record = FileRecord.model_validate(entry.body)
        out.setdefault(record.sha256, record)
    return out


def place_of(anchor: str | None) -> tuple[str, tuple[str, str]] | None:
    """(file sha256, place) of an anchor: a sheet ("sheet", name), a PDF page ("page", "n"), a Word table ("docx",
    "t:n"), Word prose ("docx", "body"), text ("text", ""); None for no anchor or one that does not parse."""
    if not anchor:
        return None
    try:
        parsed = parse_anchor(anchor)
    except AnchorError:
        return None
    locator = parsed.locator
    if isinstance(locator, SheetCell):
        return parsed.file_sha256, ("sheet", locator.sheet)
    page = getattr(locator, "page", None)
    if page is not None:
        return parsed.file_sha256, ("page", str(page))
    if isinstance(locator, DocxCell):
        return parsed.file_sha256, ("docx", f"t:{locator.table}")
    if locator.kind in ("docx_span", "figure"):
        return parsed.file_sha256, ("docx", "body")
    return parsed.file_sha256, ("text", "")


def _place_text(place: tuple[str, str]) -> str:
    """A place as a Delivery recipe's table names it: the sheet, "p<page>", "d:t:<n>", or the kind."""
    kind, name = place
    return {"sheet": name, "page": f"p{name}"}.get(kind, f"d:{name}" if kind == "docx" else kind)


def _locator_text(anchor: str | None) -> str:
    try:
        return format_locator(parse_anchor(anchor).locator) if anchor else ""
    except AnchorError:
        return ""


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _other_unit(value: ValueState) -> str:
    """Why a value of a field whose name carries its unit (`_NAME_UNIT`) cannot land as written: it states another
    unit than the name's. "" when it states none or that one. The value is named by its id, never by its number."""
    needs = _NAME_UNIT[value.field]
    if value.unit is None or not value.unit.strip() or known_unit(value.field, value.unit) == needs:
        return ""
    return (f"{value.field} ({value.id}) is written in {value.unit.strip()!r}; the field takes {needs} and nothing is "
            "converted at the landing")


def _point(minutes: float, number: float) -> tuple[float, float]:
    """A point as overlap compares it: minutes and the number, both to 10 significant digits (float noise aside)."""
    return float(f"{minutes:.10g}"), float(f"{number:.10g}")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# --- overlap with the legacy card (§2) --------------------------------------------------------------------------------


@dataclass
class _Bound:
    """What a set of bound values covers: per file, its places, and per (file, place) its points."""

    places: dict[str, set[tuple[str, str]]] = field(default_factory=dict)
    points: dict[tuple[str, tuple[str, str]], set[tuple[float, float]]] = field(default_factory=dict)

    @classmethod
    def of(cls, values: Iterable[ValueState]) -> _Bound:
        bound = cls()
        for value in values:
            found = place_of(value.anchor)
            if found is None:
                continue
            file, place = found
            bound.places.setdefault(file, set()).add(place)
            number = _number(value.value)
            if number is None or value.time is None or not value.time_unit:
                continue
            try:
                minutes = value.time * minutes_per(value.time_unit)
            except UnitError:
                continue
            bound.points.setdefault((file, place), set()).add(_point(minutes, number))
        return bound


def is_delivery_dataset(found: ObservedDataset) -> bool:
    """A dataset a Delivery confirmation landed (its source names the confirmation)."""
    return found.source.locator.startswith(LOCATOR)


def _legacy_places(found: ObservedDataset, sub: dict[str, Any] | None) -> set[tuple[str, str]] | None:
    """The places of a legacy client dataset: the sheets a recipe of its file's submission names when it lists the
    dataset, the sheets its template locator names, its page; None for a Word file's (any place of that file)."""
    places: set[tuple[str, str]] = set()
    if found.source.page is not None:
        places.add(("page", str(found.source.page)))
    for part in found.source.locator.split(";"):                      # the template's "Studies!12; PK_Summary!3:20"
        sheet, mark, _rest = part.strip().partition("!")
        if mark and sheet:
            places.add(("sheet", sheet))
    if sub is not None:
        if sub.get("kind") == "docx":
            return None
        for mapping in sub.get("mappings", []):
            if found.id in mapping.get("datasets", []):
                places.update(("sheet", str(t.get("sheet"))) for t in (mapping.get("recipe") or {}).get("tables", []))
    return places


def _overlaps(found: ObservedDataset, bound: _Bound, label_keys: set[str], sub: dict[str, Any] | None) -> bool:
    file = found.source.doc_sha256
    if file is None or file not in bound.places:
        return False
    places = _legacy_places(found, sub)
    shared = ({p for p in bound.places[file] if p[0] == "docx"} if places is None else bound.places[file] & places)
    if not shared:
        return False
    if label_key(str(found.study.get("study_id", ""))) in label_keys:
        return True
    points = set().union(*(bound.points.get((file, p), set()) for p in shared))
    try:
        factor = minutes_per(found.time_unit)
    except UnitError:
        return False
    return any(_point(t * factor, v) in points for series in found.series
               for t, v in zip(series.times, series.values, strict=False) if v is not None)


def _label_keys(reader: LedgerReader, study: str, values: Iterable[ValueState]) -> set[str]:
    """The keys a legacy study id of this study may have: its label's, and `<label>-<arm>` for each arm its values name."""
    label = subject_label(reader, "study", study)
    keys = {label_key(label)}
    for arm in {v.entity.arm for v in values if v.entity.arm}:
        entity = reader.entity(arm)
        if entity is not None:
            keys.add(label_key(client_data._arm_id(label, entity.label)))
    return keys


def _overlapping(ws: Workspace, bound: _Bound, label_keys: set[str],
                 candidates: Iterable[ObservedDataset] | None = None) -> list[ObservedDataset]:
    """The legacy client datasets (of `candidates`, else every dataset of the project) that overlap the bound values."""
    subs: dict[str, dict[str, Any] | None] = {}
    out = []
    for found in (datasets(ws) if candidates is None else candidates):
        if found.origin is not Origin.CLIENT or is_delivery_dataset(found) or found.source.doc_sha256 is None:
            continue
        sha = found.source.doc_sha256
        if sha not in subs:
            subs[sha] = client_data.submission(ws, client_data.submission_id(sha))
        if _overlaps(found, bound, label_keys, subs[sha]):
            out.append(found)
    return out


def legacy_overlap(ws: Workspace, subject_type: SubjectType, subject: str, *, reader: LedgerReader,
                   candidates: Iterable[ObservedDataset] | None = None) -> list[ObservedDataset]:
    """The legacy client datasets (any state) that overlap the subject by source (§2; see the module docstring). Only a
    study has client datasets; a product's and the compound's legacy data are not datasets. `candidates`: the datasets
    to look among (a caller that asks for many subjects reads the register once); every dataset by default."""
    subject = resolve_subject(reader, subject_type, subject)
    if subject_type != "study":
        return []
    values = subject_values(reader, "study", subject)
    return _overlapping(ws, _Bound.of(values), _label_keys(reader, subject, values), candidates)


def bound_overlap(ws: Workspace, reader: LedgerReader, values: Sequence[ValueState], study: str, *,
                  candidates: Iterable[ObservedDataset] | None = None) -> list[ObservedDataset]:
    """The legacy client datasets these bound values of a study overlap (for `intake_review.covered_by_confirmation`)."""
    return _overlapping(ws, _Bound.of(values), _label_keys(reader, study, values), candidates)


# --- the plan ----------------------------------------------------------------------------------------------------------


def plan_landing(ws: Workspace, library: DocumentLibrary | None, subject_type: SubjectType, subject: str, *,
                 reader: LedgerReader, matrix: RequirementMatrix | None, mol_weight: float | None) -> LandingPlan:
    """Build and check what the landing would write (see the module docstring); write nothing. `library` gives a sheet
    value's page and row quote (None: none). LandingError names a `StudyRecord` field no active value gives."""
    return _Planner(ws, library, reader, matrix, mol_weight).plan(subject_type, subject)


class _Planner:
    def __init__(self, ws: Workspace, library: DocumentLibrary | None, reader: LedgerReader,
                 matrix: RequirementMatrix | None, mol_weight: float | None):
        self.ws, self.library, self.reader, self.matrix = ws, library, reader, matrix
        self.mol_weight = mol_weight if mol_weight and mol_weight > 0 else None
        self.store = IntakeStore(ws)
        self.files = file_records(self.store)
        self.rules: IntakeRules = load_rules()
        self.held: list[str] = []
        self._subs: dict[str, tuple[str, dict[str, Any] | None]] = {}

    # --- files ---------------------------------------------------------------------------------------------------------

    def submission(self, sha: str) -> tuple[str, dict[str, Any] | None]:
        if sha not in self._subs:
            sid = client_data.submission_id(sha)
            self._subs[sha] = (sid, client_data.submission(self.ws, sid))
        return self._subs[sha]

    def file_name(self, sha: str | None) -> str:
        if sha is None:
            return ""
        record = self.files.get(sha)
        return record.name if record is not None else sha[:12]

    def page_and_quote(self, value: ValueState) -> tuple[int | None, str]:
        found = place_of(value.anchor)
        if found is None:
            return None, value.verbatim
        file, (kind, name) = found
        if kind == "page":
            return int(name), value.verbatim
        if kind == "sheet" and self.library is not None:
            locator = parse_anchor(value.anchor).locator  # type: ignore[arg-type]
            row = int("".join(ch for ch in getattr(locator, "cell", "") if ch.isdigit()) or 0)
            try:
                page, line = client_data._row_line(self.library, file, name, row)
            except (KeyError, ValueError, OSError):
                return None, value.verbatim
            return page, line or value.verbatim
        return None, value.verbatim

    # --- the plan ------------------------------------------------------------------------------------------------------

    def plan(self, subject_type: SubjectType, subject: str) -> LandingPlan:
        subject = resolve_subject(self.reader, subject_type, subject)
        values = subject_values(self.reader, subject_type, subject)
        digest = subject_digest(self.reader, subject_type, subject)
        label = subject_label(self.reader, subject_type, subject)
        built: list[ObservedDataset] = []
        rows: list[tuple[str, tuple[dict[str, Any], ...]]] = []
        if subject_type == "study":
            built = self.study_datasets(subject, label, values, digest)
        elif subject_type == "product":
            rows = self.dissolution(subject, label, values)
        evidence = self.evidence(values, digest)
        self.not_landed(subject_type, label, values, used_rows=bool(rows))
        reject = ()
        if subject_type == "study":
            reject = tuple(d.id for d in _overlapping(self.ws, _Bound.of(values), _label_keys(self.reader, subject, values))
                           if d.state is EvidenceState.PROPOSED)
        sheets: dict[tuple[str, str], None] = {}
        for value in values:
            found = place_of(value.anchor)
            if found is None:
                continue
            sid, sub = self.submission(found[0])
            if sub is not None:
                sheets[(sid, _place_text(found[1]))] = None
        return LandingPlan(subject_type=subject_type, subject=subject, subject_digest=digest,
                           datasets=tuple(built), dissolution=tuple(rows), evidence=tuple(evidence),
                           held=tuple(dict.fromkeys(self.held)), reject_legacy=reject, sheets=tuple(sorted(sheets)))

    # --- a study's datasets --------------------------------------------------------------------------------------------

    def study_datasets(self, study: str, label: str, values: Sequence[ValueState], digest: str) -> list[ObservedDataset]:
        # every active value that states something: a fact, or a row of an extract (a study-design table's numeric
        # columns are rows of an extract, contracts §6.3)
        facts = [v for v in values if v.value is not None]
        single = study_matrix(values)
        groups: dict[tuple[str | None, str | None, str | None], dict[str, list[ValueState]]] = {}
        for value in values:
            if value.field != "concentration" and not value.field.startswith("pk."):
                continue
            key = (value.entity.arm, value.entity.analyte, matrix_choice(value.entity.matrix) or single)
            groups.setdefault(key, {"conc": [], "pk": []})["conc" if value.field == "concentration" else "pk"].append(value)
        arms = {key[0] for key in groups}
        several = len(arms) > 1
        missing: list[str] = []
        out: list[ObservedDataset] = []
        for (arm, analyte, matrix), group in groups.items():
            arm_label = self.label(arm)
            sid = client_data._arm_id(label, arm_label) if several and arm is not None else label
            what = f"{sid}: {self.label(analyte) or 'an analyte not stated'} in {matrix or 'a matrix not stated'}"
            if analyte is None:
                self.held.append(f"{what}: the analyte is not stated (ANALYTE_MISSING): not landed")
                continue
            if matrix is None:
                self.held.append(f"{what}: the matrix is not stated (MATRIX_MISSING): not landed")
                continue
            record = _Record(self, study, arm, sid, facts, values)
            if record.held:
                self.held.append(f"{what}: {record.held}")
                continue
            if record.missing:
                missing.extend(record.missing)
                continue
            built = self.dataset(record, group, arm, analyte, matrix, digest, what)
            if built is not None:
                out.append(built)
        if missing:
            raise LandingError("; ".join(dict.fromkeys(missing)))
        return out

    def label(self, entity_id: str | None) -> str:
        if entity_id is None:
            return ""
        entity = self.reader.entity(entity_id)
        return entity.label if entity is not None else entity_id

    def dataset(self, record: _Record, group: dict[str, list[ValueState]], arm: str | None, analyte: str, matrix: str,
                digest: str, what: str) -> ObservedDataset | None:
        conc, pk = group["conc"], group["pk"]
        notes: list[str] = []
        profile = _Profile.of(self, conc, record, analyte, matrix) if conc else None
        if profile is not None and profile.held:
            self.held.append(f"{what}: {profile.held}")
            if not pk:
                return None
            profile = None
        if profile is not None:
            notes.extend(profile.notes)
        reported = []
        for value in pk:
            number = _number(value.value)
            if number is None:
                notes.append(f"the reported {value.field.removeprefix('pk.')} states no number: not landed")
                continue
            # one subject's parameter keeps its subject: a `ReportedPK` has no field for it, so its statistic names it
            subject = value.entity.subject if value.statistic in (None, "individual") else None
            if not value.statistic and not subject:
                notes.append(f"the reported {value.field.removeprefix('pk.')} states no statistic: landed with none")
            reported.append(ReportedPK(
                parameter=value.field.removeprefix("pk."), value=number, unit=value.unit or "",  # type: ignore[arg-type]
                statistic=f"individual (subject {subject})" if subject else value.statistic or "", quote=value.verbatim,
                variability=f"{value.spread:g} {value.spread_kind or ''}".strip() if value.spread is not None else ""))
        # the subjects' own parameters first, by subject, then the summary statistics as the ledger has them: the
        # dataset's NCA check reads the last reported value of a parameter, and compares it with the mean profile
        reported.sort(key=lambda r: (0, _natural(r.statistic)) if r.statistic.startswith("individual") else (1, ()))
        series = profile.series if profile is not None else ()
        if not series and not reported:
            return None
        used = [*(profile.used if profile is not None else ()), *pk]
        files = Counter(v.file_sha256 for v in used if v.file_sha256)
        main = min(files, key=lambda f: (-files[f], f)) if files else None
        first = next((v for v in used if v.file_sha256 == main), used[0])
        page, quote = self.page_and_quote(first)
        methods = {v.method for v in used} - {"person", "derived"}
        extraction = _EXTRACTION.get(methods.pop(), "TABLE") if len(methods) == 1 else (
            "FIGURE_DIGITIZED" if "digitized" in methods else "TABLE")
        # a value joined from another file, a profile's or a fact its study record was read from (§6.3, condition 5)
        flags = sorted({f"cross_file: {self.file_name(v.file_sha256)} via {v.cross_file.link_fact or 'a person'}"
                        for v in (*used, *record.used) if v.cross_file is not None})
        if flags:
            notes.append("values joined from another file: " + "; ".join(f.removeprefix("cross_file: ") for f in flags))
        unit = profile.unit if profile is not None else next(
            (r.unit for r in reported if known_unit("concentration", r.unit) is not None), "ng/ml")
        study_record = record.finish(series, profile.lloq if profile is not None else None, matrix)
        if profile is not None and profile.lloq_note:
            notes.append(profile.lloq_note)
        try:
            StudyRecord.model_validate(study_record)
        except ValueError as exc:
            raise LandingError(f"{record.sid}: the study record is refused: {exc}") from exc
        found = ObservedDataset(
            id="ds-" + hashlib.sha256(f"{digest}|{arm or ''}|{analyte}|{matrix}".encode()).hexdigest()[:10],
            kind="profile" if series else "pk_parameters", study=study_record, analyte=self.label(analyte), matrix=matrix,
            time_unit=profile.time_unit if profile is not None else "h", unit=unit, series=series, reported=tuple(reported),
            origin=Origin.CLIENT, extraction=extraction,  # type: ignore[arg-type]
            source=SourceRef(doc_sha256=main, page=page, locator=LOCATOR, title=self.file_name(main)), quote=quote,
            purpose=record.purpose, provider="CLIENT", flags=tuple(flags), note="; ".join(dict.fromkeys(notes)))
        try:
            return check_dataset(found, mol_weight=self.mol_weight)
        except DatasetError as exc:
            self.held.append(f"{what}: the dataset is refused ({exc}): not landed")
            return None

    # --- a product's dissolution ---------------------------------------------------------------------------------------

    def dissolution(self, product: str, label: str, values: Sequence[ValueState]) -> list[tuple[str, tuple[dict[str, Any], ...]]]:
        runs: dict[tuple[Any, ...], list[ValueState]] = {}
        unkeyed: dict[tuple[Any, ...], set[tuple[Any, ...]]] = {}
        for value in values:
            if value.field != "percent_dissolved":
                continue
            batch = self.label(value.entity.batch)
            conditions = {k: _condition(k, v) for k, v in value.conditions.items()}
            key = (label, _product_fact(values, "product_role", value.entity.batch), _product_fact(values, "strength_mg",
                   value.entity.batch), batch, *(conditions.get(k) for k in _DISSOLUTION_KEY))
            sha = value.file_sha256 or ""
            runs.setdefault((sha, *key), []).append(value)
            unkeyed.setdefault(key, set()).add(tuple(conditions.get(k) for k in _DISSOLUTION_UNKEYED))
        by_file: dict[str, list[tuple[str, list[dict[str, Any]]]]] = {}       # sid -> (what, its rows) per run
        for run_key, run in runs.items():
            sha, key = run_key[0], run_key[1:]
            what = f"{label} batch {key[3] or 'not stated'}, {_run_words(key)}"
            strength = next((why for v in _product_values(values, "strength_mg", run[0].entity.batch)
                             if (why := _other_unit(v))), "")
            if strength:
                self.held.append(f"{what}: {strength}: not landed")
                continue
            written = [(name, text) for name, text in zip(_DISSOLUTION_KEY, key[4:], strict=True)
                       if name in _NUMERIC_CONDITIONS and isinstance(text, str)]
            if written:                                     # the profile key holds rpm, pH and volume as numbers
                self.held.append(f"{what}: " + "; ".join(f"{name} is written {text!r}, which is not a number"
                                                         for name, text in written) + ": not landed")
                continue
            if len(unkeyed[key]) > 1:
                self.held.append(f"{what}: two runs differ only in temperature or surfactant, which the profile key "
                                 "does not hold: one would overwrite the other (DISSOLUTION_RUNS_NOT_KEYED): not landed")
                continue
            sid, sub = self.submission(sha) if sha else ("", None)
            if sub is None:
                self.held.append(f"{what}: {self.file_name(sha) or 'its file'} has no client-file record (today's "
                                 "reading refused it): its rows wait")
                continue
            made, why = _rows(self, key, run)
            if why:
                self.held.append(f"{what}: {why}: not landed")
                continue
            by_file.setdefault(sid, []).append((what, made))
        out = []
        for sid, planned in sorted(by_file.items()):
            rows = [row for _what, made in self.beside_the_legacy_card(sid, planned) for row in made]
            if rows:
                out.append((sid, tuple(rows)))
        return out

    def beside_the_legacy_card(self, sid: str, planned: list[tuple[str, list[dict[str, Any]]]]
                               ) -> list[tuple[str, list[dict[str, Any]]]]:
        """The runs of one file that can land beside its readings confirmed on the client-review card (`_legacy_recipes`).
        A reading all of whose profiles are landed here is replaced at the landing, and that is listed. A reading that
        holds a landed profile together with others is not replaced (its other profiles would be dropped): the run is
        held back, listed, and stays as that card has it. A reading with none of these profiles is not touched."""
        sub = client_data.submission(self.ws, sid) or {}
        legacy = _legacy_recipes(sub)
        name = str(sub.get("file") or "its file")
        kept = list(planned)
        changed = True
        while changed:                                       # holding a run back can leave another reading part-covered
            changed = False
            landed = {key: what for what, made in kept for key in _profile_keys(made)}
            for recipe_id, keys, _datasets in legacy:
                shared = keys & set(landed)
                if not shared or keys <= set(landed):
                    continue
                others = len(keys - set(landed))
                for what, made in list(kept):
                    if _profile_keys(made) & shared:
                        kept.remove((what, made))
                        self.held.append(f"{what}: the reading of {name} confirmed on the client-review card (recipe "
                                         f"{recipe_id}) holds this profile with {others} other{'s' if others != 1 else ''} "
                                         "not confirmed here; replacing it would drop them (reject that reading there, or "
                                         "confirm the others here): not landed")
                changed = True
        landed = {key: what for what, made in kept for key in _profile_keys(made)}
        for recipe_id, keys, _datasets in legacy:
            if keys and keys <= set(landed):
                self.held.extend(f"{landed[key]}: replaces the profile read on the client-review card (recipe {recipe_id} "
                                 f"of {name}), whose records are dropped" for key in sorted(keys, key=lambda k: landed[k]))
        return kept

    # --- evidence ------------------------------------------------------------------------------------------------------

    def evidence(self, values: Sequence[ValueState], digest: str) -> list[EvidenceItem]:
        out = []
        hold = selection_rule().hold_flags
        for value in values:
            if not is_compound_field(value.field) or value.field.startswith(("link.", "relation.")):
                continue
            number = _number(value.value)
            if number is None and not (isinstance(value.value, str) and value.value.strip()):
                self.held.append(f"ev {value.field}: no value is stated: not landed")
                continue
            requirement = client_data._requirement_for(value.field, self.matrix)
            page, quote = self.page_and_quote(value)
            item = EvidenceItem(
                id="ev-" + hashlib.sha256(f"{digest}|{value.id}".encode()).hexdigest()[:10],
                req_id=requirement.req_id if requirement else None, target=value.field,
                value=number if number is not None else str(value.value), unit=value.unit,
                source_type=SourceType.CLIENT_FILE, quote=quote,
                source=SourceRef(doc_sha256=value.file_sha256, page=page, locator=_locator_text(value.anchor),
                                 title=self.file_name(value.file_sha256)),
                extraction=_EVIDENCE_EXTRACTION.get(value.method, Extraction.TABLE), conditions=dict(value.conditions),
                provider="CLIENT", note=f"ledger value {value.id}")
            assessed = assess(item, required_conditions=requirement.conditions if requirement else (), value_in_quote=True)
            flags = [f for f in assessed.flags if f.startswith(hold)]
            if flags:
                self.held.append(f"ev {value.field}: {flags[0].split(' ')[0].rstrip(':')} (lands PROPOSED)")
            out.append(assessed)
        return out

    # --- what never lands ----------------------------------------------------------------------------------------------

    def not_landed(self, subject_type: str, label: str, values: Sequence[ValueState], *, used_rows: bool) -> None:
        excretion = sorted({v.field for v in values if v.field.startswith("excretion.")})
        if excretion:
            self.held.append(f"{label}: excretion ({', '.join(excretion)}): kept in the ledger; the model inputs have "
                             "no place for it yet")
        relations = sorted({v.field for v in values if v.field.startswith("relation.") or v.relation is not None})
        if relations:
            self.held.append(f"{label}: relations ({', '.join(relations)}): kept in the ledger; the model inputs have "
                             "no place for them yet")
        if subject_type == "study":
            placed = {*_NAMING, *_USED_FOR_RECORD, "concentration", "percent_dissolved"}
            facts = sorted({v.field for v in values if v.field not in placed and v.relation is None
                            and not v.field.startswith(("pk.", "excretion.", "relation.", "link."))
                            and not is_compound_field(v.field)
                            and ((found := field_def(v.field)) is None or found.level not in ("product", "batch"))})
            if facts:
                self.held.append(f"{label}: study facts with no place in the study record ({', '.join(facts)}): kept in "
                                 "the ledger")
        if subject_type == "product":
            used = ("product", "batch", "percent_dissolved", *(("product_role", "strength_mg") if used_rows else ()))
            attributes = sorted({v.field for v in values if v.field not in used and not v.field.startswith(("link.",))
                                 and not is_compound_field(v.field)
                                 and (found := field_def(v.field)) is not None and found.level in ("product", "batch",
                                                                                                  "observation")
                                 and not v.field.startswith(("excretion.", "relation."))})
            if attributes:
                self.held.append(f"{label}: product attributes ({', '.join(attributes)}): kept in the ledger; only "
                                 "dissolution lands")


def _profile_keys(rows: Sequence[dict[str, Any]]) -> set[ProfileKey]:
    """The profile keys of template-shaped rows, as the dissolution register keys them."""
    return {profile.key for profile in profiles_from_rows([dict(row) for row in rows])[0]}


def _legacy_recipes(sub: dict[str, Any]) -> list[tuple[str, set[ProfileKey], list[str]]]:
    """A client file's readings confirmed on the client-review card that are still in force (a recipe not replaced,
    not a Delivery one): (recipe id, the profile keys of its dissolution records, its datasets)."""
    out = []
    for mapping in sub.get("mappings", []):
        recipe_id = (mapping.get("recipe") or {}).get("recipe_id")
        if mapping.get("replaced_by") or not recipe_id or str(recipe_id).startswith("delivery-"):
            continue
        records = [r for r in sub.get("dissolution_records", []) if (r.get("source") or {}).get("recipe_id") == recipe_id]
        keys = {profile.key for profile in profiles_from_records(records)[0]}
        out.append((str(recipe_id), keys, [str(d) for d in mapping.get("datasets", [])]))
    return out


def _condition(name: str, text: str) -> Any:
    """A condition as the dissolution register keys it: rpm, pH, volume and temperature as numbers (None when the text
    is empty). A text that is not a number is returned as written: `dissolution` holds its run back."""
    if name in _NUMERIC_CONDITIONS:
        if not str(text).strip():
            return None
        try:
            return float(text.replace(",", ".").strip())
        except ValueError:
            return text
    return text


def _run_words(key: tuple[Any, ...]) -> str:
    bits = [f"{name} {value:g}" if isinstance(value, float) else f"{name} {value}"
            for name, value in zip(("apparatus", "rpm", "medium", "pH", "volume_ml"), key[4:], strict=True)
            if value not in (None, "")]
    return ", ".join(bits) or "conditions not stated"


def _product_values(values: Sequence[ValueState], name: str, batch: str | None) -> list[ValueState]:
    """The values `_product_fact` reads `name` from: this batch's when they state one value, else the product's."""
    for wanted in (batch, None):
        found = [v for v in values if v.field == name and v.entity.batch == wanted and v.value is not None]
        if len({v.value for v in found}) == 1:
            return found
    return []


def _product_fact(values: Sequence[ValueState], name: str, batch: str | None) -> Any:
    """The product's fact `name` for this batch (then for the product): its single value, else None."""
    for wanted in (batch, None):
        found = {v.value for v in values if v.field == name and v.entity.batch == wanted and v.value is not None}
        if len(found) == 1:
            value = found.pop()
            if name == "product_role":
                return read_choice("product_role", str(value)) or str(value)
            return _number(value) if name == "strength_mg" else value
    return "" if name == "product_role" else None


def _natural(text: str) -> tuple[Any, ...]:
    return tuple(int(t) if t.isdigit() else t for t in re.split(r"(\d+)", text))


def _rows(planner: _Planner, key: tuple[Any, ...], run: Sequence[ValueState]) -> tuple[list[dict[str, Any]], str]:
    """The template-shaped rows of one dissolution run, one per time: its vessels (vessel_1 … vessel_12) and/or its mean,
    SD and n; ([], why) when the run cannot land."""
    product, role, strength, batch, apparatus, rpm, medium, ph, volume = key
    base = {"product": product, "role": role or "", "strength_mg": strength, "batch": batch, "apparatus": apparatus or "",
            "rpm": rpm, "medium": medium or "", "ph": ph, "volume_ml": volume}
    vessels = sorted({v.entity.vessel for v in run if v.entity.vessel}, key=_natural)
    if len(vessels) > _VESSELS:
        return [], f"more than {_VESSELS} vessels"
    slot = {name: i + 1 for i, name in enumerate(vessels)}
    rows: dict[tuple[float, str], dict[str, Any]] = {}
    for value in run:
        number = _number(value.value)
        if number is None:
            continue                                        # a mark with no number stays in the ledger
        if why := _other_unit(value):                       # a fraction of 1 is not a percent: never converted here
            return [], why
        unit = canonical_unit(value.time_unit or "", TIME_UNITS)
        if value.time is None or unit not in _LANDED_TIME:
            return [], "a time or its unit is not stated in the time table (min, h, day)"
        time_unit = _LANDED_TIME[unit]
        row = rows.setdefault((value.time, time_unit), {"values": {**base, "time": value.time, "time_unit": time_unit},
                                                       "cells": {}})
        if value.entity.vessel:
            column = f"vessel_{slot[value.entity.vessel]}"
        elif value.statistic in (None, "arithmetic_mean"):
            column = "mean"
            if value.spread is not None:
                if value.spread_kind != "SD":
                    return [], f"the mean's spread is {value.spread_kind or 'of no stated kind'}: the register takes an SD"
                row["values"]["sd"] = value.spread
                if value.locators.get("spread"):
                    row["cells"]["sd"] = _locator_text(value.locators["spread"])
            if value.n_at is not None:
                row["values"]["n"] = value.n_at
        else:
            return [], f"a {_STATISTIC_WORDS.get(value.statistic, value.statistic)} is neither a vessel nor a mean"
        if column in row["values"]:
            return [], "a vessel or a mean appears twice at one time"
        row["values"][column] = number
        row["cells"][column] = _locator_text(value.anchor)
    return [rows[k] for k in sorted(rows)], ""


# --- a study record ----------------------------------------------------------------------------------------------------


class _Record:
    """The `StudyRecord` fields one arm's values give, facts and rows of an extract alike (an arm's own value over the
    study's): `missing` names each field
    the record needs and no active value gives; `held` says why the arm cannot land (a dose unit outside the table)."""

    def __init__(self, planner: _Planner, study: str, arm: str | None, sid: str, facts: Sequence[ValueState],
                 values: Sequence[ValueState]):
        self.planner, self.study, self.arm, self.sid = planner, study, arm, sid
        self.facts, self.values = facts, values
        self.missing: list[str] = []
        self.held = ""
        self.fields: dict[str, Any] = {"study_id": sid}
        self.purpose = ""
        self.used: list[ValueState] = []                # the facts the record's fields were read from
        self.read()

    def own(self, name: str) -> list[ValueState]:
        mine = [v for v in self.facts if v.field == name and self.arm is not None and v.entity.arm == self.arm]
        return mine or [v for v in self.facts if v.field == name and v.entity.arm is None]

    def one(self, name: str, read: Any = None) -> Any:
        stated = [(read(v.value) if read else v.value, v) for v in self.own(name)]
        found = {value for value, _v in stated if value is not None}
        if len(found) > 1:
            raise LandingError(f"{self.sid}: two values of {name} are active: choose one (a conflict, or a correction)")
        self.used += [v for value, v in stated if value is not None]
        return found.pop() if found else None

    def in_own_unit(self, name: str) -> float | None:
        """A field whose name carries its unit (`_NAME_UNIT`): its number when every active value of it states no unit
        or that unit. Another unit holds the arm back (`held`): nothing is converted here."""
        for value in self.own(name):
            if _number(value.value) is not None and (why := _other_unit(value)):
                self.held = self.held or f"{why}: not landed"
                return None
        return self.one(name, _number)

    def need(self, name: str, why: str = "") -> None:
        self.missing.append(f"{self.sid}: the study record needs {name}, which no active value states{why}: enter it")

    def read(self) -> None:
        f = self.fields
        n = self.one("n", lambda v: int(v) if _number(v) is not None and float(v).is_integer() and v > 0 else None)
        if n is None:
            self.need("n")
        else:
            f["n"] = n
        route = self.one("route", lambda v: read_choice("route", str(v)))
        if route not in (*ROUTES, "other"):
            self.need("route")
        else:
            f["route"] = route
        self.dose()
        if route == "oral":
            formulation = self.one("formulation", lambda v: read_choice("formulation", str(v)))
            if formulation not in FORMULATIONS:
                self.need("formulation", " (an oral study's dosage form)")
            else:
                f["formulation"] = formulation
            food = self.one("food_state", lambda v: read_choice("food_state", str(v)))
            if food not in ("fasted", "fed"):
                self.need("food_state", " (an oral study's, never assumed)")
            else:
                f["food_state"] = food
        if route == "iv_infusion":
            minutes = self.in_own_unit("infusion_time_min")
            if self.held:
                return
            if minutes is None or minutes <= 0:
                self.need("infusion_time_min", " (an infusion's)")
            else:
                f["infusion_time_min"] = minutes
        use = self.one("intended_use", lambda v: read_choice("intended_use", str(v)))
        if use not in USES:
            self.need("intended_use", " (what the study is for)")
        else:
            self.purpose = use
        for name, key, read in (("design", "design", lambda v: read_choice("design", str(v))),
                                ("population", "population_type", lambda v: read_choice("population", str(v))),
                                ("special_population", "special_population",
                                 lambda v: read_choice("special_population", str(v))),
                                ("dosing_interval_h", "dosing_interval_h", _number),
                                ("n_doses", "n_doses", lambda v: int(v) if _number(v) is not None else None),
                                ("meal_type", "meal_type", str), ("co_medication", "co_medication", str),
                                ("genotype", "genotype", str), ("reference", "reference", str), ("species", "species", str)):
            value = self.in_own_unit(name) if name in _NAME_UNIT else self.one(name, read)
            if self.held:
                return
            if value not in (None, ""):
                f[key] = value
        crossover = self.one("crossover", lambda v: read_choice("crossover", str(v)))
        if crossover is not None:
            f["crossover"] = crossover == "yes"

    def dose(self) -> None:
        """dose_mg: a dose in mg as written; in g or µg the ledger's derived mg fact; mg/kg with dose_per_kg."""
        stated = [v for v in self.own("dose") if v.method != "derived"]
        if not stated:
            self.need("dose")
            return
        found: set[tuple[float, bool]] = set()
        for value in stated:
            number, unit = _number(value.value), known_unit("dose", value.unit or "")
            if number is None:
                continue
            if unit == "mg":
                found.add((number, False))
            elif unit == "mg/kg":
                found.add((number, True))
            elif unit in ("g", "µg"):
                derived = [d for d in self.values if d.field == "dose" and value.id in d.derived_from
                           and (d.compute or "").endswith("dose_to_mg") and _number(d.value) is not None]
                if not derived:
                    self.held = f"the dose in {unit} has no derived dose in mg yet (the ledger derives it): not landed"
                    return
                found.add((float(derived[0].value), False))  # type: ignore[arg-type]
                self.used.append(derived[0])
            else:
                self.held = (f"the dose unit {value.unit or 'not stated'!r} is outside the mass table (mg, g, µg, "
                             "mg/kg): not landed")
                return
        self.used += stated
        if not found:
            self.need("dose", " (a number)")
        elif len(found) > 1:
            raise LandingError(f"{self.sid}: two doses are active: choose one (a conflict, or a correction)")
        else:
            dose, per_kg = found.pop()
            self.fields["dose_mg"] = dose
            if per_kg:
                self.fields["dose_per_kg"] = True

    def finish(self, series: Sequence[Series], lloq: float | None, matrix: str) -> dict[str, Any]:
        record = dict(self.fields)
        record["n_timepoints"] = max((len(s.times) for s in series), default=1) or 1
        record["statistic"] = ("individual" if any(s.statistic == "individual" for s in series)
                               else "mean_sd" if any(s.error is not None for s in series) else "mean")
        record["matrices"] = [matrix]
        if lloq is not None:
            record["lloq"] = lloq
        return record


# --- a profile ---------------------------------------------------------------------------------------------------------


@dataclass
class _Profile:
    """One (arm, analyte, matrix)'s concentration values as series, or why they cannot land (`held`)."""

    series: tuple[Series, ...] = ()
    time_unit: str = "h"
    unit: str = ""
    lloq: float | None = None
    lloq_note: str = ""
    notes: list[str] = field(default_factory=list)
    used: list[ValueState] = field(default_factory=list)
    held: str = ""

    @classmethod
    def of(cls, planner: _Planner, conc: Sequence[ValueState], record: _Record, analyte: str, matrix: str) -> _Profile:
        out = cls()
        time_units = {canonical_unit(v.time_unit or "", TIME_UNITS) for v in conc}
        if None in time_units or any(v.time is None for v in conc):
            return cls(held="a time or its unit is not in the time table (min, h, day): not landed")
        if len(time_units) > 1:
            return cls(held="its times are in several units: not landed")
        out.time_unit = _LANDED_TIME[time_units.pop()]  # type: ignore[index]
        units = {known_unit("concentration", v.unit or "") for v in conc}
        if None in units:
            return cls(held="a concentration unit the unit tables lack (check_dataset refuses it): not landed")
        if len(units) > 1:
            return cls(held="its values are in several concentration units: not landed")
        out.unit = units.pop()  # type: ignore[assignment]
        try:
            umol_per_l_per(out.unit, planner.mol_weight or 1.0)
        except UnitError:
            return cls(held=f"the unit {out.unit!r} is not one pbpk_domain.units converts: not landed")
        if any((n := _number(v.value)) is not None and n < 0 for v in conc):
            return cls(held="a negative value (check_dataset refuses it): not landed")
        occasions = {v.entity.occasion for v in conc} - {None}
        if len(occasions) > 1:
            return cls(held="its values span several occasions (OCCASIONS_NOT_LANDED), and a profile holds one occasion: not landed")
        lloq, why, note = _lloq(record, conc, analyte, matrix, out.unit)
        if why:
            return cls(held=why)
        out.lloq, out.lloq_note = lloq, note
        groups: dict[tuple[Any, ...], list[ValueState]] = {}
        left_out = as_text = False
        for value in conc:
            if value.value is None and not value.censored:
                left_out = True                             # a missing-sample or above-range mark: no number, not BLQ
                continue
            if not value.censored and _number(value.value) is None:
                as_text = True                              # a text-valued row the ledger keeps as written: no point
                continue
            individual = value.statistic == "individual" or (value.statistic is None and value.entity.subject)
            if not individual and value.statistic not in _STATISTICS:
                return cls(held="a value states no statistic and no subject (STATISTIC_MISSING): not landed")
            key = (0 if individual else 1 + _STATISTICS.index(value.statistic),  # type: ignore[arg-type]
                   _natural(value.entity.subject or "") if individual else (), value.entity.subject or "",
                   value.entity.period or "", value.entity.sequence or "", tuple(sorted(value.conditions.items())))
            groups.setdefault(key, []).append(value)
        if left_out:
            out.notes.append("values with no number (a missing-sample or above-range mark) are left out: they stay in "
                             "the ledger")
        if as_text:
            out.notes.append("values written as text, not as a number, are left out: they stay in the ledger")
        series = []
        for key in sorted(groups):
            built, why = _series(planner, key, groups[key], out.notes)
            if why:
                return cls(held=why)
            series.append(built)
            out.used.extend(groups[key])
        out.series = tuple(series)
        if any(v.interval is not None for v in conc):
            out.notes.append("intervals (CI, range) are not landed: a series has none; they stay in the ledger")
        return out


def _series(planner: _Planner, key: tuple[Any, ...], values: Sequence[ValueState], notes: list[str]) -> tuple[Series, str]:
    rank, _natural_subject, subject, period, sequence, conditions = key
    statistic = "individual" if rank == 0 else _STATISTICS[rank - 1]
    name = " ".join(b for b in (subject if rank == 0 else _STATISTIC_WORDS[statistic], period, sequence,
                                ", ".join(f"{k} {v}" for k, v in conditions)) if b)
    actual = all(v.time_actual is not None for v in values)
    ordered = sorted(values, key=lambda v: v.time_actual if actual else v.time)  # type: ignore[arg-type, return-value]
    times = tuple(float(v.time_actual if actual else v.time) for v in ordered)  # type: ignore[arg-type]
    if len(set(times)) != len(times):
        return Series(times=(), values=()), f"a time appears twice in series {name} (DUPLICATE_TIME): not landed"
    if actual:
        notes.append(f"series {name}: the actual sampling times")
    landed = planner.rules.landing.spreads_landed.get(statistic, {})
    spreads = [v for v in ordered if v.spread is not None]
    kinds = {v.spread_kind for v in spreads}
    error: tuple[float | None, ...] | None = None
    kind = "none"
    if spreads:
        words = _STATISTIC_WORDS.get(statistic, statistic)
        if None in kinds:
            planner.held.append(f"series {name}: a spread of no stated kind (SPREAD_KIND_MISSING): its spread is not "
                                "landed")
        elif len(kinds) > 1:
            notes.append(f"series {name}: spreads of several kinds ({', '.join(sorted(kinds))}) are not landed: they "  # type: ignore[arg-type]
                         "stay in the ledger")
        elif (target := landed.get(next(iter(kinds)))) is None:  # type: ignore[arg-type]
            notes.append(f"series {name}: the {next(iter(kinds))} of the {words} is not landed (intake rules "
                         f"landing.spreads_landed): it stays in the ledger")
        else:
            error, kind = tuple(v.spread for v in ordered), target
    n_each = [v.n_at for v in ordered]
    return Series(name=name, statistic=statistic, times=times,  # type: ignore[arg-type]
                  values=tuple(None if v.censored else float(v.value) for v in ordered),  # type: ignore[arg-type]
                  error=error, error_kind=kind, n=next((n for n in n_each if n is not None), None),  # type: ignore[arg-type]
                  n_at=client_data._n_at(n_each)), ""


def _fits(value: ValueState, arm: str | None, analyte: str, matrix: str) -> bool:
    entity = value.entity
    return ((entity.arm is None or entity.arm == arm) and (entity.analyte is None or entity.analyte == analyte)
            and (entity.matrix is None or matrix_choice(entity.matrix) == matrix))


def _lloq(record: _Record, conc: Sequence[ValueState], analyte: str, matrix: str,
          unit: str) -> tuple[float | None, str, str]:
    """(LLOQ, why the profile is held back, a note). A person's `lloq` entry wins for the profile it names (its analyte,
    and its matrix and arm where it states them). An entry that names no analyte is the profile's only when the study
    has one analyte profile; in a study with several it replaces no profile's stated LLOQ, and the note says so. Else
    the one LLOQ the profile's `lloq` values and its censored values state; two or more: held back. An LLOQ in another
    unit than the profile's is not converted and not set (named)."""
    lloqs = [v for v in record.values if v.field == "lloq" and _number(v.value) is not None and _fits(v, record.arm,
                                                                                                     analyte, matrix)]
    person = [v for v in lloqs if v.method == "person"]
    named = [v for v in person if v.entity.analyte is not None]
    unnamed = [v for v in person if v.entity.analyte is None]
    profiles = {v.entity.analyte for v in record.values if v.field == "concentration"}
    notes = []
    entry = named[-1] if named else unnamed[-1] if unnamed and len(profiles) <= 1 else None
    if entry is not None:
        stated = {(float(entry.value), known_unit("lloq", entry.unit or ""))}  # type: ignore[arg-type]
    else:
        if unnamed:
            notes.append("a person's lloq entry names no analyte and the study has several analyte profiles: it is not "
                         "applied (enter it for the analyte); the profile's stated LLOQ stays")
        stated = {(float(v.value), known_unit("lloq", v.unit or "")) for v in lloqs if v.method != "person"}  # type: ignore[arg-type]
        stated |= {(v.lloq, known_unit("lloq", v.lloq_unit or "")) for v in conc if v.censored and v.lloq is not None}
    if len(stated) > 1:
        return None, ("two or more LLOQs in the profile and no person's lloq entry for it (ONE_LLOQ_PER_PROFILE): not "
                      "landed"), ""
    if not stated:
        return None, "", "; ".join(notes)
    value, lloq_unit = stated.pop()
    if lloq_unit != unit:
        notes.append("the LLOQ is stated in another unit than the values: not converted, not in the study record")
        return None, "", "; ".join(notes)
    return value, "", "; ".join(notes)


# --- landing -----------------------------------------------------------------------------------------------------------


def landed(ws: Workspace, confirmation_id: str) -> Landed | None:
    """The `landed` line of a confirmation, if its landing completed."""
    for entry in IntakeStore(ws).review.entries("landed"):
        if entry.body.get("confirmation") == confirmation_id:
            return Landed.model_validate(entry.body)
    return None


def land(ws: Workspace, library: DocumentLibrary | None, confirmation: Confirmation, plan: LandingPlan, *,
         by: str) -> Landed:
    """Write the plan of a signed confirmation, each item through its owner: datasets proposed and accepted
    (`dataset_register`), dissolution rows (`client_data.record_delivery_rows`, tag `delivery-<cf id>`), evidence
    proposed and accepted unless held (`evidence_register`); what an earlier confirmation of the subject landed and this
    one does not is set aside; the still proposed overlapping legacy datasets are rejected; a Delivery recipe on each
    file counts its sheets as read. Idempotent: what exists is skipped, and once the `landed` line is written a second
    land writes nothing. Audited `intake.land`. `LandingError` (a ValueError), with nothing written, for a plan that is
    not the confirmation's: another subject's, or the subject's in another state than the record bound (its digest)."""
    from modeler_project.evidence_register import EvidenceError, decide, propose

    del library                                       # the plan carries its pages and quotes
    if (plan.subject_type, plan.subject_digest) != (confirmation.subject_type, confirmation.record.get("subject_digest")):
        raise LandingError(f"not the plan of {confirmation.id}: the plan is of {plan.subject_type} {plan.subject} in "
                           f"another state than the confirmation bound ({confirmation.subject_type} {confirmation.subject})")
    store = IntakeStore(ws)
    done = landed(ws, confirmation.id)
    if done is not None:
        return done
    name = f"{LOCATOR} {confirmation.id}"
    reason = f"confirmed on Delivery ({confirmation.id}, signature {confirmation.signature_id})"
    ids: list[str] = []
    for planned in plan.datasets:
        current = dataset(ws, planned.id)
        found = planned.model_copy(update={"source": planned.source.model_copy(update={"locator": name}),
                                           "note": "; ".join(b for b in (reason, planned.note) if b)})
        if current is None:
            try:
                propose_dataset(ws, found, actor=by)
            except (DatasetError, ImmutableVersionError):
                if dataset(ws, planned.id) is None:      # not a concurrent landing of the same plan: a real refusal
                    raise
            current = dataset(ws, planned.id)
        else:
            # the same profile (the same id) landed before: never skipped silently. When this plan gives it other
            # content than the register holds (the study's label after a merge, a spread the rules no longer land),
            # the register writes the new content as a new version; what a person chose on the dataset itself (the
            # demographics, D-29), which the ledger never states, stays
            study = {**found.study, **({"demographics": current.study["demographics"]} if "demographics" in current.study
                                       else {})}
            found = check_dataset(found.model_copy(update={"study": study, "demographics_choice": current.demographics_choice}))
            if _content(found) != _content(current):
                why = f"{name} gives this dataset other content than it held"
                _unless_written(lambda found=found, why=why: revise_dataset(ws, found, by=by, reason=why))
                current = dataset(ws, planned.id)
        # accepted under this confirmation: a dataset an earlier confirmation of the same values landed (the same
        # digest, so the same id) is decided again, so its decision names the confirmation that binds it now
        if current is not None and (current.state is not EvidenceState.ACCEPTED or current.decision_reason != reason):
            _unless_written(lambda planned=planned: decide_dataset(ws, planned.id, state=EvidenceState.ACCEPTED,
                                                                   reason=reason, by=by))
        ids.append(planned.id)
    evidence: list[str] = []
    held_flags = selection_rule().hold_flags
    for item in plan.evidence:
        if _evidence(ws, item.id) is None:
            try:
                propose(ws, item.model_copy(update={"note": f"{reason}; {item.note}"}), actor=by, value_in_quote=True)
            except (EvidenceError, ImmutableVersionError):
                if _evidence(ws, item.id) is None:   # not a concurrent landing of the same plan: a real refusal
                    raise
        current_item = _evidence(ws, item.id)
        if current_item is not None and current_item.state is EvidenceState.PROPOSED \
                and not any(f.startswith(held_flags) for f in current_item.flags):
            _unless_written(lambda item=item: decide(ws, item.id, state=EvidenceState.ACCEPTED, reason=reason, by=by))
        evidence.append(item.id)
    rows = 0
    tag = f"delivery-{confirmation.id}"
    for sid, made in plan.dissolution:
        rows += client_data.record_delivery_rows(ws, sid, made, tag=tag, by=by)
    _retire_earlier(ws, store, confirmation, ids, evidence, by=by)
    replaced = f"replaced by {name}"
    for legacy_id in plan.reject_legacy:
        current = dataset(ws, legacy_id)
        if current is not None and current.state is EvidenceState.PROPOSED:
            _unless_written(lambda legacy_id=legacy_id: decide_dataset(ws, legacy_id, state=EvidenceState.REJECTED,
                                                                       reason=replaced, by=by))
    # what this confirmation's landing rejected, whichever attempt or thread of it wrote the decision
    rejected = [legacy_id for legacy_id in plan.reject_legacy if (current := dataset(ws, legacy_id)) is not None
                and current.state is EvidenceState.REJECTED and current.decision_reason == replaced]
    _record_recipes(ws, confirmation, plan, ids, by=by)

    def decide_line(entries: list[ChainEntry]) -> list[tuple[str, Any]]:
        if any(e.kind == "landed" and e.body.get("confirmation") == confirmation.id for e in entries):
            return []
        record = Landed(confirmation=confirmation.id, datasets=tuple(ids), evidence=tuple(evidence), dissolution_records=rows,
                        rejected_legacy=tuple(rejected), pending=plan.held, at=_now())
        return [("landed", record.model_dump(mode="json"))]

    written = store.review.append_if(decide_line)
    if not written:
        return landed(ws, confirmation.id)  # type: ignore[return-value]
    entry = written[0]
    store.audit(actor=by, action="intake.land", resource_id=confirmation.id,
                after={"confirmation": confirmation.id, "datasets": list(ids), "evidence": list(evidence),
                       "dissolution_records": rows, "row_hash": entry.hash})
    return Landed.model_validate(entry.body)


def _unless_written(write: Callable[[], Any]) -> None:
    """One register write of the landing. A version that exists already (`ImmutableVersionError`) was written by
    another landing of the same confirmation (a double submit) between this one's read and its write: that landing's
    work, not an error. The caller reads the register again where it needs the result."""
    try:
        write()
    except ImmutableVersionError:
        pass


def _content(found: ObservedDataset) -> dict[str, Any]:
    """A dataset's content as two landings of the same id compare it: everything but its state and decision, and the
    two places that name the confirmation that wrote it (its note and its source's locator)."""
    content = found.model_dump(mode="json", exclude={"state", "proposed_by", "proposed_at", "decided_by", "decision_reason",
                                                     "note"})
    content["source"] = {key: value for key, value in content["source"].items() if key != "locator"}
    return content


def _evidence(ws: Workspace, evidence_id: str) -> EvidenceItem | None:
    from modeler_project.evidence_register import items

    return next((i for i in items(ws) if i.id == evidence_id), None)


def _retire_earlier(ws: Workspace, store: IntakeStore, confirmation: Confirmation, ids: Sequence[str],
                    evidence: Sequence[str], *, by: str) -> None:
    """What an earlier confirmation of the same subject landed and this one does not: its datasets and evidence
    rejected, its dissolution rows removed (a correction supersedes; nothing is loaded twice). The earlier
    confirmations are those recorded before this one for the subject as the ledger has it now (a study or a product
    followed through merges, as `supersedes` is read), and every confirmation on this one's `supersedes` chain."""
    from modeler_project.evidence_register import decide

    reader = LedgerView(ws)

    def subject_of(found: Confirmation) -> str:
        entity = reader.entity(found.subject) if found.subject_type != "compound" else None
        return entity.id if entity is not None else found.subject

    recorded = [Confirmation.model_validate(e.body) for e in store.review.entries("confirmation")]
    before = recorded[:next((i for i, c in enumerate(recorded) if c.id == confirmation.id), len(recorded))]
    by_id = {c.id: c for c in before}
    chain: set[str] = set()
    link = confirmation.supersedes
    while link in by_id and link not in chain:
        chain.add(link)
        link = by_id[link].supersedes
    earlier = [c for c in before if c.id in chain or (c.subject_type == confirmation.subject_type
                                                       and subject_of(c) == subject_of(confirmation))]
    reason = f"superseded by {LOCATOR} {confirmation.id}"
    for old in earlier:
        done = landed(ws, old.id)
        if done is None:
            continue
        for old_id in done.datasets:
            current = dataset(ws, old_id)
            if old_id not in ids and current is not None and current.state is not EvidenceState.REJECTED:
                _unless_written(lambda old_id=old_id: decide_dataset(ws, old_id, state=EvidenceState.REJECTED,
                                                                     reason=reason, by=by))
        for old_id in done.evidence:
            item = _evidence(ws, old_id)
            if old_id not in evidence and item is not None and item.state is not EvidenceState.REJECTED:
                _unless_written(lambda old_id=old_id: decide(ws, old_id, state=EvidenceState.REJECTED, reason=reason, by=by))
        if done.dissolution_records:
            tag = f"delivery-{old.id}"
            for sub in client_data.submissions(ws):
                if any(r.get("tag") == tag for r in sub.get("dissolution", [])):
                    client_data.record_delivery_rows(ws, sub["id"], [], tag=tag, by=by)


def _record_recipes(ws: Workspace, confirmation: Confirmation, plan: LandingPlan, ids: Sequence[str], *, by: str) -> None:
    """A Delivery recipe on each file the bound values are anchored in (`client_data.record_mapping`): its sheets or pages
    then count as read for `sheet_intake`, and the file lists the datasets landed from it. A reading of the file
    confirmed on the client-review card (`_legacy_recipes`) is replaced only when what it holds is landed here: every
    profile of its dissolution records is among the rows this plan lands for the file (the plan listed it,
    `_Planner.beside_the_legacy_card`), or it has no such records and one of its datasets is rejected by this landing.
    Any other reading, and every other Delivery recipe, stays as it is: nothing is dropped by the sheet's name."""
    recipe_id = f"delivery-{confirmation.id}"
    by_sid: dict[str, list[str]] = {}
    for sid, place in plan.sheets:
        by_sid.setdefault(sid, []).append(place)
    landed_from = {d.id: d.source.doc_sha256 for d in plan.datasets}
    rejected = set(plan.reject_legacy)
    for sid, places in sorted(by_sid.items()):
        sub = client_data.submission(ws, sid)
        if sub is None:
            continue
        mappings = sub.get("mappings", [])
        if any((m.get("recipe") or {}).get("recipe_id") == recipe_id for m in mappings):
            continue
        landed_keys = _profile_keys([row for file, made in plan.dissolution if file == sid for row in made])
        replaces = tuple(legacy_id for legacy_id, keys, datasets in _legacy_recipes(sub)
                         if keys <= landed_keys and (keys or rejected & set(datasets)))
        mine = [i for i in ids if landed_from.get(i) == sub.get("sha256")]
        client_data.record_mapping(ws, sid, recipe={"recipe_id": recipe_id, "version": 1,
                                                    "tables": [{"sheet": p} for p in sorted(places)]},
                                   dataset_ids=mine, dissolution=[], by=by, replaces=replaces)
