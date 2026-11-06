"""The evaluation of messy client deliveries, end to end (plan 2026-11-05 §4 step 5: "messy deliveries ... scored end to
end: placed right, read right, cleaned with a record, nothing silent").

Each delivery is a set of synthetic workbooks laid out the way CROs send them (one workbook per arm, sheets per medium,
European exports with decimal commas, notes and shipping sheets beside the data), with the answer a person would write
for each sheet:
- **placed right**: the card it lands on (a study's, a product's), or "not data";
- **read right**: how many series and sampling times its reading holds;
- **asked right**: the facts its card asks because the sheet does not state them (none: it is saved at once);
- **cleaned with a record**: phrases its record of what was left out and changed must hold (`modeler_intake.cleaning`);
- **nothing silent**: every sheet of every file is read, waiting on a card, or sorted as not data; none is dropped.

`score` runs a delivery through the real path (`client_data.ingest`, code's reading on arrival, `client_review.groups`),
with agents off: what code alone does. The owner's real deliveries are scored the same way on the server, with the
answer a person writes for them. Software test data with made-up numbers: it measures the reading, never a model.

    uv run python -m modeler_project.arrival_eval        # the score of each delivery
"""

from __future__ import annotations

import io
import math
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from openpyxl import Workbook

NOT_DATA = "not data"


@dataclass(frozen=True)
class SheetAnswer:
    file: str
    sheet: str
    place: str                                  # "study:<id>", "product:<name>" or "not data"
    series: int = 0                             # a concentration sheet: the series its reading holds
    times: int = 0                              # the sampling times (a dissolution profile: its times)
    asks: tuple[str, ...] = ()                  # the facts its card asks (empty: saved at once)
    record: tuple[str, ...] = ()                # phrases its cleaning record must hold

    @property
    def ref(self) -> str:
        return f"{self.file}!{self.sheet}"


@dataclass(frozen=True)
class MessyDelivery:
    name: str
    files: tuple[tuple[str, Callable[[], bytes]], ...]
    sheets: tuple[SheetAnswer, ...]
    drug: str = "Exampleamide"
    products: tuple[tuple[str, str], ...] = ()  # the brief's products (name, role): a dissolution sheet names one


@dataclass
class Score:
    delivery: str
    found: list[str] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)
    unexpected: list[str] = field(default_factory=list)

    @property
    def perfect(self) -> bool:
        return not self.missed and not self.unexpected


# --- the workbooks, as CROs send them ---------------------------------------------------------------------------------

def _save(wb: Workbook) -> bytes:
    raw = io.BytesIO()
    wb.save(raw)
    return raw.getvalue()


TIMES = ("Pre-dose", "0.50", "1.00", "2.00", "4.00", "8.00", "12.00", "24.00")


def _curve(t: float, scale: float) -> float:
    return round(scale * 120 * (math.exp(-0.08 * t) - math.exp(-0.9 * t)), 2)


def be_arm(arm: str, *, subjects: int = 6, ns_at: tuple[int, int] | None = (2, 7)) -> Callable[[], bytes]:
    """One arm of a BE study: times across, a BLQ pre-dose, an "NS" where a sample was missed, Mean and SD rows under the
    subjects, a footnote."""
    def build() -> bytes:
        wb = Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        ws.append([f"Study 230-23: plasma concentrations of exampleamide (ng/mL), {arm}, 50 mg, fasting"])
        ws.append([])
        ws.append(["Time (hr)"])
        ws.append(["Subject No.", "Period", *TIMES])
        for i in range(1, subjects + 1):
            values: list[Any] = ["BLQ", *(_curve(float(t), 0.85 + 0.05 * i) for t in TIMES[1:])]
            if ns_at and i == ns_at[0]:
                values[ns_at[1]] = "NS"
            ws.append([f"{i:03d}", "I" if i % 2 else "II", *values])
        ws.append(["Mean", None, None, *(_curve(float(t), 1.0) for t in TIMES[1:])])
        ws.append(["SD", None, None, *(round(_curve(float(t), 0.12), 2) for t in TIMES[1:])])
        ws.append([])
        ws.append(["BLQ = below the lower limit of quantification (0.50 ng/mL); NS = no sample"])
        return _save(wb)
    return build


def dissolution_workbook(product: str, media: tuple[tuple[str, float], ...], *, info: bool = True) -> Callable[[], bytes]:
    """A dissolution profiling workbook: one sheet per medium (times down, 6 vessels, the conditions in the title), and
    an information sheet with no data."""
    def build() -> bytes:
        wb = Workbook()
        wb.remove(wb.active)
        for label, t50 in media:
            ws = wb.create_sheet(label)
            ws.append([f"Dissolution of {product} (Test), Batch No. B501, USP II (paddle), 50 rpm, 900 mL {label} buffer"])
            ws.append(["Time (min)", *(f"Vessel {i}" for i in range(1, 7))])
            for t in (5, 10, 15, 30, 45, 60):
                base = 100 * (1 - math.exp(-math.log(2) * (t / t50) ** 1.1))
                ws.append([t, *(round(base + d, 1) for d in (-1.5, -0.5, 0, 0.3, 0.8, 1.2))])
        if info:
            ws = wb.create_sheet("Info")
            for line in (["Report prepared by the analytical laboratory"], ["Method: USP <711>, validated"],
                         ["Approved by: QA, 2026-09-12"]):
                ws.append(line)
        return _save(wb)
    return build


def european_mean_export() -> bytes:
    """A mean profile exported from a European system: numbers as text with decimal commas, "NS" where nothing was
    sampled, a comments column, and notes below the table."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Mean"
    ws.append(["Study X-01: mean plasma concentrations of exampleamide (ng/mL), 10 mg oral tablet, fasted, n = 12"])
    ws.append(["Time (h)", "Mean", "SD", "Comments"])
    for t, mean, sd, comment in (("0", "NS", None, "pre-dose not sampled"), ("0,5", "12,4", "1,2", None),
                                 ("1", "20,1", "2,0", None), ("2", "15,3", "1,8", "one sample haemolysed"),
                                 ("4", "8,2", "1,1", None), ("8", "2,6", "0,4", None)):
        ws.append([t, mean, sd, comment])
    ws.append([])
    ws.append(["Values are the arithmetic mean of 12 subjects; SD = standard deviation"])
    return _save(wb)


def shipment_with_data() -> bytes:
    """Individual concentrations (times down, one column per subject) beside a shipping log with no data."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Conc"
    ws.append(["Study EX-77: exampleamide plasma concentration (ng/mL), 25 mg oral solution, fed"])
    ws.append(["Time (h)", *(f"S{i:02d}" for i in range(1, 5))])
    for t in (0.25, 0.5, 1, 2, 4, 6, 8):
        ws.append([t, *(_curve(t, 0.4 + 0.1 * i) for i in range(1, 5))])
    log = wb.create_sheet("Shipping")
    for line in (["Samples shipped on dry ice to the bioanalytical site"], ["Courier: on 2026-08-30, 4 boxes"],
                 ["Received intact"]):
        log.append(line)
    return _save(wb)


DELIVERIES: tuple[MessyDelivery, ...] = (
    MessyDelivery("a BE study sent one workbook per arm, with BLQ and NS cells, Mean and SD rows and a footnote", (
        ("230-23 Fasting Test.xlsx", be_arm("Test")), ("230-23 Fasting Reference.xlsx", be_arm("Reference", ns_at=None))),
        sheets=(
            SheetAnswer("230-23 Fasting Test.xlsx", "Sheet1", "study:230-23-TEST", series=7, times=8,
                        asks=("n", "formulation", "purpose"),
                        record=("below the LLOQ", "marked “NS”: no sample", "Below the table")),
            SheetAnswer("230-23 Fasting Reference.xlsx", "Sheet1", "study:230-23-REF", series=7, times=8,
                        asks=("n", "formulation", "purpose"), record=("below the LLOQ", "Below the table")),
        )),
    MessyDelivery("a dissolution profiling workbook, one sheet per medium and an information sheet", (
        ("Dissolution Test Profiles.xlsx",
         dissolution_workbook("Exampleamide ER Tablets 50 mg", (("pH 1.2", 20.0), ("pH 4.5", 25.0), ("pH 6.8", 30.0)))),),
        sheets=(
            *(SheetAnswer("Dissolution Test Profiles.xlsx", medium, "product:Exampleamide ER Tablets 50 mg", times=6,
                          record=("Above the table",)) for medium in ("pH 1.2", "pH 4.5", "pH 6.8")),
            SheetAnswer("Dissolution Test Profiles.xlsx", "Info", NOT_DATA),
        ), products=(("Exampleamide ER Tablets 50 mg", "TEST"),)),
    MessyDelivery("a European export: decimal commas, NS, a comments column and notes below the table", (
        ("X-01 mean PK.xlsx", european_mean_export),),
        sheets=(
            # "10 mg oral tablet": immediate or modified release is not said, so the dosage form is asked
            SheetAnswer("X-01 mean PK.xlsx", "Mean", "study:X-01", series=1, times=5, asks=("formulation", "purpose"),
                        record=("decimal comma", "Column D (“Comments”) not read", "marked “NS”: no sample",
                                "Below the table")),
        )),
    MessyDelivery("a shipping log beside the subjects' concentrations", (
        ("EX-77 bioanalysis.xlsx", shipment_with_data),),
        sheets=(
            SheetAnswer("EX-77 bioanalysis.xlsx", "Conc", "study:EX-77", series=4, times=7, asks=("n", "purpose"),
                        record=("Above the table",)),
            SheetAnswer("EX-77 bioanalysis.xlsx", "Shipping", NOT_DATA),
        )),
)


# --- the score ------------------------------------------------------------------------------------------------------

def _brief(ws: Any, delivery: MessyDelivery) -> Any:
    from modeler_project.brief import FieldStatus, empty_brief
    from modeler_project.brief_ops import edit_field, save_brief

    brief = empty_brief(delivery.drug, by="eval")
    for i, (name, role) in enumerate(delivery.products):
        brief = edit_field(brief, f"products[{i}].name", value=name, status=FieldStatus.EDITED, by="eval")
        brief = edit_field(brief, f"products[{i}].role", value=role, status=FieldStatus.EDITED, by="eval")
    save_brief(ws, brief, actor="eval", reason="the evaluation's brief")
    return brief


def _placed(groups: list[dict[str, Any]], sid: str, file: str, sheet: str, datasets: list[str]) -> str | None:
    """The group a sheet's data landed in: its draft, its datasets, or (a dissolution sheet) a profile from its file."""
    for g in groups:
        for item in g["items"]:
            if item["id"] == f"draft|{sid}|{sheet}" or item["id"] in datasets:
                return g["id"]
            if item["kind"] == "profile" and file in item["source"]["title"]:
                return g["id"]
    return None


def score(delivery: MessyDelivery, ws: Any, *, by: str = "eval") -> Score:
    """Read one delivery into an empty project workspace, code alone (agents off), and compare with its answer."""
    from modeler_project.client_data import ingest, submission
    from modeler_project.client_review import groups
    from modeler_project.dissolution_register import profiles
    from modeler_project.documents import DocumentLibrary
    from modeler_project.sheet_intake import READ

    brief = _brief(ws, delivery)            # as the upload passes it (`client_api`)
    library = DocumentLibrary(ws)
    stored = {name: ingest(ws, library, build(), name, by=by, brief=brief)["id"] for name, build in delivery.files}
    found_groups = groups(ws)
    result = Score(delivery.name)
    answered = {(a.file, a.sheet) for a in delivery.sheets}
    for name, sid in stored.items():
        content = submission(ws, sid) or {}
        category = {t["sheet"]: t["category"] for t in content.get("triage", [])}
        readings = content.get("readings") or {}
        mapped = {t.get("sheet"): m for m in content.get("mappings", []) if not m.get("replaced_by")
                  for t in m["recipe"].get("tables", [])}
        for sheet, cat in category.items():                       # nothing silent: every sheet is accounted for
            accounted = cat not in READ or sheet in readings or sheet in mapped
            if not accounted:
                result.unexpected.append(f"silent {name}!{sheet}")
            elif (name, sheet) not in answered:
                result.unexpected.append(f"unanswered {name}!{sheet} ({cat.lower()})")
    for a in delivery.sheets:
        sid = stored[a.file]
        content = submission(ws, sid) or {}
        category = {t["sheet"]: t["category"] for t in content.get("triage", [])}
        reading = (content.get("readings") or {}).get(a.sheet) or {}
        mapped = [m for m in content.get("mappings", []) if not m.get("replaced_by")
                  and any(t.get("sheet") == a.sheet for t in m["recipe"].get("tables", []))]
        datasets = [d for m in mapped for d in m.get("datasets", [])]
        if a.place == NOT_DATA:
            place = NOT_DATA if category.get(a.sheet) not in READ else _placed(found_groups, sid, a.file, a.sheet, datasets)
        else:
            place = _placed(found_groups, sid, a.file, a.sheet, datasets)
        _check(result, f"place {a.ref} → {a.place}", place == a.place, f"landed {place}")
        if a.place == NOT_DATA:
            continue
        if a.series:
            series = (reading.get("points") or {}).get("series") or []
            got = (len(series), len({t for s in series for t in s["times"]}))
            _check(result, f"read {a.ref}: {a.series} series × {a.times} times", got == (a.series, a.times),
                   f"read {got[0]} × {got[1]}")
        elif a.times:
            mine = [p for p in profiles(ws) if a.file in ", ".join(p.get("files", [])) and a.sheet in " ".join(p.get("cells", []))]
            got_times = len(mine[0]["times_min"]) if mine else 0
            _check(result, f"read {a.ref}: {a.times} times", got_times == a.times, f"read {got_times}")
        asks = tuple(n for n in reading.get("needs", []) if not mapped)
        _check(result, f"asks {a.ref}: {', '.join(a.asks) or 'nothing (saved)'}", set(asks) == set(a.asks),
               f"asks {', '.join(asks) or 'nothing'}")
        lines = " ".join(line["text"] for line in reading.get("cleaning", []))
        for phrase in a.record:
            _check(result, f"record {a.ref}: {phrase}", phrase in lines, "not in its record")
    return result


def _check(result: Score, item: str, ok: bool, why: str) -> None:
    (result.found if ok else result.missed).append(item if ok else f"{item} ({why})")


def main() -> None:
    from modeler_project import FileProjectStore, Workspace

    total = missed = 0
    for delivery in DELIVERIES:
        with tempfile.TemporaryDirectory() as root:
            result = score(delivery, Workspace(FileProjectStore(root), "eval", "p1"))
        total += len(result.found) + len(result.missed)
        missed += len(result.missed)
        print(f"{'ok  ' if result.perfect else 'MISS'} {delivery.name}: {len(result.found)} found")
        for item in (*result.missed, *result.unexpected):
            print(f"       {item}")
    print(f"{total - missed} of {total} checks right, {len(DELIVERIES)} deliveries")


if __name__ == "__main__":
    main()
