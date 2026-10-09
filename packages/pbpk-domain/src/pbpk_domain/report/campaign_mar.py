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
    "SM": "Metabolites", "SJ": "Joint refinement", "S4": "Internal validation", "S5": "External validation", "S6": "Prediction", "S7": "Report and package",
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


def _system_tables(system, fitted: str) -> list[TableRef]:
    """A model system's compounds, products and analytes (multi-compound plan §3.5, MS-01 v1.3 §6.5): what each
    compound is, what each product doses, and what each analyte informs and where it is judged."""
    import hashlib
    import json

    from pbpk_domain.system import gated, subjects

    def sha(cpf) -> str:
        doc = cpf.model_dump(mode="json", exclude={"created_at"})
        return hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]

    forms = {f.metabolite: f"{f.compound} ({f.internal_name}:{f.molecule})" for f in system.formation}
    compounds = TableRef(id="system_compounds", title=f"Model system {system.name}: compounds",
                         columns=("Compound", "Role", "Formed by", "CPF version", "CPF sha256"),
                         rows=tuple((c.compound, system.roles[c.compound], forms.get(c.compound, "—"), str(c.version),
                                     sha(c)) for c in system.compounds))
    products = TableRef(id="system_products", title="Products and the dose fraction each compound receives",
                        columns=("Product", "Compound", "Dose fraction"),
                        rows=tuple((p, c, format_number(f)) for p, doses in system.products.items() for c, f in doses.items()))
    stages = ("S1", "S2", "S3", "SM", "SJ", "S4", "S5")
    rows = []
    for a in system.analytes.values():
        informs = subjects(system, a.name, fitted)
        metabolites = bool(informs) and all(system.roles[c] == "metabolite" for c in informs)
        judged = [st for st in stages if gated(system, a.name, fitted, st) and (st != "SM" or metabolites)]
        rows.append((a.name, ", ".join(informs) or "—", " · ".join(judged) or "reported, not judged"))
    analytes = TableRef(id="system_analytes", title="Analytes: the compounds each informs, the stages that judge it",
                        columns=("Analyte", "Informs", "Judged at"), rows=tuple(rows))
    return [compounds, products, analytes]


def _study_table(map_doc: MapDocument) -> TableRef:
    stages: dict[str, list[str]] = {}
    for sc in map_doc.scenarios:
        stages.setdefault(sc.study_id, []).append(sc.stage)
    rows = tuple((s.study_id, s.study_class, s.assignment, ", ".join(stages.get(s.study_id, [])) or "not simulated")
                 for s in map_doc.studies)
    return TableRef(id="studies", title="Clinical studies, classification and data split",
                    columns=("Study", "Class", "Assignment", "Simulated in"), rows=rows, source="signed MAP (MS-01 §3)")


def _real_data(summary: Mapping | None) -> str:
    """How many judged studies were real observed data, by origin (plan §9.4 item 3)."""
    if not summary:
        return "—"
    origins = ", ".join(f"{k.lower().replace('_', ' ')} {v}" for k, v in (summary.get("byOrigin") or {}).items())
    return f"{summary.get('real')} of {summary.get('judged')} real" + (f" ({origins})" if origins else "")


def _rounds_table(stage: str, rounds: Sequence[Mapping]) -> TableRef:
    rows = tuple((str(r.get("round")), str(r.get("action")), _fmt(r.get("aucGmfe")), _fmt(r.get("cmaxGmfe")),
                  _real_data(r.get("realData")), str(r.get("verdict"))) for r in rounds)
    return TableRef(id=f"rounds_{stage.lower()}", title=f"Round history — stage {stage}",
                    columns=("Round", "Action", "AUC GMFE", "Cmax GMFE", "Judged studies", "Verdict"), rows=rows,
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


def _value(v) -> str:
    return _fmt(v) if isinstance(v, int | float) and not isinstance(v, bool) else str(v) if v is not None else "—"


def _history_table(entries: Sequence[Mapping]) -> TableRef:
    """The change ledger: every parameter-set change, what it changed and which study verdicts it moved."""
    rows = []
    for e in entries:
        changes = [f"{c['parameter']} {_value(c.get('before'))} → {_value(c.get('after'))}" + (f" {c['unit']}" if c.get("unit") else "")
                   for c in e.get("changes", [])]
        verdicts = [f"{v['study_id']} {v['before']} → {v['after']}" for v in e.get("verdicts", [])]
        stage = str(e.get("stage")) + (f" (cycle {e['cycle']})" if (e.get("cycle") or 1) > 1 else "")
        rows.append((str(e.get("seq")), stage, f"{e.get('kind')}: {e.get('reason')}",
                     "; ".join(changes) or ("no parameter change" if e.get("event") else e.get("note", "none")),
                     "; ".join(verdicts) or "none"))
    return TableRef(id="development_history", title="Model development history",
                    columns=("Change", "Stage", "Cause", "Parameters changed", "Study verdicts moved"), rows=tuple(rows),
                    source="campaign change ledger")


def _pct(value: float) -> str:
    return f"{100 * value:.0f} %"


def _vbe_parts(vbe: Mapping, tables: list[TableRef], limitations: list[str]) -> list[str]:
    """The S6 virtual bioequivalence (T-31): its design, the probability of success, and the F-304 validation gate.
    A VBE that is not validated says so first, in bold, and in the limitations."""
    name = f"{vbe.get('template')} {vbe.get('template_version')}"
    validation = vbe.get("validation") or {}
    if vbe.get("status") != "RUN":
        limitations.append(f"S6: the virtual bioequivalence ({name}) did not run: {vbe.get('reason')}")
        return [f"**The virtual bioequivalence ({name}) did not run:** {vbe.get('reason')}"]
    status = validation.get("status", "NOT_VALIDATED")
    parts = []
    if status != "PASSED":
        parts.append(f"**This virtual bioequivalence result is not validated ({status}):** {validation.get('reason')}. It "
                     "does not support a bioequivalence decision on its own.")
        limitations.append(f"S6: the virtual bioequivalence is not validated ({status}): {validation.get('reason')}")
    if not vbe.get("limits_verified", False):
        limitations.append(f"S6: the bioequivalence limits '{vbe.get('limits_name')}' are not verified "
                           f"({vbe.get('limits_source')})")
    limitations.append(f"S6: the analysis template {name} is DRAFT and UNVERIFIED until a PBPK SME and QA sign it")
    variability = "; ".join(f"{v['parameter']} CV {v['cv_percent']} % ({v['source']})" for v in vbe.get("variability", []))
    lower, upper = vbe["limits"]
    tables.append(TableRef(id="vbe_design", title="Virtual bioequivalence design", columns=("Item", "Value"), rows=(
        ("Template", name),
        ("TEST formulation", str(vbe["formulations"]["test"])),
        ("Reference (RLD) formulation", str(vbe["formulations"]["reference"])),
        ("Design taken from", (f"{vbe['design_study']} ({format_number(vbe['dose_mg'])} mg, {vbe['food_state']}, "
                               f"{vbe['population']})")),
        ("Trials × subjects", f"{vbe['n_trials_run']} of {vbe['n_trials_planned']} planned × {vbe['n_subjects']}"),
        ("Individuals (excluded)", f"{vbe['individuals']} ({len(vbe.get('excluded_individuals', []))})"),
        ("Intra-subject variability", variability),
        ("Seeds", (f"population {vbe['seed']}; occasions TEST {vbe['occasion_seeds']['test']}, "
                   f"reference {vbe['occasion_seeds']['reference']}")),
        ("Limits", (f"{_pct(vbe['confidence'])} CI of the GMR within {format_number(lower)}–{format_number(upper)} "
                    f"({vbe['limits_name']}{'' if vbe.get('limits_verified') else ', not verified'})")),
        ("Probability-of-success threshold", _pct(vbe["pos_threshold"])),
    ), source="the signed MAP's vbe-crossover application"))
    rows = [(m, _pct(r["probability_of_success"]), format_number(r["gmr_median"]), format_number(r["gmr_p05"]),
             format_number(r["gmr_p95"]), f"{format_number(r['between_subject_cv_percent'])} %")
            for m, r in vbe["metrics"].items()]
    rows.append(("Joint (every metric in the same trial)", _pct(vbe["joint_probability_of_success"]), "", "", "", ""))
    tables.append(TableRef(id="vbe_results", title="Virtual bioequivalence trials",
                           columns=("Metric", "Probability of success", "GMR median", "GMR 5th percentile",
                                    "GMR 95th percentile", "Simulated between-subject CV"),
                           rows=tuple(rows), source="S6 virtual trials (engine population occasions, pk_analyses.csv)"))
    verdict = "meets" if vbe["meets_threshold"] else "does not meet"
    parts.append(f"The virtual trials give the probabilities of bioequivalence success below; the joint probability "
                 f"{verdict} the threshold the plan set.\n\n{{{{table:vbe_design}}}}\n\n{{{{table:vbe_results}}}}")
    checks = validation.get("checks") or []
    if checks:
        tables.append(TableRef(id="vbe_validation", title="Validation against the observed BE study (F-304)",
                               columns=("Metric", "Check", "Observed", "Simulated", "Passes"),
                               rows=tuple((c["metric"], c["check"], format_number(c["observed"]),
                                           (format_number(c["simulated"]) if "simulated" in c else
                                            f"{format_number(c['simulated_p05'])}–{format_number(c['simulated_p95'])}"),
                                           "yes" if c["passes"] else "no") for c in checks),
                               source=f"observed BE study: {validation.get('source')}"))
        parts.append(f"Validation against the observed BE study: **{status}**.\n\n{{{{table:vbe_validation}}}}")
    return parts


def assemble_campaign_mar(
    *,
    map_doc: MapDocument,
    final_cpf: CPF,
    stage_evidence: Mapping[str, Mapping],
    prediction: Mapping | None = None,
    reproduction: Mapping | None = None,
    data_bundle_sha256: str | None = None,
    generated_at: datetime | None = None,
    history: Mapping | None = None,
    system=None,
) -> MarDocument:
    """``stage_evidence[stage]`` = {"status", "rounds": [...], "metrics": {...}, "notes": [...]} per stage;
    ``prediction`` = the S6 result; ``reproduction`` = {"passes", "verdicts": [{path, status, detail}]};
    ``history`` = the campaign's change ledger (``entries``), the model development history; ``system`` = the model
    system as of the final CPF (`pbpk_domain.system.ModelSystem`), listed in section 3."""
    values: list[ValueRef] = [ValueRef(id="acceptance_tier", value=map_doc.acceptance.tier,
                                       source=f"acceptance ruleset {map_doc.acceptance.ruleset}")]
    tables: list[TableRef] = [_study_table(map_doc), _cpf_table(final_cpf)]
    model_description = "Every compound parameter, its origin and, when fitted, its precision:\n\n{{table:cpf_final}}"
    if system is not None:
        tables += _system_tables(system, final_cpf.compound)
        values.append(ValueRef(id="model_system_sha256", value=system.sha256, source="the model system as of the final CPF"))
        model_description = (
            f"The model simulates the {system.name} system (content hash {{{{value:model_system_sha256}}}}); each compound "
            "keeps its own parameter framework.\n\n{{table:system_compounds}}\n\n{{table:system_products}}\n\n"
            "{{table:system_analytes}}\n\nThe fitted compound's parameters, their origin and, when fitted, their "
            "precision:\n\n{{table:cpf_final}}")
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

    developed = ("S1", "S2", "S3", *(s for s in ("SM", "SJ") if s in stage_evidence))
    development = tuple(MarSection(number=f"4.{i}", heading=f"{s} — {STAGE_TITLES[s]}", body=stage_body(s))
                        for i, s in enumerate(developed, start=1))
    if history and history.get("entries"):
        tables.append(_history_table(history["entries"]))
        development += (MarSection(number=f"4.{len(development) + 1}", heading="Model development history",
                                   body="Every change of the parameter set during development, in order: the parameters "
                                        "it changed and the study verdicts it moved. A verdict that changed is listed "
                                        "under the change that produced the parameter set it was judged on.\n\n"
                                        "{{table:development_history}}"),)
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
        limitations.extend(f"S6: {n}" for n in prediction.get("notes", []) if not n.startswith("VBE ("))
        if prediction.get("vbe"):
            pred_parts.extend(_vbe_parts(prediction["vbe"], tables, limitations))
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
                     for s in ("S1", "S2", "S3", "S4", "S5", *(("SM",) if "SM" in stage_evidence else ())))
    conclusion = ("Every model development and validation stage passed, was accepted by a signed decision, or was "
                  "skipped for want of data; the model meets the {{value:acceptance_tier}} acceptance tier for the stated "
                  "context of use, within the limitations listed." if all_passed else
                  "Not every stage passed; the model does not yet support the stated context of use.")
    vbe = (prediction or {}).get("vbe")
    if vbe and (vbe.get("status") != "RUN" or (vbe.get("validation") or {}).get("status") != "PASSED"):
        conclusion += (" The virtual bioequivalence is not validated against an observed BE study, so it does not "
                       "support a bioequivalence decision on its own.")

    sections = (
        MarSection(number="1", heading="Objective and context of use", verbatim=True,
                   body=f"{map_doc.objective}\n\n{map_doc.context_of_use}"),
        MarSection(number="2", heading="Data", body="The studies, their class and their role are given below.\n\n"
                                                    "{{table:studies}}"),
        MarSection(number="3", heading="Model description", body=model_description),
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
    m15_tables = (m15,)
    if vbe:
        # M15 Appendix 1: one table per question of interest; the VBE application is its own question (T-31)
        validation = vbe.get("validation") or {}
        m15_tables += (AssessmentTable(
            question_of_interest=f"Virtual bioequivalence of {(vbe.get('formulations') or {}).get('test')} against "
                                 f"{(vbe.get('formulations') or {}).get('reference')} ({vbe.get('template')} "
                                 f"{vbe.get('template_version')})",
            context_of_use=map_doc.context_of_use,
            model_risk=RatedElement(description="from the signed MAP", rating=map_doc.model_risk,
                                    justification="Model influence and decision consequence are recorded by the modeler"),
            technical_criteria=(f"{_pct(vbe['confidence'])} CI of the GMR within {vbe['limits'][0]}–{vbe['limits'][1]} per "
                                f"trial; probability of success at least {_pct(vbe['pos_threshold'])}; F-304 validation "
                                "against the observed BE study" if vbe.get("status") == "RUN" else
                                f"not run: {vbe.get('reason')}"),
            evaluation_of_models_and_outcomes=(f"Validation {validation.get('status', 'NOT_VALIDATED')}: "
                                               f"{validation.get('reason', '')}. See section 6."),
        ),)
    return MarDocument(
        compound=map_doc.compound, title=f"Modeling Analysis Report — {map_doc.compound}",
        question_of_interest=map_doc.objective, context_of_use=map_doc.context_of_use, model_risk=map_doc.model_risk,
        sections=sections, evidence=Evidence(values=tuple(values), tables=tuple(tables)), m15_tables=m15_tables,
        engine_image_digest=map_doc.engine_image_digest, software_versions=dict(map_doc.software_versions),
        bundle_sha256=data_bundle_sha256, generated_at=generated_at or datetime.now(UTC),
    )
