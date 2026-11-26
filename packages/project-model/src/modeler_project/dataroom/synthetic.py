"""A synthetic client delivery for the Data room (software test data: the made-up Exampleamide, never client data).

A crossover study of a reference and a test tablet (one subject with every sample below the LLOQ, one withdrawn, one
missing its last sample), the client's own NCA (one AUC off by 2.5 %), demographics, dissolution of three products in
two media (the reformulated one levelling off below 95 %, one client mean row off), solubility, the composition side
by side, a synopsis PDF with the study's facts, a label and a cover letter. The API tests and the browser flows use it:

    files = delivery()                  # {path: bytes}, as a client would zip them
    data = delivery_zip()               # the same as one zip
    seed(store, by="e2e")               # what the agents would answer for it, written straight into the store

`seed` writes the question card, each file's triage and each used file's extraction (tables described, facts quoted),
exactly the forms the agents A6-A8 submit; code then reads and checks every value from the cells, as always.
"""

from __future__ import annotations

import io
import re
import zipfile
from typing import Any

from modeler_intake.room import document_parts
from modeler_intake.room_specs import (
    ChecklistItem,
    ColumnSpec,
    Extraction,
    Fact,
    FileTriage,
    ProductRef,
    QuestionCard,
    TableDescription,
)
from modeler_project.dataroom.store import DataRoomStore

FOLDER = "Exampleamide delivery"
REF, TEST, REFORM = "Refamide 100 mg", "Exampleamide 100 mg", "Exampleamide 100 mg reformulated"
TIMES = (0, 0.5, 1, 1.5, 2, 3, 4, 6, 8, 12, 24)
PROFILE = {"A": (0, 4.1, 9.8, 14.6, 16.9, 15.2, 12.4, 8.3, 5.6, 2.6, 0.6),
           "B": (0, 5.0, 11.2, 15.8, 17.1, 14.6, 11.7, 7.9, 5.2, 2.4, 0.55)}
LLOQ = 0.5
SUBJECTS = range(1, 9)
DISS_TIMES = (5, 10, 15, 30, 45, 60)
DISS = {"pH 6.8 phosphate buffer": {"LOT-R": (38, 58, 71, 86, 93, 97), "LOT-T": (45, 66, 79, 91, 96, 98),
                                    "LOT-X": (30, 47, 60, 76, 84, 87)},
        "pH 1.2 HCl": {"LOT-R": (80, 92, 96, 98, 99, 99), "LOT-T": (86, 95, 97, 99, 99, 99)}}
UNITS = {"pH 6.8 phosphate buffer": 12, "pH 1.2 HCl": 6}   # tablets per batch: f2 needs 12
SYNOPSIS = (
    "Clinical study report synopsis",
    "Study EX-01: an open two-period crossover in healthy adults",
    "Treatments: A = Refamide 100 mg (reference product); B = Exampleamide 100 mg (test product).",
    "Batches: LOT-R is Refamide 100 mg; LOT-T is Exampleamide 100 mg; LOT-X is Exampleamide 100 mg reformulated.",
    "Healthy male and female adults; all subjects were of Asian origin.",
    "Route: oral. Each subject received 100 mg with 240 mL of water after an overnight fast.",
    "Standardised meals were served at 4 h and 10 h after dosing.",
    "Subjects withdrawn: 4 (adverse event in period 2).",
    "Plasma was assayed by LC-MS/MS; LLOQ 0.5 ng/mL.",
    "Exampleamide: molecular weight 412.5 g/mol (free base); pKa 8.9 (basic).",
    "Dissolution: USP 2 paddle at 50 rpm in 900 mL of pH 6.8 phosphate buffer and of pH 1.2 HCl.",
)


def _value(trt: str, subject: int, period: int, k: int) -> str:
    factor = 0.8 + 0.05 * (subject - 1)
    if subject == 3 and period == 2:
        return "BLQ"                                    # every sample below the LLOQ: a possible non-absorber
    if subject == 4 and period == 2 and TIMES[k] > 4:
        return "."                                      # withdrawn after the 4 h sample
    if subject == 5 and period == 2 and TIMES[k] == 24:
        return "."                                      # the last sample missing
    x = round(PROFILE[trt][k] * factor, 2)
    return "0" if TIMES[k] == 0 else ("BLQ" if x < LLOQ else f"{x:g}")


def _sequence(subject: int) -> str:
    return "AB" if subject % 2 else "BA"


def _concentrations() -> tuple[str, list[tuple[int, int, str, list[str]]]]:
    rows = []
    for s in SUBJECTS:
        for period in (1, 2):
            trt = _sequence(s)[period - 1]
            rows.append((s, period, trt, [_value(trt, s, period, k) for k in range(len(TIMES))]))
    text = "Subject\tSequence\tPeriod\tTreatment\t" + "\t".join(f"{t:g}" for t in TIMES) + "\n"
    text += "".join(f"{s:03d}\t{_sequence(s)}\t{p}\t{t}\t" + "\t".join(v) + "\n" for s, p, t, v in rows)
    return text, rows


def _client_nca(values: list[str]) -> tuple[float, float, float] | None:
    """Cmax, Tmax and AUC0-t as the client computed them: the linear trapezoidal rule, BLQ before the first quantifiable
    sample as 0, after it left out."""
    ts, cs, seen = [], [], False
    for t, v in zip(TIMES, values, strict=True):
        if v == ".":
            continue
        x = None if v == "BLQ" else float(v)
        if x is not None and x > 0:
            seen = True
            ts.append(t)
            cs.append(x)
        elif not seen:
            ts.append(t)
            cs.append(0.0)
    if sum(1 for c in cs if c > 0) < 3:
        return None
    auc = sum((ts[i + 1] - ts[i]) * (cs[i] + cs[i + 1]) / 2 for i in range(len(ts) - 1))
    cmax = max(cs)
    return cmax, ts[cs.index(cmax)], auc


def _pk(rows: list[tuple[int, int, str, list[str]]]) -> str:
    text = "Subject\tPeriod\tTreatment\tCmax (ng/mL)\tTmax (h)\tAUC0-t (ng.h/mL)\n"
    for s, p, t, v in rows:
        got = _client_nca(v)
        if got is None:
            continue
        cmax, tmax, auc = got
        if s == 6 and p == 1:
            auc *= 1.025                                # the one value the client's file has off
        text += f"{s:03d}\t{p}\t{t}\t{cmax:g}\t{tmax:g}\t{auc:.2f}\n"
    return text


def _dissolution(medium: str) -> str:
    groups = DISS[medium]
    head1 = "Batch\t" + "\t".join(f"{g}" + "\t" * (len(DISS_TIMES) - 1) for g in groups)
    head2 = "Time (min)\t" + "\t".join("\t".join(str(t) for t in DISS_TIMES) for _ in groups)
    lines, means = [], {g: [0.0] * len(DISS_TIMES) for g in groups}
    n = UNITS[medium]
    for unit in range(1, n + 1):
        cells = []
        for g, base in groups.items():
            for i, b in enumerate(base):
                x = min(100.0, round(b + (unit - (n + 1) / 2) * 0.8, 1))
                means[g][i] += x / n
                cells.append(f"{x:g}")
        lines.append(f"{unit}\t" + "\t".join(cells))
    mean_cells = []
    for g in groups:
        for i, m in enumerate(means[g]):
            written = round(m, 1) + (1.5 if g == "LOT-X" and DISS_TIMES[i] == 30 else 0.0)   # the client's row off once
            mean_cells.append(f"{written:.1f}")
    return "\n".join([head1.rstrip("\t"), head2, *lines, "Mean\t" + "\t".join(mean_cells)]) + "\n"


def _demographics() -> str:
    text = "Subject\tSex\tAge (years)\tWeight (kg)\tHeight (cm)\n"
    for s in SUBJECTS:
        text += f"{s:03d}\t{'M' if s % 3 else 'F'}\t{24 + 2 * s}\t{58 + 1.5 * s:g}\t{160 + s:g}\n"
    return text


COMPOSITION = (f"Component\tFunction\t{REF}\t{TEST}\t{REFORM}\n"
               "Exampleamide\tactive\t100\t100\t100\n"
               "Microcrystalline cellulose\tfiller\t120\t120\t110\n"
               "Lactose monohydrate\tfiller\t60\t60\t60\n"
               "Crospovidone\tdisintegrant\t8\t8\t12\n"
               "Sodium lauryl sulfate\tsurfactant\t0\t0\t4\n"
               "Magnesium stearate\tlubricant\t2\t2\t2\n")
SOLUBILITY = "Medium\tpH\tSolubility (mg/mL)\nWater\t6.5\t0.21\n0.1 N HCl\t1.2\t4.8\nAcetate buffer\t4.5\t1.9\nPhosphate buffer\t6.8\t0.15\n"
LABEL = "# Exampleamide tablets: label extract\n\nMolecular weight: 412.5 g/mol\nPlasma protein binding: 97 %\n"
LETTER = "Dear modelling team\n\nplease find enclosed the delivery for the Exampleamide project.\nKind regards\n"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _pdf(lines: tuple[str, ...]) -> bytes:
    """A one-page PDF (Helvetica, text layer) of the lines."""
    ops = "\n".join(f"BT /F{2 if i == 0 else 1} {14 if i == 0 else 10} Tf 64 {740 - 22 * i - (8 if i else 0)} Td "
                    f"({_escape(line)}) Tj ET" for i, line in enumerate(lines)).encode("latin-1")
    objects = [b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
               b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
               (b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> "
                b"/Contents 6 0 R >> endobj\n"),
               b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >> endobj\n",
               b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >> endobj\n",
               f"6 0 obj << /Length {len(ops)} >> stream\n".encode() + ops + b"\nendstream endobj\n"]
    body, offsets = b"%PDF-1.4\n", []
    for obj in objects:
        offsets.append(len(body))
        body += obj
    xref = len(body)
    body += f"xref\n0 {len(offsets) + 1}\n0000000000 65535 f \n".encode()
    body += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    return body + f"trailer << /Size {len(offsets) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


def delivery() -> dict[str, bytes]:
    """The delivery's files by their path in the zip."""
    conc, rows = _concentrations()
    files = {"Clinical/EX-01 concentrations.tsv": conc, "Clinical/EX-01 PK parameters.tsv": _pk(rows),
             "Clinical/EX-01 demographics.tsv": _demographics(), "In vitro/Dissolution pH 6.8.tsv": _dissolution(
                 "pH 6.8 phosphate buffer"), "In vitro/Dissolution pH 1.2.tsv": _dissolution("pH 1.2 HCl"),
             "In vitro/Solubility.tsv": SOLUBILITY, "Formulation/Composition.tsv": COMPOSITION,
             "Literature/Label.md": LABEL, "Cover letter.txt": LETTER}
    out = {f"{FOLDER}/{k}": v.encode() for k, v in files.items()}
    out[f"{FOLDER}/Clinical/EX-01 synopsis.pdf"] = _pdf(SYNOPSIS)
    return out


def delivery_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, data in sorted(delivery().items()):
            archive.writestr(zipfile.ZipInfo(path, date_time=(2026, 11, 1, 9, 0, 0)), data)
    return buffer.getvalue()


# --- what the agents would answer -------------------------------------------------------------------------------------

QUESTION = QuestionCard(
    question="Does the reformulated Exampleamide tablet perform like the reference product in vivo?", regulator="Health Canada",
    approach="PBBM", context_of_use="A virtual bioequivalence check of the reformulated tablet against the reference",
    products=[ProductRef(name=REF, role="reference"), ProductRef(name=TEST, role="test"),
              ProductRef(name=REFORM, role="reformulated")],
    checklist=[ChecklistItem(id="D-concentrations", label="Individual concentrations of every arm", area="D",
                             topics=["clinical_concentrations"]),
               ChecklistItem(id="B-dissolution", label="Dissolution of every product in every medium", area="B",
                             topics=["dissolution"]),
               ChecklistItem(id="A-composition", label="Composition of every product", area="A", topics=["composition"]),
               ChecklistItem(id="C-particle-size", label="Particle size of the drug substance (d10, d50, d90)", area="C",
                             why="the reformulation changes the release; particle size explains it", topics=["particle_size"])])


def _c(index: int, role: str, **kw: object) -> ColumnSpec:
    return ColumnSpec(index=index, role=role, **kw)  # type: ignore[arg-type]


def _quote(field: str, value: str, quote: str, **kw: str) -> Fact:
    return Fact(field=field, value=value, quote=quote, **kw)


def answers(parts: dict[str, str]) -> tuple[list[FileTriage], list[Extraction]]:
    """The triage of every file and the extraction of every used file, given each file's first part name."""
    p = f"{FOLDER}/"
    conc, pk, dem = p + "Clinical/EX-01 concentrations.tsv", p + "Clinical/EX-01 PK parameters.tsv", p + "Clinical/EX-01 demographics.tsv"
    d68, d12, sol, comp = (p + "In vitro/Dissolution pH 6.8.tsv", p + "In vitro/Dissolution pH 1.2.tsv", p + "In vitro/Solubility.tsv",
                           p + "Formulation/Composition.tsv")
    syn, label, letter = p + "Clinical/EX-01 synopsis.pdf", p + "Literature/Label.md", p + "Cover letter.txt"
    triage = [FileTriage(path=conc, purpose="used", topics=["clinical_concentrations"], study="EX-01",
                         reason="The individual plasma concentrations of study EX-01, both periods."),
              FileTriage(path=pk, purpose="used", topics=["clinical_pk"], study="EX-01",
                         reason="The client's own Cmax, Tmax and AUC per subject and period."),
              FileTriage(path=dem, purpose="used", topics=["clinical_demographics"], study="EX-01",
                         reason="Sex, age, weight and height of every subject."),
              FileTriage(path=d68, purpose="used", topics=["dissolution"], products=[REF, TEST, REFORM],
                         reason="Dissolution of the three products in pH 6.8 buffer, twelve tablets each."),
              FileTriage(path=d12, purpose="used", topics=["dissolution"], products=[REF, TEST],
                         reason="Dissolution of the reference and test tablets in pH 1.2."),
              FileTriage(path=sol, purpose="used", topics=["solubility"], reason="Solubility of the drug in four media."),
              FileTriage(path=comp, purpose="used", topics=["composition"], products=[REF, TEST, REFORM],
                         reason="The composition of each product, side by side."),
              FileTriage(path=syn, purpose="used", topics=["clinical_design", "dosing_and_meals", "drug_substance"], study="EX-01",
                         reason="The study synopsis: design, treatments, batches, dosing, meals and exclusions."),
              FileTriage(path=label, purpose="context", topics=["label"], reason="The product label: molecular weight and binding."),
              FileTriage(path=letter, purpose="not_needed", topics=["other"],
                         reason="A cover letter: it holds no data the model needs.")]
    dtimes = [float(t) for t in DISS_TIMES]

    def dissolution(path: str, medium: str) -> TableDescription:
        groups = list(DISS[medium])
        cols = [_c(1, "unit")] + [_c(2 + g * len(dtimes) + i, "value", time=t, group=groups[g])
                                  for g in range(len(groups)) for i, t in enumerate(dtimes)]
        return TableDescription(file=path, kind="dissolution", part=parts[path], header_lines=[1, 2], first_line=3,
                                last_line=2 + UNITS[medium],
                                summary_lines={"mean": 3 + UNITS[medium]}, time_unit="min", value_unit="%", columns=cols,
                                constants={"medium": medium, "apparatus": "USP 2 paddle", "rpm": "50", "volume": "900 mL"})

    extractions = [
        Extraction(file=conc, tables=[TableDescription(
            file=conc, kind="concentrations", about="EX-01", part=parts[conc], header_lines=[1], first_line=2,
            last_line=1 + 2 * len(SUBJECTS), time_unit="h", value_unit="ng/mL",
            columns=[_c(1, "subject"), _c(2, "sequence"), _c(3, "period"), _c(4, "treatment")]
            + [_c(5 + i, "value", time=float(t)) for i, t in enumerate(TIMES)])]),
        Extraction(file=pk, tables=[TableDescription(
            file=pk, kind="pk_parameters", about="EX-01", part=parts[pk], header_lines=[1], first_line=2,
            last_line=_pk(_concentrations()[1]).count("\n"), value_unit="ng/mL",
            columns=[_c(1, "subject"), _c(2, "period"), _c(3, "treatment"), _c(4, "cmax"), _c(5, "tmax"), _c(6, "auc_t")])]),
        Extraction(file=dem, tables=[TableDescription(
            file=dem, kind="demographics", about="EX-01", part=parts[dem], header_lines=[1], first_line=2,
            last_line=1 + len(SUBJECTS), columns=[_c(1, "subject"), _c(2, "sex"), _c(3, "age", unit="years"),
                                                   _c(4, "weight", unit="kg"), _c(5, "height", unit="cm")])]),
        Extraction(file=d68, tables=[dissolution(d68, "pH 6.8 phosphate buffer")]),
        Extraction(file=d12, tables=[dissolution(d12, "pH 1.2 HCl")]),
        Extraction(file=sol, tables=[TableDescription(
            file=sol, kind="solubility", part=parts[sol], header_lines=[1], first_line=2, last_line=5, value_unit="mg/mL",
            columns=[_c(1, "medium"), _c(2, "ph"), _c(3, "solubility")])]),
        Extraction(file=comp, tables=[TableDescription(
            file=comp, kind="composition", part=parts[comp], header_lines=[1], first_line=2, last_line=7,
            columns=[_c(1, "component"), _c(2, "function"), _c(3, "amount", group=REF, unit="mg"),
                     _c(4, "amount", group=TEST, unit="mg"), _c(5, "amount", group=REFORM, unit="mg")])]),
        Extraction(file=syn, facts=[
            _quote("study.design", "two-period crossover", SYNOPSIS[1], subject="EX-01"),
            _quote("study.treatment_code", f"{REF} (reference product)", SYNOPSIS[2], subject="A", product=REF),
            _quote("study.treatment_code", f"{TEST} (test product)", SYNOPSIS[2], subject="B", product=TEST),
            _quote("product.batch", "LOT-R", "LOT-R is Refamide 100 mg", product=REF),
            _quote("product.batch", "LOT-T", "LOT-T is Exampleamide 100 mg;", product=TEST),
            _quote("product.batch", "LOT-X", "LOT-X is Exampleamide 100 mg reformulated", product=REFORM),
            _quote("study.population", "healthy", SYNOPSIS[4], subject="EX-01"),
            _quote("study.sex", "male and female", SYNOPSIS[4], subject="EX-01"),
            _quote("study.ethnicity", "Asian", SYNOPSIS[4], subject="EX-01"),
            _quote("study.route", "oral", "Route: oral.", subject="EX-01"),
            _quote("study.dose", "100", "Each subject received 100 mg", subject="EX-01", unit="mg"),
            _quote("study.water", "240", "with 240 mL of water", subject="EX-01", unit="mL"),
            _quote("study.fasting", "after an overnight fast", "after an overnight fast", subject="EX-01"),
            _quote("study.meal_times", "4 h and 10 h", SYNOPSIS[6], subject="EX-01", unit="h"),
            _quote("study.excluded_subjects", "4", SYNOPSIS[7], subject="EX-01", note="adverse event in period 2"),
            _quote("study.lloq", "0.5", "LLOQ 0.5 ng/mL", subject="EX-01", unit="ng/mL"),
            _quote("substance.mw", "412.5", "molecular weight 412.5 g/mol (free base)", unit="g/mol"),
            _quote("substance.pka", "8.9", "pKa 8.9 (basic)"),
        ]),
        Extraction(file=label, facts=[
            _quote("substance.mw", "412.5", "Molecular weight: 412.5 g/mol", unit="g/mol"),
            _quote("adme.fu", "97", "Plasma protein binding: 97 %", unit="%"),
        ]),
    ]
    return triage, extractions


def seed(store: DataRoomStore, *, by: str = "e2e-fixture", confirmed: bool = False) -> None:
    """What the agents would have answered for the delivery, written into a store whose files are read (the read stage
    ran): the question card (confirmed or not), every file's triage, every used file's extraction."""
    files = {f.path: f for f in store.files()}
    parts = {}
    for path, f in files.items():
        doc = store.doc(f.sha256) if not f.duplicate_of else None
        if doc is not None and (found := document_parts(doc)):
            parts[path] = found[0].name
    triage, extractions = answers(parts)
    store.set_question(QUESTION, by=by, confirmed=confirmed, reason="seeded" if confirmed else "")
    for t in triage:
        if t.path in files:
            store.put_triage(t, files[t.path].sha256)
    for e in extractions:
        if e.file in files:
            store.put_extraction(e, files[e.file].sha256, agent={"agent": "A8", "model": "recorded", "prompt": "synthetic"})


# --- scoring a room against these answers -----------------------------------------------------------------------------


def score_room(got: Any, key: Any) -> list[tuple[str, str, object, object]]:
    """A room (`room_view`, from a model's run on this delivery) value by value against the room from the hand-written
    answers above (`seed`, confirmed): rows of (OK | WRONG | MISSING, what, the key's value, the room's). Exposures, means
    and solubility within 0.5 %, f2 within 1 %; everything else equal. The question card scores its products and roles
    and its regulator (only as a file states it: none here); each study its sets, exposures, arms and facts; then dissolution, f2, solubility and substance."""
    rows: list[tuple[str, str, object, object]] = []

    def words(text: str) -> str:
        return " ".join(re.findall(r"[a-z0-9.]+", text.lower()))

    def add(what: str, value: object, expected: object, tol: float = 0.005) -> None:
        if isinstance(value, str) and isinstance(expected, str) and words(expected):
            # a fact as the delivery words it: the key's words, in order, inside what the room read ("open two-period
            # crossover" holds "two-period crossover"; "healthy adults" holds "healthy")
            ok = f" {words(expected)} " in f" {words(value)} "
        elif isinstance(value, float) and isinstance(expected, float):
            ok = abs(value - expected) <= tol * max(abs(expected), 1e-9)
        elif isinstance(value, tuple) and isinstance(expected, tuple) and len(value) == len(expected) and all(
                isinstance(v, float) for v in (*value, *expected)):
            ok = all(abs(v - e) <= tol * max(abs(e), 1e-9) for v, e in zip(value, expected, strict=True))
        else:
            ok = value == expected
        rows.append(("OK" if ok else "MISSING" if value in (None, "", (), []) else "WRONG", what, expected, value))

    def products(view: Any) -> tuple[tuple[str, str], ...] | None:
        return tuple(sorted((p.name, p.role) for p in view.question.products)) if view.question else None

    add("question card: products and roles", products(got), products(key))
    # the agency only as a file states it: this delivery names none, so the right card leaves it empty
    stated = key.question.regulator if any(f.field == "question.regulator" for f in key.question.quotes) else ""
    add("question card: regulator, as a file states it", got.question.regulator if got.question else None, stated)
    for ks in key.studies:
        s = next((x for x in got.studies if x.study_id.replace(" ", "").lower() == ks.study_id.replace(" ", "").lower()), None)
        add(f"study {ks.study_id} found", s is not None, True)
        for kset in ks.sets:
            add(f"{ks.study_id} set {kset.name} (subjects)",
                next((len(x.subjects) for x in s.sets if x.name == kset.name), None) if s else None, len(kset.subjects))
        for ke in ks.exposures:
            add(f"{ks.study_id} {ke.treatment} {ke.metric} {ke.statistic}",
                next((e.value for e in s.exposures if (e.treatment, e.metric, e.statistic) == (ke.treatment, ke.metric,
                                                                                               ke.statistic)), None)
                if s else None, ke.value)
        add(f"{ks.study_id} arms (treatment, role, product)",
            tuple(sorted((a.treatment, a.role, a.product or "") for a in s.arms)) if s else None,
            tuple(sorted((a.treatment, a.role, a.product or "") for a in ks.arms)))
        for kv in ks.facts:
            add(f"{ks.study_id} {kv.key}", next((v.value for v in s.facts if v.key == kv.key), None) if s else None, kv.value)
    for kd in key.dissolution:
        d = next((x for x in got.dissolution if x.batch == kd.batch and x.ph == kd.ph), None)
        add(f"dissolution {kd.batch} pH {kd.ph:g} means", d.mean if d else None, kd.mean)
    def batch(view: Any, dataset: str) -> str:          # a dissolution's id names its cells: the batch and pH name it here
        d = next((x for x in view.dissolution if x.id == dataset), None)
        return f"{d.batch} pH {d.ph:g}" if d is not None and d.ph is not None else dataset

    got_f2 = {(batch(got, f.test), batch(got, f.reference)): f for f in got.f2}
    for kf in key.f2:      # a pair f2 does not apply to has no value: the pair itself is what is scored then
        pair = (batch(key, kf.test), batch(key, kf.reference))
        if (f := got_f2.get(pair)) is None:
            rows.append(("MISSING", f"f2 {pair[0]} vs {pair[1]}", kf.value, None))
        else:
            add(f"f2 {pair[0]} vs {pair[1]}", f.value, kf.value, tol=0.01)
    for ks in key.solubility:
        add(f"solubility pH {ks.ph:g}", next((x.solubility_mg_ml for x in got.solubility if x.ph == ks.ph), None),
            ks.solubility_mg_ml)
    def base(name: str) -> str:            # "substance.mw[Exampleamide]" and "substance.mw" name the same value here
        return name.split("[", 1)[0]

    for kv in key.substance:
        add(f"substance {base(kv.key)}", next((v.value for v in got.substance if base(v.key) == base(kv.key)), None),
            kv.value)
    return rows


# --- a CRO's SDTM PC dataset (plan 2026-11-26 §7 phase 2b) -------------------------------------------------------------
# Made up, in the shape such a dataset has: one line per sample, the drug and its metabolite M1 line by line, two
# studies (EX-02, EX-03) pooled and sorted by STUDYID, each subject in two periods named by PCGRPID ("Period 1"), the
# planned time in PCTPTNUM running on across visits (the 24 h sample is on "Day 2"), below the LLOQ written "<0.50", one
# missing sample "MS" on a NOT DONE line. `test_dataroom_cdisc` describes it by code; its SAS transport twin is
# tests/fixtures/dataroom/pc_two_analytes.xpt (made with pyreadstat 1.3.7 from these lines).

PC_VARIABLES = ("STUDYID", "DOMAIN", "USUBJID", "PCSEQ", "PCGRPID", "PCTESTCD", "PCTEST", "PCSTRESC", "PCSTRESN",
                "PCSTRESU", "PCSTAT", "PCREASND", "PCSPEC", "VISIT", "PCTPT", "PCTPTNUM")
PC_STUDIES = ("EX-02", "EX-03")
PC_ANALYTES = (("EXA", "Exampleamide"), ("EXAM1", "Exampleamide-M1 Metabolite"))
PC_TIMES = (("Pre-dose", 0.0, "Day 1"), ("0.5 h", 0.5, "Day 1"), ("1 h", 1.0, "Day 1"), ("2 h", 2.0, "Day 1"),
            ("4 h", 4.0, "Day 1"), ("8 h", 8.0, "Day 1"), ("24 h", 24.0, "Day 2"))


def _pc_conc(subject: int, period: str, code: str, t: float) -> float:
    import math

    if t == 0:
        return 0.0
    c = 50 * (math.exp(-0.1 * t) - math.exp(-1.5 * t)) * (1 + 0.1 * subject) * (1.0 if period == "Period 1" else 0.95)
    return round(c * (0.08 if code == "EXAM1" else 1.0), 3)


def pc_dataset_rows() -> list[dict[str, str]]:
    """The made-up SDTM PC dataset, one dict per line (variable -> value as the dataset writes it)."""
    rows = []
    for study in PC_STUDIES:
        seq = 0
        for s in (1, 2, 3):
            for period in ("Period 1", "Period 2"):
                for code, name in PC_ANALYTES:
                    for tpt, t, visit in PC_TIMES:
                        seq += 1
                        c = _pc_conc(s, period, code, t)
                        missing = (s, period, code, t) == (2, "Period 2", "EXA", 8.0)
                        text = "MS" if missing else ("<0.50" if c < 0.5 else f"{c:g}")
                        rows.append({"STUDYID": study, "DOMAIN": "PC", "USUBJID": f"{study}-00{s}", "PCSEQ": str(seq),
                                     "PCGRPID": period, "PCTESTCD": code, "PCTEST": name, "PCSTRESC": text,
                                     "PCSTRESN": "" if missing or c < 0.5 else f"{c:g}",
                                     "PCSTRESU": "" if missing else "ng/mL", "PCSTAT": "NOT DONE" if missing else "",
                                     "PCREASND": "MISSING" if missing else "", "PCSPEC": "PLASMA",
                                     "VISIT": f"{period} {visit}", "PCTPT": tpt, "PCTPTNUM": f"{t:g}"})
    return rows


def dataset_csv(rows: list[dict[str, str]], variables: tuple[str, ...] = PC_VARIABLES) -> bytes:
    """A dataset's lines as its CSV export (variables in line 1)."""
    import csv

    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(variables), extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode()


# the same studies' SDTM EX: EX-02 gives each subject 100 mg in period 1 and 50 mg in period 2 (the design's doses);
# EX-03 gives each subject its own dose, the same in both periods (individualised, as by weight). The period is in
# EXTPT ("PERIOD 1"), as the CRO's delivery of 2026-11-26 wrote it.
EX_VARIABLES = ("STUDYID", "DOMAIN", "USUBJID", "EXSEQ", "EXTRT", "EXDOSE", "EXDOSU", "EXDOSFRM", "EXDOSFRQ", "EXROUTE",
                "EPOCH", "EXTPT")
EX_DOSES = {"EX-02": {1: ("100", "50"), 2: ("100", "50"), 3: ("100", "50")},
            "EX-03": {1: ("98.5", "98.5"), 2: ("104", "104"), 3: ("111.5", "111.5")}}


def ex_dataset_rows() -> list[dict[str, str]]:
    rows = []
    for study in PC_STUDIES:
        seq = 0
        for s in (1, 2, 3):
            for k, period in enumerate(("PERIOD 1", "PERIOD 2")):
                seq += 1
                rows.append({"STUDYID": study, "DOMAIN": "EX", "USUBJID": f"{study}-00{s}", "EXSEQ": str(seq),
                             "EXTRT": "EXAMPLEAMIDE", "EXDOSE": EX_DOSES[study][s][k], "EXDOSU": "mg",
                             "EXDOSFRM": "TABLET", "EXDOSFRQ": "ONCE", "EXROUTE": "ORAL", "EPOCH": "TREATMENT",
                             "EXTPT": period})
    return rows


# the same studies' SDTM PP: the client's NCA (CMAX, TMAX, AUCLST) of the drug and of M1 (named "EXAMPLEAMIDE-M1", not
# as PC names it), plus a model-based CMAX line (PPSCAT "1 Compartment") that is not the client's NCA. EX-03 gives each
# parameter twice per period (VISIT Day 1 and Day 2): not one value per profile.
PP_VARIABLES = ("STUDYID", "DOMAIN", "USUBJID", "PPSEQ", "PPGRPID", "PPTESTCD", "PPTEST", "PPCAT", "PPSCAT", "PPSTRESC",
                "PPSTRESN", "PPSTRESU", "VISIT")


def pp_dataset_rows() -> list[dict[str, str]]:
    rows = []
    for study in PC_STUDIES:
        seq = 0
        for s in (1, 2, 3):
            for period in ("Period 1", "Period 2"):
                for cat, code in (("EXAMPLEAMIDE", "EXA"), ("EXAMPLEAMIDE-M1", "EXAM1")):
                    peak = max(_pc_conc(s, period, code, t) for _tpt, t, _v in PC_TIMES)
                    values = [("CMAX", "Max Conc", f"{peak:g}", "ng/mL", "Non-Compartmental"),
                              ("TMAX", "Time of CMAX", "2", "h", "Non-Compartmental"),
                              ("AUCLST", "AUC to Last Nonzero Conc", f"{round(peak * 9.1, 2):g}", "h*ng/mL",
                               "Non-Compartmental"),
                              ("CMAX", "Max Conc", f"{round(peak * 1.07, 3):g}", "ng/mL", "1 Compartment")]
                    for visit in (("Day 1", "Day 2") if study == "EX-03" else ("",)):
                        for testcd, test, value, unit, method in values:
                            seq += 1
                            rows.append({"STUDYID": study, "DOMAIN": "PP", "USUBJID": f"{study}-00{s}", "PPSEQ": str(seq),
                                         "PPGRPID": period, "PPTESTCD": testcd, "PPTEST": test, "PPCAT": cat,
                                         "PPSCAT": method, "PPSTRESC": value, "PPSTRESN": value, "PPSTRESU": unit,
                                         "VISIT": f"{period} {visit}".strip() if visit else ""})
    return rows
