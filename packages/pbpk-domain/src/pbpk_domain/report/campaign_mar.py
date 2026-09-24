"""The Modeling Analysis Report for a whole campaign (MS-01 §4 S7, ICH M15 Appendix 2).

`assemble_campaign_mar` builds the report from what the campaign actually produced — the signed MAP, the final CPF,
each stage's last round (PK tables, acceptance groups, VPC), the S6 sensitivity and prediction intervals, and the
reproduction check — and nothing else. As in every MAR here, the prose carries no free-standing number: each figure
is a reference into the evidence set, so `check_report` can prove every number traces to an artifact.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from pbpk_domain.campaign.map import MapDocument
from pbpk_domain.cpf.models import CPF
from pbpk_domain.m15 import AssessmentTable, RatedElement
from pbpk_domain.report.mar import (
    Evidence,
    MarDocument,
    MarSection,
    TableRef,
    ValueRef,
    _study_pk_table,
    format_number,
)

STAGE_TITLES = {
    "S0": "Readiness", "S1": "IV disposition", "S2": "Oral absorption (fasted)", "S3": "Formulation and fed state",
    "S4": "Internal validation", "S5": "External validation", "S6": "Prediction", "S7": "Report and package",
}


def _fmt(value) -> str:
    return format_number(value) if isinstance(value, int | float) and not isinstance(value, bool) else "—"


def _cpf_table(cpf: CPF) -> TableRef:
    rows = []
    for p in cpf.parameters:
        ci = "—"
        if p.uncertainty and p.uncertainty.ci95_lower is not None and p.uncertainty.ci95_upper is not None:
            ci = f"{format_number(p.uncertainty.ci95_lower)} – {format_number(p.uncertainty.ci95_upper)}"
        value = format_number(p.value) if isinstance(p.value, int | float) else (str(p.value) if p.value is not None else "—")
        source = p.provenance.source_type if p.provenance else "—"
        if p.provenance and p.provenance.run:
            source += f" ({p.provenance.run})"
        rows.append((p.id, value, p.unit or "", p.status.value, source, p.fitted_at_stage or "—", ci))
    return TableRef(id="cpf_final", title=f"Final compound parameters — {cpf.compound} CPF version {cpf.version}",
                    columns=("Parameter", "Value", "Unit", "Status", "Source", "Fitted at", "95 % CI"),
                    rows=tuple(rows), source="final CPF")


def _study_table(map_doc: MapDocument) -> TableRef:
    stages: dict[str, list[str]] = {}
    for sc in map_doc.scenarios:
        stages.setdefault(sc.study_id, []).append(sc.stage)
    rows = tuple((s.study_id, s.study_class, s.assignment, ", ".join(stages.get(s.study_id, [])) or "not simulated")
                 for s in map_doc.studies)
    return TableRef(id="studies", title="Clinical studies, classification and data split",
                    columns=("Study", "Class", "Assignment", "Simulated in"), rows=rows, source="signed MAP (MS-01 §3)")


def _rounds_table(stage: str, rounds: Sequence[Mapping]) -> TableRef:
    rows = tuple((str(r.get("round")), str(r.get("action")), _fmt(r.get("aucGmfe")), _fmt(r.get("cmaxGmfe")),
                  str(r.get("verdict"))) for r in rounds)
    return TableRef(id=f"rounds_{stage.lower()}", title=f"Round history — stage {stage}",
                    columns=("Round", "Action", "AUC GMFE", "Cmax GMFE", "Verdict"), rows=rows,
                    source=f"campaign rounds {stage}")


def _groups_table(stage: str, groups: Sequence[Mapping]) -> TableRef:
    rows = tuple((str(g.get("role")), str(g.get("group") or "all"), str(g.get("quantity")), str(g.get("n")),
                  _fmt(g.get("fraction_within")), _fmt(g.get("required_fraction")),
                  "pass" if g.get("passes") else "fail") for g in groups)
    return TableRef(id=f"groups_{stage.lower()}", title=f"Acceptance by group — stage {stage}",
                    columns=("Role", "Group", "Quantity", "n", "Fraction within limits", "Required", "Verdict"),
                    rows=rows, source=f"acceptance evaluation {stage}")


def _vpc_table(stage: str, vpc: Mapping[str, Mapping]) -> TableRef:
    rows = tuple((sid, f"{v.get('inside')} of {v.get('points')}", _fmt(v.get("coverage")), str(v.get("individuals", "")),
                  "pass" if v.get("passes") else "below threshold") for sid, v in vpc.items())
    return TableRef(id=f"vpc_{stage.lower()}", title=f"Visual predictive check — stage {stage}",
                    columns=("Study", "Observed points inside the band", "Coverage", "Virtual individuals", "Result"),
                    rows=rows, source=f"population simulations {stage}")


def assemble_campaign_mar(
    *,
    map_doc: MapDocument,
    final_cpf: CPF,
    stage_evidence: Mapping[str, Mapping],
    prediction: Mapping | None = None,
    reproduction: Mapping | None = None,
    data_bundle_sha256: str | None = None,
    generated_at: datetime | None = None,
) -> MarDocument:
    """``stage_evidence[stage]`` = {"status", "rounds": [...], "metrics": {...}, "notes": [...]} per stage;
    ``prediction`` = the S6 result; ``reproduction`` = {"passes", "verdicts": [{path, status, detail}]}."""
    values: list[ValueRef] = [ValueRef(id="acceptance_tier", value=map_doc.acceptance.tier,
                                       source=f"acceptance ruleset {map_doc.acceptance.ruleset}")]
    tables: list[TableRef] = [_study_table(map_doc), _cpf_table(final_cpf)]
    limitations: list[str] = list(map_doc.split_limitations)

    def stage_body(stage: str) -> str:
        ev = stage_evidence.get(stage) or {}
        status = ev.get("status", "not run")
        limitations.extend(f"{stage}: {n}" for n in ev.get("notes", []) if not n.startswith("expression profiles:"))
        parts = [f"Stage {stage} ({STAGE_TITLES.get(stage, stage)}) ended **{status}**."]
        rounds = ev.get("rounds") or []
        metrics = ev.get("metrics") or {}
        if metrics.get("studies"):
            t = _study_pk_table(stage, metrics)
            tables.append(t)
            parts.append(f"{{{{table:{t.id}}}}}")
        if metrics.get("groups"):
            t = _groups_table(stage, metrics["groups"])
            tables.append(t)
            parts.append(f"{{{{table:{t.id}}}}}")
        if metrics.get("vpc"):
            t = _vpc_table(stage, metrics["vpc"])
            tables.append(t)
            parts.append(f"{{{{table:{t.id}}}}}")
        if rounds:
            t = _rounds_table(stage, rounds)
            tables.append(t)
            parts.append(f"The rounds the stage ran are listed below.\n\n{{{{table:{t.id}}}}}")
            last = rounds[-1]
            for q, key in (("AUC", "aucGmfe"), ("Cmax", "cmaxGmfe")):
                if last.get(key) is not None:
                    vid = f"{q.lower()}_gmfe_{stage.lower()}"
                    values.append(ValueRef(id=vid, value=float(last[key]), source=f"stage {stage} final round {q} GMFE"))
                    parts.append(f"The final {q} geometric mean fold error is {{{{value:{vid}}}}}.")
        return "\n\n".join(parts)

    development = tuple(MarSection(number=f"4.{i}", heading=f"{s} — {STAGE_TITLES[s]}", body=stage_body(s))
                        for i, s in enumerate(("S1", "S2", "S3"), start=1))
    evaluation = tuple(MarSection(number=f"5.{i}", heading=f"{s} — {STAGE_TITLES[s]}", body=stage_body(s))
                       for i, s in enumerate(("S4", "S5"), start=1))

    # S6 — sensitivity ranking and prediction intervals.
    pred_parts: list[str] = []
    if prediction:
        rows = []
        for sid, ranked in (prediction.get("sensitivity") or {}).items():
            for row in ranked[:8]:
                rows.append((sid, row["parameter"], row["pk_parameter"], format_number(row["value"])))
        if rows:
            tables.append(TableRef(id="sensitivity", title="Local sensitivity of plasma PK (largest first)",
                                   columns=("Study", "Parameter", "PK parameter", "Sensitivity"), rows=tuple(rows),
                                   source="S6 sensitivity analysis"))
            pred_parts.append("The PK parameters are most sensitive to the parameters below.\n\n{{table:sensitivity}}")
        rows = []
        for sid, pk in (prediction.get("intervals") or {}).items():
            for q, band in pk.items():
                if band:
                    rows.append((sid, q, format_number(band["p5"]), format_number(band["p50"]), format_number(band["p95"]),
                                 str(band["n"])))
        if rows:
            tables.append(TableRef(id="prediction_intervals", title="Prediction intervals from parameter uncertainty",
                                   columns=("Study", "Quantity", "5th percentile", "Median", "95th percentile", "Runs"),
                                   rows=tuple(rows), source="S6 uncertainty propagation (engine batch)"))
            pred_parts.append("Propagating the fitted parameters' uncertainty gives the intervals below.\n\n"
                              "{{table:prediction_intervals}}")
        limitations.extend(f"S6: {n}" for n in prediction.get("notes", []))
    if not pred_parts:
        pred_parts.append("No prediction was made (see the limitations).")

    # Reproduction.
    repro_parts: list[str] = []
    if reproduction:
        rows = tuple((v["path"], v["status"], v.get("detail", "")) for v in reproduction.get("verdicts", []))
        tables.append(TableRef(id="reproduction", title="Independent re-run of every bundled simulation",
                               columns=("Result table", "Verdict", "Detail"), rows=rows,
                               source="S7 reproduction on a fresh engine process"))
        values.append(ValueRef(id="reproduced_tables", value=len(rows), source="S7 reproduction", precision=6))
        verdict = "reproduced every result table" if reproduction.get("passes") else "did NOT reproduce every table"
        repro_parts.append(f"A fresh engine run of the bundled snapshots {verdict} "
                           f"({{{{value:reproduced_tables}}}} tables compared).\n\n{{{{table:reproduction}}}}")
    if data_bundle_sha256:
        values.append(ValueRef(id="data_bundle_sha256", value=data_bundle_sha256, source="S7 bundle manifest"))
        repro_parts.append("The data bundle's manifest hash is {{value:data_bundle_sha256}}.")

    all_passed = all((stage_evidence.get(s) or {}).get("status") in ("PASSED", "ACCEPTED", "SKIPPED")
                     for s in ("S1", "S2", "S3", "S4", "S5"))
    conclusion = ("Every model development and validation stage passed, was accepted by a signed decision, or was "
                  "skipped for want of data; the model meets the {{value:acceptance_tier}} acceptance tier for the stated "
                  "context of use, within the limitations listed." if all_passed else
                  "Not every stage passed; the model does not yet support the stated context of use.")

    sections = (
        MarSection(number="1", heading="Objective and context of use", verbatim=True,
                   body=f"{map_doc.objective}\n\n{map_doc.context_of_use}"),
        MarSection(number="2", heading="Data", body="The studies, their class and their role are given below.\n\n"
                                                    "{{table:studies}}"),
        MarSection(number="3", heading="Model description",
                   body="Every compound parameter, its origin and, when fitted, its precision:\n\n{{table:cpf_final}}"),
        MarSection(number="4", heading="Model development", subsections=development),
        MarSection(number="5", heading="Model evaluation", subsections=evaluation),
        MarSection(number="6", heading="Prediction", body="\n\n".join(pred_parts)),
        MarSection(number="7", heading="Reproducibility", body="\n\n".join(repro_parts) or "Not assessed."),
        MarSection(number="8", heading="Assumptions and limitations", verbatim=True,
                   body="\n".join(f"- {line}" for line in dict.fromkeys(limitations)) or "None recorded."),
        MarSection(number="9", heading="Conclusion", body=conclusion),
    )
    m15 = AssessmentTable(
        question_of_interest=map_doc.objective, context_of_use=map_doc.context_of_use,
        model_risk=RatedElement(description="from the signed MAP", rating=map_doc.model_risk,
                                justification="Model influence and decision consequence are recorded by the modeler"),
        technical_criteria=f"Acceptance ruleset {map_doc.acceptance.ruleset}, tier {map_doc.acceptance.tier}; diagnostics "
                           f"{map_doc.diagnostics_ruleset_version}",
        evaluation_of_models_and_outcomes="See sections 4 and 5 of this report.",
    )
    return MarDocument(
        compound=map_doc.compound, title=f"Modeling Analysis Report — {map_doc.compound}",
        question_of_interest=map_doc.objective, context_of_use=map_doc.context_of_use, model_risk=map_doc.model_risk,
        sections=sections, evidence=Evidence(values=tuple(values), tables=tuple(tables)), m15_tables=(m15,),
        engine_image_digest=map_doc.engine_image_digest, software_versions=dict(map_doc.software_versions),
        bundle_sha256=data_bundle_sha256, generated_at=generated_at or datetime.now(UTC),
    )
