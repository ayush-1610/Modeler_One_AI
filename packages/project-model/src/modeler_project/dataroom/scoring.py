"""The Data room's values in the value scorer's long form (plan 2026-11-26 §5, §6): one row per value code read, so a
delivery read by the room is scored against an analysts' key (`value_key`, schema value-key/2) by the same scorer as
the intake pipeline (`modeler_project.value_score`, D0).

    uv run python -m modeler_project.value_score --root R --project P --key K.xlsx --source dataroom

`from_dataroom(ws)` reads the room's tables the way the room does (`assemble.read_extractions`): what is scored is what
the page shows, never a second reading. It gives, each as `value_score.Extracted`:

- every individual concentration of a concentrations table (`concentration`, one per subject, period and time; a value
  below the LLOQ censored, a missing sample with no value; the subject as the file writes it, as the key does);
- every per-subject PK parameter of a PK-parameters table (`pk.Cmax`, `pk.tmax`, `pk.AUC_last`, `pk.AUC_inf`,
  `pk.t_half`);
- every test/reference ratio of a BE-statistics table (`relation.test_vs_reference.<parameter>`);
- every dissolution profile's mean per time (`percent_dissolved`, statistic `mean`: computed from the units read, as
  the room shows it).

No anchor is given (the scorer joins on labels, never on the anchor; the intake's anchor form is the ledger's), so the
report names a value's file but not its sheet or page. Labels come from the table as the agent (or code, for a CDISC
dataset) described it: the study from its "study" constant or what it is about, the analyte from each line's analyte
cell (a PC dataset holds the drug and its metabolites) else the table's constant, the matrix from its constants, the
arm from each row's treatment, as written; the scorer's name matching and
the key's Studies sheet do the rest. Not yet given (phase 3 and later): demographics, solubility, composition and the
quoted facts; their key rows are then `missing`, which the report says.
"""

from __future__ import annotations

import re

from modeler_intake.source_model import number_text
from modeler_project.dataroom import DataRoomStore, room_inputs
from modeler_project.dataroom.assemble import read_extractions
from modeler_project.dataroom.clinical import samples_from
from modeler_project.dataroom.extract import parse_number
from modeler_project.dataroom.invitro import dissolution_views
from modeler_project.dataroom.model import ReadTable
from modeler_project.dataroom.observed import is_statistic
from modeler_project.value_key import format_conditions
from modeler_project.value_score import Extracted
from modeler_project.workspace import Workspace

METHOD = "dataroom"
# a PK-parameters table's column roles, as the ledger's field names
_PK_FIELDS = {"cmax": "pk.Cmax", "tmax": "pk.tmax", "auc_t": "pk.AUC_last", "auc_inf": "pk.AUC_inf", "t_half": "pk.t_half"}
_INF = re.compile(r"inf|∞|0\s*[-–]\s*i", re.IGNORECASE)


def _labels(table: ReadTable) -> dict[str, str]:
    desc = table.description
    const = {k.lower(): v.strip() for k, v in desc.constants.items()}
    return {"study": const.get("study", "") or desc.about.strip(), "analyte": const.get("analyte", ""),
            "matrix": const.get("matrix", "")}


def _concentrations(table: ReadTable) -> list[Extracted]:
    samples, _problems, unit = samples_from(table)
    labels = _labels(table)
    out = []
    for n, s in enumerate(samples):
        out.append(Extracted(
            file=table.description.file, study=labels["study"], arm=s.treatment, analyte=s.analyte or labels["analyte"],
            matrix=labels["matrix"], subject=s.subject_text or s.subject, period=s.period, sequence=s.sequence, field="concentration",
            time_min=round(s.time_h * 60.0, 6), value=None if s.value is None else number_text(s.value), verbatim=s.text,
            censored=s.blq, lloq=None, unit=unit or None, method=METHOD, anchor=None, id=f"{table.id}:c{n}"))
    return out


def _cells(table: ReadTable) -> list[dict[str, str]]:
    """Each data line's cells by role (the client's own summary lines left out)."""
    rows = []
    for row in table.rows:
        if row.summary:
            continue
        one = {c.role: c.text for c in row.cells}
        if is_statistic(one.get("subject", "")) or one.get("statistic", "").strip():
            continue
        rows.append(one)
    return rows


def _pk_parameters(table: ReadTable) -> list[Extracted]:
    labels = _labels(table)
    units = {c.role: c.unit for c in table.description.columns if c.unit}
    out = []
    for n, row in enumerate(_cells(table)):
        for role, field in _PK_FIELDS.items():
            text = row.get(role, "").strip()
            if not text:
                continue
            number = parse_number(text, decimal_comma=table.decimal_comma)
            out.append(Extracted(
                file=table.description.file, study=labels["study"], arm=row.get("treatment", "").strip(),
                analyte=row.get("analyte", "").strip() or labels["analyte"], matrix=labels["matrix"],
                subject=row.get("subject", "").strip(),
                period=row.get("period", "").strip(), sequence=row.get("sequence", "").strip(), field=field, time_min=None,
                value=None if number is None else number_text(number), verbatim=text, censored=False, lloq=None,
                unit=units.get(role) or None, method=METHOD, anchor=None, id=f"{table.id}:p{n}:{role}"))
    return out


def _pk_name(parameter: str) -> str | None:
    text = parameter.lower().replace(" ", "")
    if "cmax" in text:
        return "Cmax"
    if "auc" in text:
        return "AUC_inf" if _INF.search(text) else "AUC_last"
    return None


def _be_statistics(table: ReadTable) -> list[Extracted]:
    labels = _labels(table)
    out = []
    for n, row in enumerate(_cells(table)):
        name = _pk_name(row.get("parameter", ""))
        text = row.get("ratio", "").strip()
        if name is None or not text:
            continue
        number = parse_number(text.rstrip("%").strip(), decimal_comma=table.decimal_comma)
        out.append(Extracted(
            file=table.description.file, study=labels["study"], arm="", analyte=labels["analyte"], matrix=labels["matrix"],
            subject="", field=f"relation.test_vs_reference.{name}", time_min=None,
            value=None if number is None else number_text(number), verbatim=text, censored=False, lloq=None,
            unit="%" if text.endswith("%") else (table.description.value_unit or None), method=METHOD, anchor=None,
            id=f"{table.id}:be{n}"))
    return out


def _dissolution(table: ReadTable) -> list[Extracted]:
    views, _problems = dissolution_views(table)
    out = []
    for view in views:
        conditions = format_conditions({"medium": view.medium}) if view.medium else ""
        for t, mean in zip(view.times_min, view.mean, strict=False):
            out.append(Extracted(
                file=table.description.file, study="", arm="", analyte="", matrix="", subject="", product=view.product,
                batch=view.batch, conditions=conditions, field="percent_dissolved", time_min=round(t, 6),
                value=number_text(round(mean, 6)), verbatim="", censored=False, lloq=None, unit="%", method=METHOD,
                anchor=None, id=f"{view.id}:{t:g}", statistic="mean", n=str(view.n_units) if view.n_units else None))
    return out


_READERS = {"concentrations": _concentrations, "pk_parameters": _pk_parameters, "be_statistics": _be_statistics,
            "dissolution": _dissolution}


def from_dataroom(ws: Workspace) -> list[Extracted]:
    """Every value the project's Data room reads from its described tables, in the scorer's long form."""
    tables, _facts, _problems = read_extractions(room_inputs(DataRoomStore(ws)))
    out: list[Extracted] = []
    for table in tables:
        reader = _READERS.get(table.description.kind)
        if reader is not None:
            out += reader(table)
    return out


__all__ = ["METHOD", "from_dataroom"]
