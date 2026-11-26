"""CDISC datasets described by code (plan 2026-11-26 §7 phase 2b): no agent is asked for a table code can describe.

A CRO delivers its clinical data as CDISC datasets (SAS `.xpt` / `.sas7bdat`, sometimes a CSV or a workbook sheet),
whose variables are standard names. Where those names say everything a description needs, code writes the
`TableDescription` itself, from the dataset's own variables, and the extractor (A8) and the checker (A9) skip the file
(`modeler_agents.dataroom.stages`). A table code is not sure of is left to the agents, with the reason said.

- **SDTM PC** (pharmacokinetic concentrations): the subject (USUBJID), the analyte (PCTEST, else PCTESTCD: a dataset
  that measured the drug and its metabolites gives each line its analyte), the planned time (PCTPTNUM), the result in
  standard units (PCSTRESC with PCSTRESU, else PCORRES with PCORRESU), the specimen (PCSPEC) and the category (PCCAT,
  context). Described only when:
  - PCTPTNUM agrees with the time each line writes (PCELTM, an ISO 8601 duration, else PCTPT: "0.5 h", "Pre-dose"),
    in one unit (hours, minutes or days) for the whole study;
  - one unit holds every result;
  - each line is one sample of one profile. The profile's occasion is the dose its time counts from: PCTPTREF, else
    PCGRPID or EPOCH when every value names a period ("Period 2"). VISIT never is: in a CRO's delivery (2026-11-26) a
    profile's 24 h sample is on "Day 1" and its 48 h sample on "Day 2"; the times run on across visits. The
    description is read back and refused when two lines of one analyte share a subject, an occasion and a time
    (`clinical.colliding_samples`).
  A result that is not a number is below the LLOQ when it says so ("<0.500", "<", "BLQ"); one the dataset marks NOT
  DONE (PCSTAT) on every line it is written is a missing sample ("MS"); any other ("N.R.") stays unread and is said.
- **DM / ADSL** (one line per subject): subject, sex, age, weight, height, BMI and race, each unit from its unit
  variable (AGEU, WEIGHTU, HEIGHTU).

A dataset that pools several studies (STUDYID) is one table per study, each study's lines a contiguous run.

Not described by code here (described by the agents, as any other file): PP (PK parameters: one line per parameter,
with model-based and NCA values side by side), EX (dosing) and every ADaM dataset but ADSL. Tying a period to its
treatment (EX, ADSL TRTxxP) is not done: an SDTM PC dataset names no treatment.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Sequence

from modeler_intake.room import Line, Part, document_parts
from modeler_intake.room_specs import ColumnSpec, Extraction, TableDescription
from modeler_intake.source_model import SourceDocument
from modeler_project.dataroom.clinical import colliding_samples
from modeler_project.dataroom.extract import parse_number, read_table
from modeler_project.dataroom.store import DataRoomStore

#: the describer's version, recorded as the author of every description it writes (a change to a rule is a new one)
DESCRIBER = "cdisc-1"

_DEFAULT_MISSING = list(TableDescription.model_fields["missing_tokens"].default_factory())  # type: ignore[misc]
_PERIOD = re.compile(r"(?i)\bperiod\b|\bper\s*\d|\bp\s*\d+\b|\btreatment\s+(?:period\s+)?\d+\b")
_PREDOSE = re.compile(r"(?i)\bpre[\s-]?dose\b|\bbaseline\b|\bpredose\b")
_TPT = re.compile(r"(?i)^\s*(-?\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours|min|mins|minute|minutes|d|day|days)\b")
_ISO = re.compile(r"(?i)^-?P(?:(\d+(?:\.\d+)?)D)?(?:T(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?)?$")
_TO_HOURS = {"h": 1.0, "hr": 1.0, "hrs": 1.0, "hour": 1.0, "hours": 1.0, "min": 1 / 60, "mins": 1 / 60,
             "minute": 1 / 60, "minutes": 1 / 60, "d": 24.0, "day": 24.0, "days": 24.0}
_UNITS = {"h": 1.0, "min": 1 / 60, "d": 24.0}


def _iso_hours(text: str) -> float | None:
    """An ISO 8601 duration in hours ("PT0.5H", "-PT2M", "P1DT2H"); None for anything else."""
    m = _ISO.match(text.strip())
    if not m or not any(m.groups()):
        return None
    d, h, mi, s = (float(x) if x else 0.0 for x in m.groups())
    hours = 24 * d + h + mi / 60 + s / 3600
    return -hours if text.strip().startswith("-") else hours


def _said_hours(tpt: str, eltm: str) -> float | None:
    """The time a line writes, in hours: its PCELTM, else its PCTPT ("0.5 h", "30 min"); 0 for a pre-dose sample."""
    if eltm.strip() and (hours := _iso_hours(eltm)) is not None:
        return hours
    if m := _TPT.match(tpt):
        return float(m.group(1)) * _TO_HOURS[m.group(2).lower()]
    if _PREDOSE.search(tpt):
        return 0.0
    return None


class _Sheet:
    """A sheet's variables (line 1) and its data lines (from line 2, or 3 when line 2 holds the labels)."""

    def __init__(self, part: Part, labels: bool):
        self.part = part
        self.columns = {c.text.strip().upper(): i for i, c in enumerate(part.lines[0].cells, start=1) if c.text.strip()}
        self.first = 3 if labels else 2
        self.header_lines = [1, 2] if labels else [1]
        self.lines = [ln for ln in part.lines if ln.number >= self.first and any(c.text.strip() for c in ln.cells)]

    def has(self, *names: str) -> bool:
        return all(n in self.columns for n in names)

    def get(self, line: Line, name: str) -> str:
        i = self.columns.get(name)
        return line.cells[i - 1].text.strip() if i is not None and i <= len(line.cells) else ""

    def runs(self) -> tuple[list[tuple[str, list[Line]]], str]:
        """The lines by study (STUDYID), each study's lines a contiguous run; why not, when a study's lines are apart."""
        if "STUDYID" not in self.columns:
            return [("", self.lines)], ""
        runs: list[tuple[str, list[Line]]] = []
        for line in self.lines:
            study = self.get(line, "STUDYID")
            if runs and runs[-1][0] == study:
                runs[-1][1].append(line)
            else:
                runs.append((study, [line]))
        apart = [s for s, n in Counter(s for s, _ in runs).items() if n > 1]
        return runs, (f"the lines of study {', '.join(apart)} are not one run (sort the dataset by STUDYID)" if apart else "")

    def column(self, name: str, role: str, unit: str = "") -> ColumnSpec:
        return ColumnSpec(index=self.columns[name], role=role, label=name, unit=unit)


def _one_unit(sheet: _Sheet, lines: Sequence[Line], name: str) -> tuple[str, str]:
    """The one unit a unit variable holds over the lines, and why not when it holds several."""
    units = sorted({sheet.get(ln, name) for ln in lines} - {""})
    if len(units) > 1:
        return "", f"{name} holds {len(units)} units ({', '.join(units)})"
    return (units[0] if units else ""), ""


def _time_unit(sheet: _Sheet, lines: Sequence[Line]) -> tuple[str, str]:
    """The unit PCTPTNUM is written in ("h", "min", "d"), checked against the time every line writes; why not."""
    pairs = {(sheet.get(ln, "PCTPTNUM"), sheet.get(ln, "PCTPT"), sheet.get(ln, "PCELTM")) for ln in lines}
    pairs = {p for p in pairs if p[0]}
    if not pairs:
        return "", "PCTPTNUM is empty on every line"
    said: list[tuple[float, float, str]] = []
    for num, tpt, eltm in sorted(pairs):
        value = parse_number(num)
        if value is None:
            return "", f"PCTPTNUM {num!r} is not a number"
        hours = _said_hours(tpt, eltm)
        if hours is None:
            return "", f"PCTPT {tpt!r} writes no time to check PCTPTNUM {num} against"
        said.append((value, hours, tpt or eltm))
    for unit, factor in _UNITS.items():
        if all(math.isclose(v * factor, h, rel_tol=1e-6, abs_tol=1e-6) or (h == 0 and v <= 0) for v, h, _t in said):
            return unit, ""
    v, h, t = next((v, h, t) for v, h, t in said if not math.isclose(v, h, rel_tol=1e-6, abs_tol=1e-6))
    return "", f"PCTPTNUM {v:g} does not agree with {t!r} ({h:g} h) in hours, minutes or days"


def _occasion(sheet: _Sheet, lines: Sequence[Line]) -> str:
    """The variable that names each profile's occasion (the dose its times count from), "" when none does."""
    if sheet.has("PCTPTREF") and any(sheet.get(ln, "PCTPTREF") for ln in lines):
        return "PCTPTREF"
    for name in ("PCGRPID", "EPOCH"):
        values = {sheet.get(ln, name) for ln in lines} - {""} if sheet.has(name) else set()
        if len(values) > 1 and all(_PERIOD.search(v) for v in values):
            return name
    return ""


def _analyte(sheet: _Sheet, lines: Sequence[Line]) -> str:
    """PCTEST (the analyte's name) when each name is one PCTESTCD and each code one name, else PCTESTCD."""
    if not sheet.has("PCTEST"):
        return "PCTESTCD"
    pairs = {(sheet.get(ln, "PCTESTCD"), sheet.get(ln, "PCTEST")) for ln in lines}
    codes, names = Counter(c for c, _ in pairs), Counter(n for _, n in pairs)
    return "PCTEST" if all(n == 1 for n in codes.values()) and all(n == 1 for n in names.values()) and "" not in names \
        else "PCTESTCD"


def _not_done(sheet: _Sheet, lines: Sequence[Line], value: str) -> list[str]:
    """The results that are not numbers and not below the LLOQ, written only on lines the dataset marks NOT DONE."""
    if not sheet.has("PCSTAT"):
        return []
    status: dict[str, set[str]] = defaultdict(set)
    for ln in lines:
        text = sheet.get(ln, value)
        if text and parse_number(text) is None and not text.startswith("<"):
            status[text].add(sheet.get(ln, "PCSTAT").upper())
    return sorted(t for t, s in status.items() if s == {"NOT DONE"})


def _pc(sheet: _Sheet, path: str, sha256: str, doc: SourceDocument) -> tuple[list[TableDescription], list[str]]:
    runs, why = sheet.runs()
    if why:
        return [], [f"{sheet.part.name}: SDTM PC not described by code: {why}"]
    value, unit_var = ("PCSTRESC", "PCSTRESU") if sheet.has("PCSTRESC") else ("PCORRES", "PCORRESU")
    out: list[TableDescription] = []
    notes: list[str] = []
    for study, lines in runs:
        where = f"{sheet.part.name}{f', study {study}' if study else ''}"
        unit, why = _one_unit(sheet, lines, unit_var) if sheet.has(unit_var) else ("", f"no {unit_var}")
        time_unit, why_time = _time_unit(sheet, lines) if sheet.has("PCTPTNUM") else ("", "no PCTPTNUM")
        if why or why_time or not unit:
            notes.append(f"{where}: SDTM PC not described by code: {why or why_time or f'{unit_var} is empty'}")
            continue
        occasion, analyte = _occasion(sheet, lines), _analyte(sheet, lines)
        columns = [sheet.column("USUBJID", "subject"), sheet.column(analyte, "analyte"),
                   sheet.column("PCTPTNUM", "time", time_unit), sheet.column(value, "value", unit)]
        if occasion:
            columns.append(sheet.column(occasion, "period"))
        columns += [sheet.column(n, r) for n, r in (("PCSPEC", "matrix"), ("PCCAT", "group")) if sheet.has(n)]
        missing = _not_done(sheet, lines, value)
        said = [f"time {'PCTPTNUM'} in {time_unit}, checked against {'PCELTM' if sheet.has('PCELTM') else 'PCTPT'}",
                f"occasion {occasion}" if occasion else "one occasion per subject (no PCTPTREF, and PCGRPID/EPOCH name no "
                "period)", f"result {value} in {unit}"]
        if missing:
            said.append(f"{', '.join(repr(m) for m in missing)} on NOT DONE lines (PCSTAT): missing samples")
        desc = TableDescription(
            file=path, kind="concentrations", about=study, part=sheet.part.name, header_lines=sheet.header_lines,
            first_line=lines[0].number, last_line=lines[-1].number,
            skip_lines=[k for k in range(lines[0].number, lines[-1].number + 1) if k not in {ln.number for ln in lines}],
            columns=sorted(columns, key=lambda c: c.index), time_unit=time_unit, value_unit=unit,
            missing_tokens=_DEFAULT_MISSING + [m for m in missing if m not in _DEFAULT_MISSING],
            note=f"described by code ({DESCRIBER}): SDTM PC; " + "; ".join(said))
        read = read_table(desc, doc, file=path, sha256=sha256)
        errors = [p.message for p in read.problems if p.severity == "error"]
        if errors or (clash := colliding_samples(read)):
            notes.append(f"{where}: SDTM PC not described by code: {errors[0] if errors else clash}")
            continue
        out.append(desc)
    return out, notes


_SUBJECT_VARIABLES = (("SEX", "sex", ""), ("AGE", "age", "AGEU"), ("WEIGHT", "weight", "WEIGHTU"),
                      ("HEIGHT", "height", "HEIGHTU"), ("BMI", "bmi", "BMIU"), ("RACE", "race", ""))


def _subjects(sheet: _Sheet, path: str, name: str) -> tuple[list[TableDescription], list[str]]:
    runs, why = sheet.runs()
    if why:
        return [], [f"{sheet.part.name}: {name} not described by code: {why}"]
    out: list[TableDescription] = []
    notes: list[str] = []
    for study, lines in runs:
        where = f"{sheet.part.name}{f', study {study}' if study else ''}"
        twice = [s for s, n in Counter(sheet.get(ln, "USUBJID") for ln in lines).items() if n > 1]
        if twice:
            notes.append(f"{where}: {name} not described by code: {len(twice)} subjects on more than one line")
            continue
        columns = [sheet.column("USUBJID", "subject")]
        for var, role, unit_var in _SUBJECT_VARIABLES:
            if not sheet.has(var):
                continue
            unit, why = _one_unit(sheet, lines, unit_var) if unit_var and sheet.has(unit_var) else ("", "")
            if why:
                notes.append(f"{where}: {name} {var} left out: {why}")
                continue
            columns.append(sheet.column(var, role, unit))
        out.append(TableDescription(
            file=path, kind="demographics", about=study, part=sheet.part.name, header_lines=sheet.header_lines,
            first_line=lines[0].number, last_line=lines[-1].number,
            skip_lines=[k for k in range(lines[0].number, lines[-1].number + 1) if k not in {ln.number for ln in lines}],
            columns=columns, note=f"described by code ({DESCRIBER}): {name}, one line per subject"))
    return out, notes


def _domain(sheet: _Sheet) -> str:
    """The CDISC domain code describes, from the sheet's variables: PC, DM or ADSL ("" for any other)."""
    if sheet.has("USUBJID", "PCTESTCD") and (sheet.has("PCSTRESC") or sheet.has("PCORRES")):
        return "PC"
    if sheet.has("USUBJID", "SEX") and not any(n.endswith("TESTCD") or n == "PARAMCD" for n in sheet.columns):
        return "ADSL" if any(n in sheet.columns for n in ("SAFFL", "TRT01P", "TRT01A", "TRTSEQP")) else "DM"
    return ""


def describe(path: str, sha256: str, doc: SourceDocument) -> tuple[Extraction | None, list[str]]:
    """The file's CDISC tables described by code (None when it holds none code describes), and a note for each table
    of a domain code knows that it left to the agents, with the reason."""
    if not doc.sheets:                 # a dataset is a sheet: a PDF's pages are not laid out for nothing
        return None, []
    labels = any(w.startswith("SAS_LABELS") for w in doc.warnings)
    tables: list[TableDescription] = []
    notes: list[str] = []
    for part in document_parts(doc):
        if not part.name.startswith("sheet:") or len(part.lines) < 2:
            continue
        sheet = _Sheet(part, labels=labels)
        domain = _domain(sheet)
        if domain == "PC":
            got, said = _pc(sheet, path, sha256, doc)
        elif domain in ("DM", "ADSL"):
            got, said = _subjects(sheet, path, domain)
        else:
            continue
        tables += got
        notes += said
    if not tables:
        return None, notes
    return Extraction(file=path, tables=tables), notes


def describe_room(store: DataRoomStore, *, redo: bool = False, only: set[str] | None = None
                  ) -> tuple[list[str], list[str]]:
    """Every read file of the room code describes, described (the extractor and the checker then skip it): the files
    described, and the notes (a table of a known domain left to the agents, with why). A file an agent described stays
    as the agent described it unless `redo`; a description by code is written again only when it changed."""
    described: list[str] = []
    notes: list[str] = []
    for f in store.files():
        if f.duplicate_of or (only is not None and f.path not in only):
            continue
        triage = store.triage(f.sha256)
        if triage is not None and triage.purpose != "used":
            continue
        known = store.extraction(f.sha256)
        if known is not None and not redo and known[1].get("agent") != "code":
            continue
        doc = store.doc(f.sha256)
        if doc is None:
            continue
        got, said = describe(f.path, f.sha256, doc)
        notes += [f"{f.path}, {n}" for n in said]
        if got is None:
            continue
        if known is None or known[1].get("agent") != "code" or known[0] != got:
            store.put_extraction(got, f.sha256, agent={"agent": "code", "describer": DESCRIBER})
            store.record_author(stage="extract", file=f.path, model="code", identity=DESCRIBER, prompt=DESCRIBER,
                                note="described by code: no agent was asked")
        described.append(f.path)
    return described, notes
