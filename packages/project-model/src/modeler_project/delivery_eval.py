"""The evaluation set for reading a client's delivery across files (docs/plans/2026-11-03-inputs-and-client-data.md §3.4,
build I6, grown alongside from I3 on).

Each delivery is a small set of synthetic client files with a known answer: the groups the client's data must form,
the conflicts, differences and questions that must be flagged on them, the links to ask about, and what must be found
the same across files (made one, with a note). `score` runs a delivery through the real path (the library, the tags,
`client_data.ingest`, `client_review.groups`) and says what was found, what was missed and what was flagged that the
answer does not hold. Software test data with made-up numbers: it measures the reading, never a model.

A delivery with a PDF or Word file (build I4) needs a reader: `score(..., read_documents=…)` runs the reading agent on
each document (the server's model when it is scored there). Each such delivery also carries `reading`, the tool calls
a perfect reader would make: the tests run it through the real agent tools, so the answer is known to pass code's
checks, and what the server's model reads is scored against the same answer.

Real client deliveries are scored the same way on the server, with the answer a person writes for them.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from modeler_intake.client_template import build_template

DOCUMENTS = (".pdf", ".docx")


@dataclass(frozen=True)
class DeliveryFile:
    name: str
    build: Callable[[], bytes]
    tag: tuple[str, str] | None = None          # (kind, study) as the person tags it at upload
    reading: tuple[tuple[str, dict[str, Any]], ...] = ()   # a document: the tool calls a perfect reader makes

    @property
    def document(self) -> bool:
        return self.name.lower().endswith(DOCUMENTS)


@dataclass(frozen=True)
class Delivery:
    name: str
    files: tuple[DeliveryFile, ...]
    groups: tuple[str, ...]                     # the group ids the data must form
    flags: tuple[str, ...] = ()                 # "<group>|<issue key prefix>:<kind>" for every conflict, difference, link
    notes: tuple[str, ...] = ()                 # a phrase each "found the same" note must hold, by group: "<group>|<phrase>"

    @property
    def needs_reader(self) -> bool:
        return any(f.document for f in self.files)


@dataclass
class Score:
    delivery: str
    found: list[str] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)
    unexpected: list[str] = field(default_factory=list)

    @property
    def perfect(self) -> bool:
        return not self.missed and not self.unexpected


def _template(*, studies: list[dict[str, Any]] = (), summary: list[tuple] = (), dissolution: list[tuple] = (),
              note: str = "") -> Callable[[], bytes]:
    def build() -> bytes:
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(build_template()))
        header = [c.value.rstrip("*") for c in wb["Studies"][1]]
        for study in studies:
            wb["Studies"].append([study.get(h) for h in header])
        for row in summary:
            wb["PK_Summary"].append(list(row))
        for row in dissolution:
            wb["Dissolution"].append(list(row))
        if note:
            wb["README"]["A1"] = note
        out = io.BytesIO()
        wb.save(out)
        return out.getvalue()

    return build


def synthetic_pdf(pages: list[list[str]]) -> bytes:
    """A small valid PDF with these lines on each page (written by hand: no PDF writer dependency)."""
    objects, kids = [], []
    for i, lines in enumerate(pages):
        page_obj, content_obj = 4 + 2 * i, 5 + 2 * i
        kids.append(f"{page_obj} 0 R")
        escaped = [line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for line in lines]
        stream = ("BT /F1 10 Tf 14 TL 50 760 Td " + " T* ".join(f"({line}) Tj" for line in escaped) + " ET").encode("latin-1")
        objects.append(f"{page_obj} 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                       f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_obj} 0 R >> endobj\n".encode())
        objects.append(f"{content_obj} 0 obj << /Length {len(stream)} >> stream\n".encode() + stream + b"\nendstream endobj\n")
    head = [b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
            f"2 0 obj << /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >> endobj\n".encode(),
            b"3 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >> endobj\n"]
    body, offsets = b"%PDF-1.4\n", []
    for obj in head + objects:
        offsets.append(len(body))
        body += obj
    xref = len(body)
    body += f"xref\n0 {len(offsets) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        body += f"{offset:010d} 00000 n \n".encode()
    return body + f"trailer << /Size {len(offsets) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


def synthetic_docx(paragraphs: list[str]) -> bytes:
    """A small Word file with these paragraphs."""
    import docx

    document = docx.Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def _study(study_id: str, *, dose: float = 10, n: int = 12) -> dict[str, Any]:
    return {"study_id": study_id, "design": "SD", "population": "healthy", "n": n, "route": "oral", "dose": dose,
            "dose_unit": "mg", "formulation": "ir_tablet", "food_state": "fasted", "lloq": 0.5, "lloq_unit": "ng/ml"}


def _pk(study_id: str, values: tuple[float, ...], n: int = 12) -> list[tuple]:
    return [(study_id, None, t, "h", "arithmetic_mean", v, None, None, n, "ng/ml") for t, v in zip((0.5, 1, 2, 4, 8), values,
                                                                                              strict=True)]


def _diss(at_30: float, *, product: str = "Test 10 mg tablet", batch: str = "B1") -> list[tuple]:
    return [(product, "TEST", 10, batch, "USP 2 paddle", 50, "phosphate", 6.8, 900, 37, None, t, "min", v, v + 1, v - 1)
            for t, v in ((15, 55), (30, at_30), (45, 97))]


PK = (18.0, 42.0, 31.0, 13.0, 4.2)
SYNOPSIS = ["Clinical study synopsis: Study EX-301",
            "Design: open-label study; subjects received a single oral dose of 10 mg as one film-coated tablet.",
            "Dosing took place after an overnight fast of at least 10 hours.",
            "Population: Twelve healthy subjects (n = 12) were dosed and completed the study."]
PROTOCOL = ["Clinical Study Protocol", "Protocol EXZ-101 (Study 101)",
            "12 healthy subjects receive a single oral dose of 10 mg in the fasted state."]
DEMOGRAPHICS = ["Clinical study synopsis: Study EX-302",
                "Subjects: Twelve healthy Caucasian subjects (12 men, 0 women) aged 24 to 41 years (mean age 31.5 years).",
                "Their mean body weight was 76.2 kg."]
CERTIFICATE = ["Certificate of analysis: Test 10 mg tablet, batch 4711 (B1)",
               "Composition per tablet:", "Drug X 10 mg (active)", "Lactose monohydrate 89 mg (filler)",
               "Magnesium stearate 1 mg (lubricant)",
               "Dissolution: USP 2 paddle at 50 rpm, 900 mL phosphate buffer pH 6.8, test product",
               "Time (min) Mean % dissolved (SD) n", "15 56.0 (2.0) 6", "30 84.0 (3.1) 6", "45 97.0 (1.2) 6"]
DISSOLUTION_REPORT = ["Dissolution report", "Product: Test 10 mg tablet, batch B1 (test product)",
                      "Apparatus: USP 2 paddle at 50 rpm", "Medium: 900 mL phosphate buffer pH 6.8, 37 C",
                      "Time (min) Mean % dissolved (SD) n", "15 55.0 (2.0) 6", "30 71.0 (3.1) 6", "45 97.0 (1.2) 6"]

DELIVERIES: tuple[Delivery, ...] = (
    Delivery("one study, two doses and two subject counts", (
        DeliveryFile("EX-101_protocol_PK.xlsx", _template(studies=[_study("EX-101", dose=10, n=14)], summary=_pk("EX-101", PK, 14))),
        DeliveryFile("EX-101_PK_sheet.xlsx", _template(studies=[_study("EX-101", dose=5, n=12)], summary=_pk("EX-101", PK, 12))),
    ), groups=("study:EX-101",), flags=("study:EX-101|dose_mg:conflict", "study:EX-101|n:difference"),
       notes=("study:EX-101|gives the same profile",)),
    Delivery("the same profile sent twice", (
        DeliveryFile("PK_v1.xlsx", _template(studies=[_study("EX-1")], summary=_pk("EX-1", PK))),
        DeliveryFile("PK_v2.xlsx", _template(studies=[_study("EX-1")], summary=_pk("EX-1", PK), note="sent again")),
    ), groups=("study:EX-1",), notes=("study:EX-1|gives the same profile",)),
    Delivery("one study written two ways, its profiles differing", (
        DeliveryFile("site_a.xlsx", _template(studies=[_study("EX-202")], summary=_pk("EX-202", PK))),
        DeliveryFile("site_b.xlsx", _template(studies=[_study("ex 202")], summary=_pk("ex 202", (18.0, 55.0, 31.0, 13.0, 4.2)))),
    ), groups=("study:EX-202",), flags=("study:EX-202|profile:conflict",), notes=("study:EX-202|Also called ex 202",)),
    Delivery("a study named at upload that its sheet calls otherwise", (
        DeliveryFile("Data_Q3_final.xlsx", _template(studies=[_study("Study 101")], summary=_pk("Study 101", PK)),
                     tag=("clinical", "EXZ-101")),
    ), groups=("study:Study 101",), flags=("link|Study 101:link",)),
    Delivery("a dissolution profile given twice, 14 points apart", (
        DeliveryFile("release.xlsx", _template(dissolution=_diss(85))),
        DeliveryFile("stability.xlsx", _template(dissolution=_diss(71))),
    ), groups=("product:Test 10 mg tablet",), flags=("product:Test 10 mg tablet|profile:conflict",)),
    # --- documents (build I4): read by the reading agent ------------------------------------------------------------
    Delivery("a Word protocol giving another dose than the PK sheet", (
        DeliveryFile("EX-301_PK.xlsx", _template(studies=[_study("EX-301", dose=5)], summary=_pk("EX-301", PK))),
        DeliveryFile("EX-301_synopsis.docx", lambda: synthetic_docx(SYNOPSIS), tag=("clinical", "EX-301"), reading=(
            ("propose_study_facts", {"study_id": "EX-301", "facts": [
                {"fact": "dose", "value": 10, "unit": "mg", "page": 1, "quote": "a single oral dose of 10 mg"},
                {"fact": "route", "value": "oral", "page": 1, "quote": "a single oral dose of 10 mg"},
                {"fact": "design", "value": "SD", "page": 1, "quote": "a single oral dose of 10 mg"},
                {"fact": "formulation", "value": "ir_tablet", "page": 1, "quote": "as one film-coated tablet"},
                {"fact": "food_state", "value": "fasted", "page": 1, "quote": "after an overnight fast of at least 10 hours"},
                {"fact": "n", "value": 12, "page": 1, "quote": "Twelve healthy subjects (n = 12)"}]}),)),
    ), groups=("study:EX-301",), flags=("study:EX-301|dose_mg:conflict",)),
    Delivery("a PDF protocol naming the study by its protocol number, the PK sheet by its code", (
        DeliveryFile("Study 101 PK.xlsx", _template(studies=[_study("Study 101")], summary=_pk("Study 101", PK))),
        DeliveryFile("protocol.pdf", lambda: synthetic_pdf([PROTOCOL]), tag=("clinical", ""), reading=(
            ("propose_study_facts", {"study_id": "EXZ-101", "facts": [
                {"fact": "dose", "value": 10, "unit": "mg", "page": 1, "quote": "a single oral dose of 10 mg"},
                {"fact": "n", "value": 12, "page": 1, "quote": "12 healthy subjects"}]}),
            ("propose_link", {"names": ["EXZ-101", "Study 101"], "page": 1, "quote": "Protocol EXZ-101 (Study 101)"}),)),
    ), groups=("study:EXZ-101", "study:Study 101"), flags=("link|Study 101:link",)),
    Delivery("a PDF dissolution report contradicting the workbook", (
        DeliveryFile("release.xlsx", _template(dissolution=_diss(85))),
        DeliveryFile("dissolution_report.pdf", lambda: synthetic_pdf([DISSOLUTION_REPORT]), tag=("formulation", ""), reading=(
            ("propose_dissolution", {
                "product": "Test 10 mg tablet", "product_quote": "Product: Test 10 mg tablet, batch B1 (test product)",
                "page": 1, "time_unit": "min", "header_quote": "Time (min) Mean % dissolved (SD) n",
                "conditions": [
                    {"field": "role", "value": "TEST", "quote": "Product: Test 10 mg tablet, batch B1 (test product)"},
                    {"field": "strength_mg", "value": 10, "quote": "Product: Test 10 mg tablet, batch B1 (test product)"},
                    {"field": "batch", "value": "B1", "quote": "Product: Test 10 mg tablet, batch B1 (test product)"},
                    {"field": "apparatus", "value": "USP 2 paddle", "quote": "Apparatus: USP 2 paddle at 50 rpm"},
                    {"field": "rpm", "value": 50, "quote": "Apparatus: USP 2 paddle at 50 rpm"},
                    {"field": "medium", "value": "phosphate", "quote": "Medium: 900 mL phosphate buffer pH 6.8"},
                    {"field": "ph", "value": 6.8, "quote": "Medium: 900 mL phosphate buffer pH 6.8"},
                    {"field": "volume_ml", "value": 900, "quote": "Medium: 900 mL phosphate buffer pH 6.8"}],
                "n": 6, "rows": [{"time": 15, "mean": 55, "sd": 2.0, "quote": "15 55.0 (2.0) 6"},
                                 {"time": 30, "mean": 71, "sd": 3.1, "quote": "30 71.0 (3.1) 6"},
                                 {"time": 45, "mean": 97, "sd": 1.2, "quote": "45 97.0 (1.2) 6"}]}),)),
    ), groups=("product:Test 10 mg tablet",), flags=("product:Test 10 mg tablet|profile:conflict",)),
    Delivery("a Word synopsis giving the subjects' demographics", (
        DeliveryFile("EX-302_PK.xlsx", _template(studies=[_study("EX-302")], summary=_pk("EX-302", PK))),
        DeliveryFile("EX-302_synopsis.docx", lambda: synthetic_docx(DEMOGRAPHICS), tag=("clinical", "EX-302"), reading=(
            ("propose_study_facts", {"study_id": "EX-302", "facts": [
                {"fact": "age_mean", "value": 31.5, "page": 1, "quote": "(mean age 31.5 years)"},
                {"fact": "age_min", "value": 24, "page": 1, "quote": "aged 24 to 41 years"},
                {"fact": "age_max", "value": 41, "page": 1, "quote": "aged 24 to 41 years"},
                {"fact": "weight_mean", "value": 76.2, "unit": "kg", "page": 1, "quote": "mean body weight was 76.2 kg"},
                {"fact": "females", "value": 0, "page": 1, "quote": "(12 men, 0 women)"},
                {"fact": "ethnicity", "value": "Caucasian", "page": 1, "quote": "Twelve healthy Caucasian subjects"}]}),)),
    ), groups=("study:EX-302",), flags=("study:EX-302|demographics:question",)),
    Delivery("one product written two ways in two workbooks, the same profile", (
        DeliveryFile("release.xlsx", _template(dissolution=_diss(85))),
        DeliveryFile("release_v2.xlsx", _template(dissolution=_diss(85, product="TEST 10 MG Tablet"))),
    ), groups=("product:TEST 10 MG Tablet",),
       notes=("product:TEST 10 MG Tablet|kept once", "product:TEST 10 MG Tablet|Also called Test 10 mg tablet")),
    Delivery("a certificate naming the batch by its lot number, with the composition", (
        DeliveryFile("release.xlsx", _template(dissolution=_diss(85))),
        DeliveryFile("certificate.pdf", lambda: synthetic_pdf([CERTIFICATE]), tag=("formulation", ""), reading=(
            ("propose_link", {"kind": "batch", "names": ["4711", "B1"], "page": 1, "quote": CERTIFICATE[0]}),
            ("propose_composition", {"product": "Test 10 mg tablet", "product_quote": CERTIFICATE[0], "page": 1,
                                     "components": [
                                         {"name": "Drug X", "amount": 10, "unit": "mg", "function": "active",
                                          "quote": "Drug X 10 mg (active)"},
                                         {"name": "Lactose monohydrate", "amount": 89, "unit": "mg", "function": "filler",
                                          "quote": "Lactose monohydrate 89 mg (filler)"},
                                         {"name": "Magnesium stearate", "amount": 1, "unit": "mg", "function": "lubricant",
                                          "quote": "Magnesium stearate 1 mg (lubricant)"}]}),
            ("propose_dissolution", {
                "product": "Test 10 mg tablet", "product_quote": CERTIFICATE[0], "page": 1, "time_unit": "min",
                "header_quote": "Time (min) Mean % dissolved (SD) n", "n": 6,
                "conditions": [
                    {"field": "role", "value": "TEST", "quote": CERTIFICATE[5]},
                    {"field": "strength_mg", "value": 10, "quote": CERTIFICATE[0]},
                    {"field": "batch", "value": "4711", "quote": CERTIFICATE[0]},
                    {"field": "apparatus", "value": "USP 2 paddle", "quote": CERTIFICATE[5]},
                    {"field": "rpm", "value": 50, "quote": CERTIFICATE[5]},
                    {"field": "medium", "value": "phosphate", "quote": CERTIFICATE[5]},
                    {"field": "ph", "value": 6.8, "quote": CERTIFICATE[5]},
                    {"field": "volume_ml", "value": 900, "quote": CERTIFICATE[5]}],
                "rows": [{"time": 15, "mean": 56, "sd": 2.0, "quote": "15 56.0 (2.0) 6"},
                         {"time": 30, "mean": 84, "sd": 3.1, "quote": "30 84.0 (3.1) 6"},
                         {"time": 45, "mean": 97, "sd": 1.2, "quote": "45 97.0 (1.2) 6"}]}),)),
    ), groups=("product:Test 10 mg tablet",), flags=("blink|4711:link",),
       notes=("product:Test 10 mg tablet|Composition as certificate.pdf reports it",)),
)


def _flag(issue: dict[str, Any]) -> str:
    """An issue as the answer names it: "<group>|<what>:<kind>" ("study:EX-101|dose_mg:conflict"), or a link question
    as "link|<the sheet's name>:link"."""
    scope, _, key = issue["id"].partition("|")
    return f"{scope}|{key if issue['kind'] == 'link' else key.split(':', 1)[0]}:{issue['kind']}"


def score(delivery: Delivery, ws: Any, *, by: str = "eval",
          read_documents: Callable[[Any, Any, str, DeliveryFile], None] | None = None) -> Score:
    """Read one delivery into an empty project workspace and compare what was found with the answer. A document is
    read by `read_documents(ws, library, submission id, file)`; a delivery with documents needs one."""
    from modeler_project.client_data import ingest
    from modeler_project.client_review import groups
    from modeler_project.documents import DocumentLibrary

    if delivery.needs_reader and read_documents is None:
        raise ValueError(f"{delivery.name}: its documents need a reader")
    library = DocumentLibrary(ws)
    for f in delivery.files:
        stored = ingest(ws, library, f.build(), f.name, by=by, tag=f.tag)
        if f.document and read_documents is not None:
            read_documents(ws, library, stored["id"], f)
    found = groups(ws)
    result = Score(delivery.name)
    ids = {g["id"] for g in found}
    flagged = {_flag(i) for g in found for i in g["issues"]}
    notes = {(g["id"], n) for g in found for n in g["notes"]}
    expected = [*(f"group {g}" for g in delivery.groups), *(f"flag {f}" for f in delivery.flags),
                *(f"note {n}" for n in delivery.notes)]
    for item in expected:
        what, _, key = item.partition(" ")
        hit = (key in ids if what == "group" else key in flagged if what == "flag"
               else any(g == key.split("|", 1)[0] and key.split("|", 1)[1] in n for g, n in notes))
        (result.found if hit else result.missed).append(item)
    result.unexpected = [f"group {g}" for g in sorted(ids - set(delivery.groups)) if g.startswith(("study:", "product:"))]
    result.unexpected += [f"flag {f}" for f in sorted(flagged - set(delivery.flags))]
    return result
