"""The evaluation set for reading client sheets (redesign §3.2, R3c): client sheets in the layouts real files use, each
with the values it holds and how a person reads it.

A reader is scored on each sheet: code's first filling (`suggest`), the reading agent
(`modeler_agents.evals.sheet_reading`), or the person's reading kept with the case. Its reading is applied and checked by
code exactly as a confirmed reading would be (`to_proposal`, `review_proposal`). The score then says whether the
reading:
- reads without a problem;
- gives back every value at its time, below-LLOQ marks included;
- has the units, the statistic, the LLOQ and the dose right.

The sheets are synthetic: this module writes each one from its answer, so the answer is known by construction. They
are software test data, never observed data. The owner's real files are scored only on the server, never committed.
"""

from __future__ import annotations

import io
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from openpyxl import Workbook

from modeler_intake.grid import WorkbookGrid, read_workbook_bytes
from modeler_intake.recipe_review import RecipeProposal, review_proposal
from modeler_intake.sheet_form import Evidence, Kind, SheetForm, suggest, to_proposal
from modeler_intake.validate import CONCENTRATION_UNITS, TIME_UNITS, canonical_unit

Point = tuple[float, float | None]          # a time as the sheet states it, and the value there (None: below the LLOQ)
FIELDS = ("read", "values", "units", "statistic", "lloq", "dose")


@dataclass(frozen=True)
class Answer:
    """What a sheet holds, in the sheet's own units."""

    series: dict[str, tuple[Point, ...]]
    kind: Kind = "concentration_time"
    statistic: str = "individual"
    time_unit: str = "h"
    value_unit: str = "ng/mL"
    mean: tuple[Point, ...] = ()            # the sheet's own mean profile next to the subjects
    sd: tuple[float, ...] = ()              # the SD of a summary series, at each of its times
    n: int | None = None                    # the subjects behind a summary series
    lloq: float | None = None
    dose_mg: float | None = None            # the dose (a dissolution sheet: the strength)


@dataclass(frozen=True)
class Case:
    name: str
    layout: str                             # the layout in words
    file: str
    sheet: str
    drug: str
    build: Callable[[Any], None]            # writes the sheet (an openpyxl worksheet) from the answer
    answer: Answer
    form: SheetForm                         # how a person reads it: the scorer must give it full marks


@dataclass
class Score:
    case: str
    fields: dict[str, bool]
    problems: list[str] = field(default_factory=list)

    @property
    def exact(self) -> bool:
        return all(self.fields.values())


Reader = Callable[[Case, WorkbookGrid], SheetForm | None]


def workbook_bytes(case: Case) -> bytes:
    """The case's sheet as an .xlsx file, as a client would send it."""
    book = Workbook()
    sheet = book.active
    sheet.title = case.sheet
    case.build(sheet)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def workbook(case: Case) -> WorkbookGrid:
    return read_workbook_bytes(workbook_bytes(case), case.file)


# --- scoring ---------------------------------------------------------------------------------------------------------


def _key(points: Sequence[Point]) -> tuple[tuple[float, float, bool], ...]:
    """A profile in an order-free form: (time, value, below the LLOQ), sorted; series names are not compared."""
    return tuple(sorted((round(t, 9), -1.0 if v is None else round(v, 9), v is None) for t, v in points))


def _profiles(points: list[tuple[str, float, float | None]]) -> list[tuple[tuple[float, float, bool], ...]]:
    by_series: dict[str, list[Point]] = {}
    for series, time, value in points:
        by_series.setdefault(series, []).append((time, value))
    return sorted(_key(p) for p in by_series.values())


def _same(a: float | None, b: float | None) -> bool:
    return (a is None) == (b is None) and (a is None or math.isclose(a, b, rel_tol=1e-9))  # type: ignore[arg-type]


def _number(text: object) -> float | None:
    try:
        return float(str(text))
    except ValueError:
        return None


def score(case: Case, form: SheetForm | None) -> Score:
    """How well one reading reads one sheet (every field False when there is no reading)."""
    if form is None:
        return Score(case.name, dict.fromkeys(FIELDS, False), ["no reading"])
    grid = workbook(case)
    answer = case.answer
    try:
        proposal = RecipeProposal.model_validate(to_proposal(form, grid.sheets[case.sheet]))
    except (KeyError, ValueError) as exc:
        return Score(case.name, dict.fromkeys(FIELDS, False), [f"not a reading: {exc}"])
    review = review_proposal(grid, proposal, recipe_id=f"eval-{case.name}")
    problems = [f"{i.code} {i.location}: {i.message}" for i in review.issues] + list(review.questions)
    expected = sorted(_key(p) for p in answer.series.values())
    if answer.kind == "dissolution":
        values = _profiles([(r.vessel, r.time, r.percent_dissolved) for r in review.dissolution]) == expected
        value_unit_ok = form.value_unit.strip() == "%"
        dose = _number(form.constants.get("strength_mg", ""))
    else:
        main = [r for r in review.concentrations if r.statistic == answer.statistic]
        values = _profiles([(r.series, r.time, None if r.below_lloq else r.value) for r in main]) == expected
        if answer.mean:
            mean = [r for r in review.concentrations if r.statistic != answer.statistic]
            values = values and _profiles([(r.series, r.time, r.value) for r in mean]) == [_key(answer.mean)]
        if answer.sd:
            values = values and [r.sd for r in sorted(main, key=lambda r: r.time)] == list(answer.sd)
        if answer.n is not None:
            values = values and bool(main) and all(r.n == answer.n for r in main)
        value_unit_ok = canonical_unit(form.value_unit, CONCENTRATION_UNITS) == canonical_unit(answer.value_unit,
                                                                                               CONCENTRATION_UNITS)
        dose = _number(form.constants.get("dose", ""))
    fields = {
        "read": review.ready_for_confirmation,
        "values": values,
        "units": value_unit_ok and canonical_unit(form.time_unit, TIME_UNITS) == canonical_unit(answer.time_unit, TIME_UNITS),
        "statistic": answer.kind == "dissolution" or form.statistic == answer.statistic,
        "lloq": _same(form.lloq, answer.lloq),
        "dose": _same(dose, answer.dose_mg),
    }
    return Score(case.name, fields, problems)


def evaluate(reader: Reader, cases: Sequence[Case] | None = None) -> list[Score]:
    scores = []
    for case in cases or CASES:
        try:
            form = reader(case, workbook(case))
        except Exception as exc:  # noqa: BLE001 - a reader that fails on one sheet is scored, the run goes on
            scores.append(Score(case.name, dict.fromkeys(FIELDS, False), [f"the reader failed: {type(exc).__name__}: {exc}"]))
            continue
        scores.append(score(case, form))
    return scores


def report(scores: Sequence[Score]) -> str:
    width = max(len(s.case) for s in scores)
    lines = [f"{'sheet':<{width}}  " + "  ".join(f"{f:<9}" for f in FIELDS) + "  exact"]
    for s in scores:
        lines.append(f"{s.case:<{width}}  " + "  ".join(f"{'ok' if s.fields[f] else '-':<9}" for f in FIELDS)
                     + f"  {'yes' if s.exact else 'no'}")
    for f in FIELDS:
        lines.append(f"{f}: {sum(s.fields[f] for s in scores)}/{len(scores)}")
    lines.append(f"exact: {sum(s.exact for s in scores)}/{len(scores)}")
    return "\n".join(lines)


# --- readers ---------------------------------------------------------------------------------------------------------


def suggest_reader(case: Case, grid: WorkbookGrid) -> SheetForm:
    """Code's first filling, as the Client data page shows it before a person changes anything."""
    return suggest(grid.sheets[case.sheet], filename=case.file, drug=case.drug)[0]


def answer_reader(case: Case, grid: WorkbookGrid) -> SheetForm:
    """The person's reading kept with the case: full marks, or the case and the scorer disagree."""
    return case.form


# --- the sheets ------------------------------------------------------------------------------------------------------


def _rows(sheet: Any, rows: Sequence[Sequence[Any]]) -> None:
    for row in rows:
        sheet.append(list(row))


def _ev(sheet: str, cell: str, quote: str, field_: str, value: str) -> Evidence:
    return Evidence(cell=f"{sheet}!{cell}", quote=quote, supports=f"{field_} {value}", field=field_, value=value)


# 1 · a bioequivalence listing: times across the top, a period column, pre-dose, BLQ and NS, Mean and SD rows
_BE_TIMES = (0.0, 0.5, 1.0, 2.0, 4.0, 8.0, 12.0, 24.0)
_BE = {"001 / I": ("BLQ", 12.1, 40.5, 80.2, 95.0, 60.1, 41.0, 12.3),
       "002 / II": ("BLQ", 10.0, 35.0, 70.4, "NS", 55.5, 39.9, 10.8),
       "003 / I": ("BLQ", 9.1, 30.2, 66.0, 81.0, 50.0, 35.5, 9.9)}
_BE_MEAN = (None, 10.4, 35.2, 72.2, 88.0, 55.2, 38.8, 11.0)


def _be(sheet: Any) -> None:
    _rows(sheet, [
        ["Study 230-23: plasma concentrations of desvenlafaxine (ng/mL) after a single 50 mg dose"], [], ["Time (hr)"],
        ["Subject No.", "Period", "Pre-dose", "0.50", "1.00", "2.00", "4.00", "8.00", "12.00", "24.00"],
        *([*name.split(" / "), *values] for name, values in _BE.items()),
        ["Mean", None, *_BE_MEAN], ["SD", None, None, 1.5, 5.2, 7.2, 7.0, 5.0, 2.9, 1.2], [],
        ["BLQ = below the lower limit of quantification (1.00 ng/mL); NS = no sample"],
    ])


def _be_answer() -> Answer:
    series = {name: tuple((t, None if v == "BLQ" else float(v)) for t, v in zip(_BE_TIMES, values, strict=True) if v != "NS")
              for name, values in _BE.items()}
    return Answer(series=series, lloq=1.0, dose_mg=50.0,
                  mean=tuple((t, v) for t, v in zip(_BE_TIMES, _BE_MEAN, strict=True) if v is not None))


# 2 · a listing in long form: one row per subject and time, a "<LLOQ" token, the LLOQ in a note under the table
_LONG_TIMES = (0.0, 1.0, 2.0, 4.0, 8.0, 24.0)
_LONG = {"101-001": ("<LLOQ", 15.2, 22.8, 18.1, 9.4, 1.2), "101-002": ("<LLOQ", 11.7, 19.5, 16.0, 8.1, 0.9),
         "101-003": ("<LLOQ", 18.9, 25.1, 20.2, 10.3, "<LLOQ")}


def _long(sheet: Any) -> None:
    _rows(sheet, [["Subject", "Nominal time (h)", "Concentration (ng/mL)"],
                  *([s, t, v] for s, values in _LONG.items() for t, v in zip(_LONG_TIMES, values, strict=True)),
                  [], ["LLOQ = 0.5 ng/mL"]])


# 3 · one column per subject, times down
_WIDE_TIMES = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 12.0)
_WIDE = {"S01": (3.1, 8.8, 14.2, 12.0, 7.7, 3.0, 1.1), "S02": (2.4, 7.1, 12.9, 11.2, 7.0, 2.8, 0.9),
         "S03": (4.0, 9.9, 15.8, 13.1, 8.2, 3.3, 1.3), "S04": (1.8, 6.0, 11.5, 10.4, 6.6, 2.5, 0.8)}


def _wide(sheet: Any) -> None:
    _rows(sheet, [["Plasma concentrations (ng/mL) after a single 20 mg oral dose"], ["Time (h)", *_WIDE],
                  *([t, *(v[i] for v in _WIDE.values())] for i, t in enumerate(_WIDE_TIMES))])


# 4 · a published table: mean, SD and N columns
_MEAN_TIMES = (0.5, 1.0, 2.0, 4.0, 8.0, 12.0, 24.0)
_MEAN = (20.1, 45.3, 61.0, 48.2, 25.5, 13.0, 3.2)
_MEAN_SD = (6.2, 12.0, 15.1, 11.8, 7.3, 4.1, 1.5)


def _mean(sheet: Any) -> None:
    _rows(sheet, [["Time (h)", "Mean (ng/mL)", "SD", "N"],
                  *([t, m, s, 12] for t, m, s in zip(_MEAN_TIMES, _MEAN, _MEAN_SD, strict=True))])


# 5 · minutes and µg/L; the subject columns are headed "Subj 1" … (the header word for a subject column)
_MIN_TIMES = (5.0, 15.0, 30.0, 60.0, 120.0, 240.0)
_MIN = {"Subj 1": (410.0, 352.0, 290.0, 201.0, 98.0, 24.0), "Subj 2": (388.0, 340.0, 275.0, 190.0, 91.0, 22.0),
        "Subj 3": (452.0, 371.0, 301.0, 214.0, 104.0, 27.0)}


def _minutes(sheet: Any) -> None:
    _rows(sheet, [["Plasma concentration (µg/L) during and after a 30-minute infusion"], ["Time (min)", *_MIN],
                  *([t, *(v[i] for v in _MIN.values())] for i, t in enumerate(_MIN_TIMES))])


# 6 · a report table: title rows, the header further down, a source line directly under the data
_CSR_TIMES = (0.5, 1.0, 1.5, 2.0, 4.0, 6.0, 12.0)
_CSR = (5.5, 14.8, 19.9, 21.0, 15.2, 9.8, 2.6)
_CSR_SD = (2.1, 4.9, 5.5, 5.8, 4.4, 3.0, 1.0)


def _csr(sheet: Any) -> None:
    _rows(sheet, [["Table 14.2.1 Mean (SD) plasma concentrations"], ["Study EX-201, 10 mg tablet, fasted"], [],
                  ["Nominal time (h)", "Mean conc. (ng/mL)", "SD (ng/mL)", "n"],
                  *([t, m, s, 10] for t, m, s in zip(_CSR_TIMES, _CSR, _CSR_SD, strict=True)),
                  ["Source: Listing 16.2.6"]])


# 7 · geometric means with a CV column (a CV is not an SD)
_GEO_TIMES = (1.0, 2.0, 4.0, 8.0, 24.0)
_GEO = (33.0, 52.4, 40.1, 21.7, 4.4)


def _geo(sheet: Any) -> None:
    _rows(sheet, [["Time (h)", "Geometric mean (ng/mL)", "Geo CV%", "N"],
                  *([t, g, cv, 8] for t, g, cv in zip(_GEO_TIMES, _GEO, (28.0, 25.5, 30.2, 35.0, 41.3), strict=True))])


# 8 · dissolution: twelve vessels, the conditions in the title
_DISS_TIMES = (5.0, 10.0, 15.0, 20.0, 30.0, 45.0, 60.0)
_DISS = {f"V{v}": tuple(round(min(100.0, 100 * (1 - math.exp(-t / 12)) + (v - 6.5) * 0.4), 1) for t in _DISS_TIMES)
         for v in range(1, 13)}


def _dissolution(sheet: Any) -> None:
    title = "Dissolution of Test tablets 10 mg, batch B123, 900 mL pH 6.8 phosphate buffer, USP apparatus 2 (paddle), 50 rpm"
    mean = [round(sum(v[i] for v in _DISS.values()) / 12, 1) for i in range(len(_DISS_TIMES))]
    _rows(sheet, [[title], ["Time (min)", *_DISS, "Mean", "SD"],
                  *([t, *(v[i] for v in _DISS.values()), mean[i], 1.4] for i, t in enumerate(_DISS_TIMES))])


# 9 · an export with decimal commas (the numbers are text)
_COMMA_TIMES = (0.5, 1.0, 2.0, 4.0, 8.0)
_COMMA = (12.4, 30.5, 41.2, 28.8, 10.1)
_COMMA_SD = (3.1, 7.7, 9.0, 6.2, 2.5)


def _comma(sheet: Any) -> None:
    def text(x: float) -> str:
        return f"{x:g}".replace(".", ",")

    _rows(sheet, [["Time (h)", "Mean conc. (ng/mL)", "SD", "N"],
                  *([text(t), text(m), text(s), "6"] for t, m, s in zip(_COMMA_TIMES, _COMMA, _COMMA_SD, strict=True))])


# 10 · units and n stated only in a note under the table
_NOTE_TIMES = (0.5, 1.0, 2.0, 3.0, 6.0, 12.0, 24.0)
_NOTE = (80.0, 150.0, 210.0, 190.0, 120.0, 55.0, 12.0)
_NOTE_SD = (20.0, 35.0, 44.0, 40.0, 28.0, 14.0, 4.0)


def _note(sheet: Any) -> None:
    _rows(sheet, [["Time (h)", "Mean", "SD"], *([t, m, s] for t, m, s in zip(_NOTE_TIMES, _NOTE, _NOTE_SD, strict=True)), [],
                  ["All concentrations in nmol/L; n = 16 healthy volunteers."]])


# 11 · times across as numbers under an ID column, the time unit in the title, BLQ explained under the table
_ACROSS_TIMES = (0.0, 0.5, 1.0, 2.0, 4.0, 8.0, 24.0)
_ACROSS = {"P01": ("BLQ", 4.2, 9.8, 12.5, 8.0, 3.1, 0.4), "P02": ("BLQ", 3.5, 8.1, 11.0, 7.2, 2.9, 0.3),
           "P03": ("BLQ", 5.1, 10.9, 13.8, 8.8, 3.6, 0.5), "P04": ("BLQ", 2.9, 7.0, 10.2, 6.9, 2.5, "BLQ"),
           "P05": ("BLQ", 4.8, 10.1, 12.9, 8.4, 3.3, 0.4)}


def _across(sheet: Any) -> None:
    _rows(sheet, [["Plasma concentration (ng/mL) by nominal time after dose (h)"], ["ID", *_ACROSS_TIMES],
                  *([s, *v] for s, v in _ACROSS.items()), [], ["BLQ: below 0.2 ng/mL"]])


def _series(times: Sequence[float], by_name: dict[str, Sequence[Any]], blq: str = "BLQ") -> dict[str, tuple[Point, ...]]:
    return {name: tuple((t, None if v == blq else float(v)) for t, v in zip(times, values, strict=True))
            for name, values in by_name.items()}


_PK = {"analyte": "Exampleamide", "matrix": "plasma"}

CASES: tuple[Case, ...] = (
    Case("be-times-across", "times across the top, subject and period columns, pre-dose, BLQ and NS, Mean and SD rows",
         "230-23_Fasting_Reference.xlsx", "Sheet1", "Desvenlafaxine", _be, _be_answer(),
         SheetForm(sheet="Sheet1", layout="times_across", header_row=4, first_data_row=5, last_data_row=7,
                   subject_column="A", group_column="B", value_columns=list("CDEFGHIJ"), time_unit="h", value_unit="ng/mL",
                   lloq=1.0, below_lloq_tokens=["BLQ"], missing_tokens=["NS"], mean_row=8, mean_n=3,
                   constants={"study_id": "230-23-REF", "analyte": "Desvenlafaxine", "matrix": "plasma", "dose": "50",
                              "dose_unit": "mg", "route": "oral", "food_state": "fasted"},
                   evidence=[_ev("Sheet1", "A1", "ng/mL", "value_unit", "ng/mL"), _ev("Sheet1", "A3", "hr", "time_unit", "h"),
                             _ev("Sheet1", "A11", "1.00 ng/mL", "lloq", "1"), _ev("Sheet1", "A1", "50 mg", "dose", "50")])),
    Case("long-subject-time", "long form: subject, time and value columns, a <LLOQ token, the LLOQ in a note",
         "Study_101_PK_listing.xlsx", "PK_Individual", "Exampleamide", _long,
         Answer(series=_series(_LONG_TIMES, _LONG, blq="<LLOQ"), lloq=0.5),
         SheetForm(sheet="PK_Individual", header_row=1, first_data_row=2, time_column="B", subject_column="A",
                   value_columns=["C"], time_unit="h", value_unit="ng/mL", lloq=0.5, below_lloq_tokens=["<LLOQ"],
                   constants={"study_id": "101", **_PK},
                   evidence=[_ev("PK_Individual", "C1", "ng/mL", "value_unit", "ng/mL"),
                             _ev("PK_Individual", "B1", "h", "time_unit", "h"),
                             _ev("PK_Individual", "A21", "LLOQ = 0.5 ng/mL", "lloq", "0.5")])),
    Case("wide-subjects", "one column per subject, times down, the unit and dose in a title row", "PK_wide.xlsx", "Plasma",
         "Exampleamide", _wide, Answer(series=_series(_WIDE_TIMES, _WIDE), dose_mg=20.0),
         SheetForm(sheet="Plasma", header_row=2, first_data_row=3, time_column="A", value_columns=list("BCDE"), time_unit="h",
                   value_unit="ng/mL", constants={"study_id": "wide", **_PK, "dose": "20", "dose_unit": "mg", "route": "oral"},
                   evidence=[_ev("Plasma", "A1", "ng/mL", "value_unit", "ng/mL"), _ev("Plasma", "A2", "h", "time_unit", "h"),
                             _ev("Plasma", "A1", "20 mg", "dose", "20")])),
    Case("published-mean", "a published table: mean, SD and N columns", "Smith2015_Table2.xlsx", "Mean PK", "Exampleamide",
         _mean, Answer(series={"mean": tuple(zip(_MEAN_TIMES, _MEAN, strict=True))}, statistic="arithmetic_mean", sd=_MEAN_SD,
                       n=12),
         SheetForm(sheet="Mean PK", header_row=1, first_data_row=2, time_column="A", value_columns=["B"], sd_column="C",
                   n_column="D", statistic="arithmetic_mean", time_unit="h", value_unit="ng/mL",
                   constants={"study_id": "Smith2015", **_PK},
                   evidence=[_ev("Mean PK", "B1", "ng/mL", "value_unit", "ng/mL"), _ev("Mean PK", "A1", "h", "time_unit", "h")])),
    Case("minutes-subj-columns", "minutes and µg/L; subject columns headed 'Subj 1', 'Subj 2' …", "IV_infusion_study.xlsx",
         "Conc", "Exampleamide", _minutes, Answer(series=_series(_MIN_TIMES, _MIN), time_unit="min", value_unit="µg/L"),
         SheetForm(sheet="Conc", header_row=2, first_data_row=3, time_column="A", value_columns=list("BCD"), time_unit="min",
                   value_unit="µg/L", constants={"study_id": "IV", **_PK, "route": "iv_infusion", "formulation": "solution"},
                   study={"infusion_time_min": "30"},
                   evidence=[_ev("Conc", "A1", "µg/L", "value_unit", "µg/L"), _ev("Conc", "A2", "min", "time_unit", "min")])),
    Case("report-table", "title rows, the header on row 4, a source line directly under the data", "CSR_Table_14-2-1.xlsx",
         "T14.2.1", "Exampleamide", _csr,
         Answer(series={"mean": tuple(zip(_CSR_TIMES, _CSR, strict=True))}, statistic="arithmetic_mean", sd=_CSR_SD, n=10,
                dose_mg=10.0),
         SheetForm(sheet="T14.2.1", header_row=4, first_data_row=5, last_data_row=11, time_column="A", value_columns=["B"],
                   sd_column="C", n_column="D", statistic="arithmetic_mean", time_unit="h", value_unit="ng/mL",
                   constants={"study_id": "EX-201", **_PK, "dose": "10", "dose_unit": "mg", "route": "oral",
                              "food_state": "fasted"},
                   evidence=[_ev("T14.2.1", "B4", "ng/mL", "value_unit", "ng/mL"), _ev("T14.2.1", "A4", "h", "time_unit", "h"),
                             _ev("T14.2.1", "A2", "10 mg", "dose", "10")])),
    Case("geometric-mean", "geometric means with a CV column and N", "Geo_means.xlsx", "Summary", "Exampleamide", _geo,
         Answer(series={"geo": tuple(zip(_GEO_TIMES, _GEO, strict=True))}, statistic="geometric_mean", n=8),
         SheetForm(sheet="Summary", header_row=1, first_data_row=2, time_column="A", value_columns=["B"], n_column="D",
                   statistic="geometric_mean", time_unit="h", value_unit="ng/mL", constants={"study_id": "geo", **_PK},
                   evidence=[_ev("Summary", "B1", "ng/mL", "value_unit", "ng/mL"), _ev("Summary", "A1", "h", "time_unit", "h")])),
    Case("dissolution-vessels", "dissolution: twelve vessel columns, Mean and SD, the conditions in the title",
         "Dissolution_Test_B123.xlsx", "Dissolution", "Exampleamide", _dissolution,
         Answer(series={k: tuple(zip(_DISS_TIMES, v, strict=True)) for k, v in _DISS.items()}, kind="dissolution",
                time_unit="min", value_unit="%", dose_mg=10.0),
         SheetForm(sheet="Dissolution", kind="dissolution", header_row=2, first_data_row=3, time_column="A",
                   value_columns=list("BCDEFGHIJKLM"), time_unit="min", value_unit="%",
                   constants={"role": "TEST", "product": "Test tablet", "batch": "B123", "medium": "phosphate buffer",
                              "ph": "6.8", "rpm": "50", "volume_ml": "900", "strength_mg": "10",
                              "apparatus": "USP apparatus 2"},
                   evidence=[_ev("Dissolution", "A2", "min", "time_unit", "min"),
                             _ev("Dissolution", "A1", "batch B123", "batch", "B123"),
                             _ev("Dissolution", "A1", "10 mg", "strength_mg", "10")])),
    Case("decimal-comma", "an export with decimal commas, the numbers stored as text", "Export_EU.xlsx", "Data",
         "Exampleamide", _comma,
         Answer(series={"mean": tuple(zip(_COMMA_TIMES, _COMMA, strict=True))}, statistic="arithmetic_mean", sd=_COMMA_SD,
                n=6),
         SheetForm(sheet="Data", header_row=1, first_data_row=2, time_column="A", value_columns=["B"], sd_column="C",
                   n_column="D", statistic="arithmetic_mean", time_unit="h", value_unit="ng/mL", decimal_comma=True,
                   constants={"study_id": "EU", **_PK},
                   evidence=[_ev("Data", "B1", "ng/mL", "value_unit", "ng/mL"), _ev("Data", "A1", "h", "time_unit", "h")])),
    Case("unit-in-note", "no unit in the header: the unit and n in a note under the table", "Study_C_profile.xlsx",
         "Profile", "Exampleamide", _note,
         Answer(series={"mean": tuple(zip(_NOTE_TIMES, _NOTE, strict=True))}, statistic="arithmetic_mean",
                value_unit="nmol/L", sd=_NOTE_SD, n=16),
         SheetForm(sheet="Profile", header_row=1, first_data_row=2, time_column="A", value_columns=["B"], sd_column="C",
                   statistic="arithmetic_mean", time_unit="h", value_unit="nmol/L",
                   constants={"study_id": "C", **_PK, "n": "16"},
                   evidence=[_ev("Profile", "A10", "nmol/L", "value_unit", "nmol/L"), _ev("Profile", "A1", "h", "time_unit", "h"),
                             _ev("Profile", "A10", "n = 16", "n", "16")])),
    Case("times-across-numbers", "times across as numbers under an ID column, the time unit in the title",
         "Pop_PK_wide.xlsx", "Conc", "Exampleamide", _across, Answer(series=_series(_ACROSS_TIMES, _ACROSS), lloq=0.2),
         SheetForm(sheet="Conc", layout="times_across", header_row=2, first_data_row=3, subject_column="A",
                   value_columns=list("BCDEFGH"), time_unit="h", value_unit="ng/mL", lloq=0.2, below_lloq_tokens=["BLQ"],
                   constants={"study_id": "PopPK", **_PK},
                   evidence=[_ev("Conc", "A1", "ng/mL", "value_unit", "ng/mL"), _ev("Conc", "A1", "(h)", "time_unit", "h"),
                             _ev("Conc", "A9", "below 0.2 ng/mL", "lloq", "0.2")])),
)
