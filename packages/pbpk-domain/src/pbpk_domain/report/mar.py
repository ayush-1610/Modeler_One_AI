"""The Modeling Analysis Report (MAR), ICH M15 Appendix 2 — structure, evidence and rendering (T-24).

Design principle (M15 / Part 11 reviewability): the report's prose contains no free-standing numbers.
Every quantitative statement is a reference token — ``{{value:id}}``, ``{{table:id}}`` or ``{{figure:id}}`` —
resolved at render time from an ``Evidence`` set built from the campaign's own artifacts (final CPF, MAP,
evaluation metrics, reproducibility bundle). ``check_report`` enforces two invariants that mirror the T-24
acceptance: every referenced id resolves ("contains every table/figure referenced"), and no numeric literal
appears in prose outside a resolved reference ("no number in the text that is not in evidence").
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict

from pbpk_domain.m15 import AssessmentTable, Rating

# A reference token: {{value:auc_gmfe_s2}}, {{table:parameters}}, {{figure:gof_s2}}, or the block {{signatures}}.
_TOKEN_RE = re.compile(r"\{\{\s*(value|table|figure|signatures)\s*(?::\s*([A-Za-z0-9_.\-]+))?\s*\}\}")
# A bare numeric CLAIM in prose: a freestanding number, not digits embedded in an identifier or term. The
# look-arounds exclude a digit-run touching a letter, digit or hyphen on either side, so "2-fold", "S2",
# "ICH M15" and "CYP3A4" are not claims, while a standalone "1.3" or "95" is.
_NUMBER_RE = re.compile(r"(?<![\w-])\d+(?:[.,]\d+)*(?![\w-])")


class ValueRef(BaseModel):
    """A single number that must trace to a computed artifact; rendered inline in the prose."""
    model_config = ConfigDict(frozen=True)
    id: str
    value: float | int | str
    unit: str | None = None
    source: str  # provenance, e.g. "evaluate_round S2 / AUC GMFE"
    precision: int = 4  # significant figures used when rendering a float

    def rendered(self) -> str:
        return format_number(self.value, self.precision) + (_unit_suffix(self.unit))


class TableRef(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    title: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    source: str = ""


class FigureRef(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    title: str
    path: str  # path within the bundle the reviewer receives
    caption: str = ""
    source: str = ""


class Evidence(BaseModel):
    """The set of values, tables and figures the report may reference. Ordered for a stable evidence index."""
    model_config = ConfigDict(frozen=True)
    values: tuple[ValueRef, ...] = ()
    tables: tuple[TableRef, ...] = ()
    figures: tuple[FigureRef, ...] = ()

    def value(self, id: str) -> ValueRef | None:
        return next((v for v in self.values if v.id == id), None)

    def table(self, id: str) -> TableRef | None:
        return next((t for t in self.tables if t.id == id), None)

    def figure(self, id: str) -> FigureRef | None:
        return next((f for f in self.figures if f.id == id), None)

    def has(self, kind: str, id: str) -> bool:
        return {"value": self.value, "table": self.table, "figure": self.figure}[kind](id) is not None


class MarSection(BaseModel):
    model_config = ConfigDict(frozen=True)
    number: str  # "1", "2.1"
    heading: str
    body: str = ""  # markdown prose with {{...}} reference tokens
    subsections: tuple[MarSection, ...] = ()
    verbatim: bool = False  # a quoted input (e.g. the signed objective); exempt from the number/reference linter


class MarSignature(BaseModel):
    model_config = ConfigDict(frozen=True)
    printed_name: str
    meaning: str
    signed_at: datetime
    signature_id: str | None = None
    content_sha256: str = ""

    def manifestation(self) -> str:
        return f"{self.printed_name} | {self.meaning} | {self.signed_at.strftime('%Y-%m-%d %H:%M:%S %Z') or self.signed_at.isoformat()}"


class MarDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    compound: str
    title: str
    question_of_interest: str
    context_of_use: str
    model_risk: Rating
    sections: tuple[MarSection, ...]
    evidence: Evidence
    m15_tables: tuple[AssessmentTable, ...] = ()
    signatures: tuple[MarSignature, ...] = ()
    engine_image_digest: str = ""
    software_versions: dict[str, str] = {}
    bundle_sha256: str | None = None
    generated_at: datetime | None = None

    def content_sha256(self) -> str:
        content = self.model_dump(mode="json", exclude={"signatures", "generated_at"})
        return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class ReportIssue(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: str  # "unresolved_reference" | "unreferenced_number" | "unused_evidence"
    location: str  # section number, or "evidence"
    detail: str


class ReportError(Exception):
    def __init__(self, issues: list[ReportIssue]):
        self.issues = issues
        super().__init__("; ".join(f"[{i.kind}] {i.location}: {i.detail}" for i in issues))


# --- formatting helpers --------------------------------------------------------------------------


def format_number(value: float | str, precision: int = 4) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, int) or (isinstance(value, float) and value.is_integer()):
        return str(int(value))
    return f"{value:.{precision}g}"


def _unit_suffix(unit: str | None) -> str:
    if not unit:
        return ""
    return unit if unit in {"%"} else f" {unit}"


def _iter_sections(sections: tuple[MarSection, ...]):
    for section in sections:
        yield section
        yield from _iter_sections(section.subsections)


# --- validation (the T-24 acceptance invariants) -------------------------------------------------


def check_report(doc: MarDocument, *, require_all_evidence_used: bool = False) -> list[ReportIssue]:
    """Return every reviewability violation. Empty list means the report renders and is fully traceable."""
    issues: list[ReportIssue] = []
    referenced: set[tuple[str, str]] = set()

    for section in _iter_sections(doc.sections):
        if section.verbatim:
            continue  # a quoted input: not the report's own numeric claim
        for kind, id in _references(section.body):
            if kind == "signatures":
                continue
            referenced.add((kind, id))
            if not doc.evidence.has(kind, id):
                issues.append(ReportIssue(kind="unresolved_reference", location=section.number,
                                          detail=f"no {kind} evidence with id {id!r}"))
        for literal in _bare_numbers(section.body):
            issues.append(ReportIssue(kind="unreferenced_number", location=section.number,
                                      detail=f"bare number {literal!r} in prose; express it as a {{{{value:...}}}} reference"))

    if require_all_evidence_used:
        for pool, kind in ((doc.evidence.values, "value"), (doc.evidence.tables, "table"), (doc.evidence.figures, "figure")):
            for item in pool:
                if (kind, item.id) not in referenced:
                    issues.append(ReportIssue(kind="unused_evidence", location="evidence",
                                              detail=f"{kind} {item.id!r} is in evidence but never referenced"))
    return issues


def _references(body: str) -> list[tuple[str, str]]:
    return [(m.group(1), m.group(2)) for m in _TOKEN_RE.finditer(body) if m.group(1) == "signatures" or m.group(2)]


def _bare_numbers(body: str) -> list[str]:
    """Numeric literals left in prose once every reference token is removed."""
    return _NUMBER_RE.findall(_TOKEN_RE.sub("", body))


# --- rendering -----------------------------------------------------------------------------------


def render_markdown(doc: MarDocument, *, strict: bool = True) -> str:
    """Render the MAR to Markdown (Pandoc input). With ``strict`` (default), raises ``ReportError`` if any
    reference is unresolved or any bare number remains — the report is not allowed to render otherwise."""
    if strict:
        issues = check_report(doc)
        if issues:
            raise ReportError(issues)

    counters = {"table": 0, "figure": 0}
    numbers: dict[tuple[str, str], int] = {}
    out: list[str] = [f"# {doc.title}", ""]
    out += _front_matter(doc)

    for section in doc.sections:
        out += _render_section(section, doc, counters, numbers, depth=2)

    if doc.m15_tables:
        out += ["", "## ICH M15 assessment tables", ""]
        for i, table in enumerate(doc.m15_tables, start=1):
            out += _render_m15_table(i, table)

    out += _render_evidence_index(doc)

    if doc.signatures:
        out += ["", "## Signatures", ""]
        for sig in doc.signatures:
            out += [f"- {sig.manifestation()}"
                    + (f" (signature {sig.signature_id})" if sig.signature_id else ""), ""]
    return "\n".join(out).rstrip() + "\n"


def _front_matter(doc: MarDocument) -> list[str]:
    lines = [
        f"**Compound:** {doc.compound}  ",
        f"**Question of interest:** {doc.question_of_interest}  ",
        f"**Context of use:** {doc.context_of_use}  ",
        f"**Model risk (ICH M15):** {doc.model_risk.value}  ",
    ]
    if doc.engine_image_digest:
        lines.append(f"**Engine image:** {doc.engine_image_digest}  ")
    if doc.software_versions:
        versions = ", ".join(f"{k} {v}" for k, v in sorted(doc.software_versions.items()))
        lines.append(f"**Software:** {versions}  ")
    if doc.bundle_sha256:
        lines.append(f"**Reproducibility bundle:** sha256 {doc.bundle_sha256}  ")
    if doc.generated_at:
        lines.append(f"**Generated:** {doc.generated_at.isoformat()}  ")
    return [*lines, ""]


def _render_section(section: MarSection, doc: MarDocument, counters, numbers, depth: int) -> list[str]:
    out = ["#" * min(depth, 6) + f" {section.number} {section.heading}", ""]
    if section.body.strip():
        rendered = section.body if section.verbatim else _render_body(section.body, doc, counters, numbers)
        out += [rendered, ""]
    for sub in section.subsections:
        out += _render_section(sub, doc, counters, numbers, depth + 1)
    return out


def _render_body(body: str, doc: MarDocument, counters, numbers) -> str:
    def replace(match: re.Match) -> str:
        kind, id = match.group(1), match.group(2)
        if kind == "signatures":
            return "\n".join(f"- {s.manifestation()}" for s in doc.signatures) or "_(unsigned)_"
        if kind == "value":
            ref = doc.evidence.value(id)
            return ref.rendered() if ref else match.group(0)
        # a table or figure: assign a stable number on first sight, then embed it
        key = (kind, id)
        if key not in numbers:
            counters[kind] += 1
            numbers[key] = counters[kind]
        n = numbers[key]
        if kind == "table":
            table = doc.evidence.table(id)
            return "\n" + _render_table(n, table) if table else match.group(0)
        figure = doc.evidence.figure(id)
        return "\n" + _render_figure(n, figure) if figure else match.group(0)

    return _TOKEN_RE.sub(replace, body)


def _render_table(n: int, table: TableRef) -> str:
    head = "| " + " | ".join(table.columns) + " |"
    rule = "| " + " | ".join("---" for _ in table.columns) + " |"
    rows = ["| " + " | ".join(str(c) for c in row) + " |" for row in table.rows]
    return "\n".join([f"**Table {n}. {table.title}**", "", head, rule, *rows, ""])


def _render_figure(n: int, figure: FigureRef) -> str:
    caption = f" {figure.caption}" if figure.caption else ""
    return "\n".join([f"![{figure.title}]({figure.path})", "", f"**Figure {n}. {figure.title}.**{caption}", ""])


def _render_m15_table(n: int, table: AssessmentTable) -> list[str]:
    def rated(field: str) -> str:
        el = getattr(table, field)
        rating = el.rating.value if el.rating else "—"
        return f"| {field.replace('_', ' ')} | {rating} | {el.description or '—'} | {el.justification or '—'} |"

    out = [f"**M15 Table {n}. {table.question_of_interest or 'Question of interest'}**", "",
           f"Context of use: {table.context_of_use or '—'}", "",
           "| Element | Rating | Description | Justification |", "| --- | --- | --- | --- |"]
    for field in ("model_influence", "consequence_of_wrong_decision", "model_risk", "model_impact"):
        out.append(rated(field))
    out.append("")
    return out


def _render_evidence_index(doc: MarDocument) -> list[str]:
    out = ["", "## Evidence index", "",
           "Every quantitative statement above resolves to an entry here.", "",
           "| Reference | Value / title | Source |", "| --- | --- | --- |"]
    for v in doc.evidence.values:
        out.append(f"| value:{v.id} | {v.rendered()} | {v.source} |")
    for t in doc.evidence.tables:
        out.append(f"| table:{t.id} | {t.title} | {t.source} |")
    for f in doc.evidence.figures:
        out.append(f"| figure:{f.id} | {f.title} | {f.source} |")
    out.append("")
    return out


# --- assembly from campaign artifacts ------------------------------------------------------------


def assemble_mar(
    *,
    compound: str,
    question_of_interest: str,
    context_of_use: str,
    model_risk: Rating,
    parameters: tuple[TableRef, ...] | TableRef,
    stage_assessments: list[tuple[str, dict]],
    figures: tuple[FigureRef, ...] = (),
    m15_tables: tuple[AssessmentTable, ...] = (),
    signatures: tuple[MarSignature, ...] = (),
    engine_image_digest: str = "",
    software_versions: dict[str, str] | None = None,
    bundle_sha256: str | None = None,
    generated_at: datetime | None = None,
) -> MarDocument:
    """Build a MAR (M15 Appendix 2 skeleton) from campaign artifacts.

    ``parameters`` is the final CPF rendered as a table; ``stage_assessments`` is a list of
    ``(stage, RoundAssessment.metrics)`` from the passing round of each stage. Evidence values are derived
    from the metrics (GMFE, fraction within 2-fold, acceptance tier) so the prose can reference them without
    stating any number directly.
    """
    param_tables = (parameters,) if isinstance(parameters, TableRef) else tuple(parameters)
    values: list[ValueRef] = []
    tables: list[TableRef] = list(param_tables)
    eval_lines: list[str] = []

    tier_seen: str | None = None
    for stage, metrics in stage_assessments:
        tier_seen = metrics.get("tier", tier_seen)
        study_table = _study_pk_table(stage, metrics)
        tables.append(study_table)
        for quantity in ("AUC", "Cmax"):
            q = metrics.get(quantity)
            if not q:
                continue
            gmfe_id = f"{quantity.lower()}_gmfe_{stage.lower()}"
            frac_id = f"{quantity.lower()}_within2fold_{stage.lower()}"
            values.append(ValueRef(id=gmfe_id, value=q["gmfe"], source=f"evaluate_round {stage} / {quantity} GMFE"))
            values.append(ValueRef(id=frac_id, value=q["fraction_within_2fold"] * 100.0, unit="%", precision=3,
                                   source=f"evaluate_round {stage} / {quantity} fraction within 2-fold"))
        prose = " ".join(
            f"The {quantity} geometric mean fold error is {{{{value:{quantity.lower()}_gmfe_{stage.lower()}}}}} "
            f"with {{{{value:{quantity.lower()}_within2fold_{stage.lower()}}}}} of predictions within 2-fold."
            for quantity in ("AUC", "Cmax") if metrics.get(quantity)
        )
        eval_lines.append(
            f"Model performance for stage {stage} is summarised below.\n\n"
            f"{{{{table:{study_table.id}}}}}\n\n{prose}"
        )

    if tier_seen:
        values.append(ValueRef(id="acceptance_tier", value=tier_seen, source="acceptance ruleset (M15 model-risk tier)"))

    param_refs = " ".join(f"{{{{table:{t.id}}}}}" for t in param_tables)
    figure_refs = " ".join(f"{{{{figure:{f.id}}}}}" for f in figures)

    sections = (
        MarSection(number="1", heading="Objective and context of use", verbatim=True,
                   body=f"{question_of_interest}\n\n{context_of_use}"),
        MarSection(number="2", heading="Model description",
                   body="The compound parameter framework and the origin of every parameter are given below.\n\n"
                        + param_refs),
        MarSection(number="3", heading="Model evaluation",
                   body=("\n\n".join(eval_lines) if eval_lines else "No evaluated stages were supplied.")
                   + (f"\n\nGoodness-of-fit is shown below.\n\n{figure_refs}" if figures else "")),
        MarSection(number="4", heading="Conclusion",
                   body=("The model meets the acceptance criteria of the {{value:acceptance_tier}} tier for the "
                         "stated context of use." if tier_seen
                         else "Acceptance could not be determined from the supplied artifacts.")),
        MarSection(number="5", heading="Assumptions and limitations",
                   body="Assumptions and limitations are recorded in the ICH M15 assessment tables below."),
    )

    return MarDocument(
        compound=compound,
        title=f"Modeling Analysis Report — {compound}",
        question_of_interest=question_of_interest,
        context_of_use=context_of_use,
        model_risk=model_risk,
        sections=sections,
        evidence=Evidence(values=tuple(values), tables=tuple(tables), figures=tuple(figures)),
        m15_tables=m15_tables,
        signatures=signatures,
        engine_image_digest=engine_image_digest,
        software_versions=software_versions or {},
        bundle_sha256=bundle_sha256,
        generated_at=generated_at or datetime.now(UTC),
    )


def _study_pk_table(stage: str, metrics: dict) -> TableRef:
    columns = ("Study", "Role", "Pred AUC", "Obs AUC", "Pred Cmax", "Obs Cmax", "AUC in limits", "Cmax in limits")
    rows = []
    for s in metrics.get("studies", []):
        rows.append((
            s["study_id"], str(s.get("role", "")),
            format_number(s.get("predicted_auc")) if s.get("predicted_auc") is not None else "—",
            format_number(s.get("observed_auc")) if s.get("observed_auc") is not None else "—",
            format_number(s.get("predicted_cmax")) if s.get("predicted_cmax") is not None else "—",
            format_number(s.get("observed_cmax")) if s.get("observed_cmax") is not None else "—",
            _tick(s.get("auc_in_limits")), _tick(s.get("cmax_in_limits")),
        ))
    return TableRef(id=f"pk_{stage.lower()}", title=f"Predicted vs observed PK — stage {stage}",
                    columns=columns, rows=tuple(rows), source=f"evaluate_round {stage}")


def _tick(flag: bool | None) -> str:
    return "—" if flag is None else ("yes" if flag else "no")
