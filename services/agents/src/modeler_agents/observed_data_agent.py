"""Agent A3 · Observed Data Agent (plan §14.2, T-45): clinical PK data from the literature for the data plan's needs.

It finds studies that meet the data plan's dataset needs (an IV study, fasted oral doses across the range, fed,
multiple-dose, external validation studies …) and extracts them from tables: every row it proposes carries a quote
that is checked verbatim on the page and must contain the row's time and value, so no number enters that the page
does not state. A study reported only as NCA values becomes a PK-parameter dataset (it can judge a prediction, not
train a fit). A study shown only in a figure is handed to a person for digitization: picking the points against a
calibrated axis is a human step (T-19), and its overlay is approved before use.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from modeler_agents.evidence_agent import ResearchContext, ResearchOutcome, reading_tools
from modeler_agents.llm import ChatModel, Tool, run_tool_loop
from modeler_intake.citations import quote_appears_in, value_stated_in_quote
from modeler_project.dataset_register import propose_dataset
from modeler_project.datasets import DatasetError, ObservedDataset, Origin, ReportedPK, Series, new_dataset_id
from modeler_project.evidence import SourceRef
from modeler_project.evidence_register import request_access

SYSTEM_PROMPT = """You find observed clinical pharmacokinetic data for a PBPK model built in PK-Sim, for the dataset needs listed by list_requirements (kind "dataset"): IV single-dose studies, fasted oral studies across the dose range, fed studies, multiple-dose studies, studies for external validation, urine data.

For each study you use, the study record must say: study_id (short, e.g. firstauthor-year-route-dose), reference, n, route (iv_bolus, iv_infusion, oral), dose_mg, formulation (solution, suspension, ir_tablet, ir_capsule, mr, other), food_state (fasted, fed), design (SD or MD; with dosing_interval_h and n_doses for MD), infusion_time_min for an infusion, statistic (individual, mean_sd, mean), n_timepoints, lloq if stated, population_type (healthy or patient), co_medication / genotype / special_population when present, and demographics {population, sex, age_years, age_min, age_max} when reported. Only what the paper states; leave out what it does not.

Extract concentration-time data from TABLES with propose_profile: one call per study and series; each row has the time, the value (and SD or SE if given) and a quote copied exactly from the table row on that page (the row text must contain the time and the value). When a paper gives only NCA results (AUC, Cmax, tmax, t1/2), use propose_pk_table. When the profile is only in a FIGURE, call request_digitization so a person digitizes it; do not read numbers off a figure yourself.

Report units exactly as the paper does (time unit; ng/ml, µg/l, µmol/l …). Call several tools in one turn when you can. Finish with a summary per dataset need: studies found, not found."""


def _parse_obj(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def _source(ctx: ResearchContext, doc_sha256: str, page: int, locator: str) -> SourceRef:
    doc = ctx.library.by_sha(doc_sha256)
    note = (doc.content.get("note") or "") if doc else ""
    paper = ctx.papers.get(note.split("paper:", 1)[1].split()[0]) if "paper:" in note else None
    return SourceRef(doc_sha256=doc_sha256, page=page, locator=locator,
                     title=getattr(paper, "title", "") or (doc.content["name"] if doc else ""),
                     authors=getattr(paper, "authors", ""), year=getattr(paper, "year", None),
                     doi=getattr(paper, "doi", None), pmid=getattr(paper, "pmid", None))


def propose_profile(ctx: ResearchContext, *, study: Any, time_unit: str, unit: str, rows: Any, doc_sha256: str, page: int,
                    locator: str = "", statistic: str = "arithmetic_mean", n: int | None = None, error_kind: str = "none",
                    series_name: str = "mean", analyte: str = "parent", matrix: str = "plasma",
                    purpose: str = "model_building") -> str:
    study, rows = _parse_obj(study), _parse_obj(rows)
    if not isinstance(study, dict) or not isinstance(rows, list) or not rows:
        return "REJECTED INVALID_INPUT: study must be an object and rows a non-empty list"
    text = ctx.library.page_text(doc_sha256, int(page))
    if text is None:
        return "REJECTED UNKNOWN_PAGE: read the document first"
    times, values, errors = [], [], []
    for index, row in enumerate(rows):
        try:
            t, v = float(row["time"]), row.get("value")
            v = None if v in (None, "", "BLQ", "<LLOQ") else float(v)
        except (KeyError, TypeError, ValueError):
            return f"REJECTED INVALID_ROW {index}: each row needs a numeric time and value"
        quote = str(row.get("quote", ""))
        if not quote_appears_in(text, quote):
            return f"REJECTED INVALID_CITATION row {index}: the quote is not on that page verbatim"
        if not value_stated_in_quote(t, quote) or (v is not None and not value_stated_in_quote(v, quote)):
            return f"REJECTED VALUE_NOT_IN_QUOTE row {index}: the quoted row must contain the time and the value"
        times.append(t)
        values.append(v)
        if row.get("error") not in (None, ""):
            errors.append(float(row["error"]))
    study = {**study, "n_timepoints": study.get("n_timepoints") or len(times)}
    dataset = ObservedDataset(
        id=new_dataset_id(), kind="profile", study=study, analyte=analyte, matrix=matrix, time_unit=time_unit, unit=unit,
        series=(Series(name=series_name, statistic=statistic, times=tuple(times), values=tuple(values),  # type: ignore[arg-type]
                       error=tuple(errors) if len(errors) == len(times) else None,
                       error_kind=error_kind if len(errors) == len(times) else "none", n=n),),  # type: ignore[arg-type]
        origin=Origin.LITERATURE, extraction="TABLE", source=_source(ctx, doc_sha256, int(page), locator),
        quote=str(rows[0].get("quote", "")), purpose=purpose, provider="LITERATURE")
    try:
        stored = propose_dataset(ctx.ws, dataset, actor=ctx.actor)
    except (DatasetError, ValueError) as exc:
        return f"REJECTED INVALID_DATASET: {exc}"
    ctx.proposed.append(stored.id)
    return f"RECORDED dataset {stored.id}" + (f"; flags: {', '.join(stored.flags)}" if stored.flags else "")


def propose_pk_table(ctx: ResearchContext, *, study: Any, parameters: Any, doc_sha256: str, page: int, locator: str = "",
                     purpose: str = "external_validation") -> str:
    study, parameters = _parse_obj(study), _parse_obj(parameters)
    if not isinstance(study, dict) or not isinstance(parameters, list) or not parameters:
        return "REJECTED INVALID_INPUT: study must be an object and parameters a non-empty list"
    text = ctx.library.page_text(doc_sha256, int(page))
    if text is None:
        return "REJECTED UNKNOWN_PAGE: read the document first"
    reported = []
    for index, p in enumerate(parameters):
        quote = str(p.get("quote", ""))
        if not quote_appears_in(text, quote) or not value_stated_in_quote(float(p.get("value", "nan")), quote):
            return f"REJECTED INVALID_CITATION parameter {index}: the quote must be on the page and contain the value"
        try:
            reported.append(ReportedPK(parameter=p["parameter"], value=float(p["value"]), unit=str(p["unit"]),
                                       statistic=str(p.get("statistic", "arithmetic_mean")),
                                       variability=str(p.get("variability", "")), quote=quote))
        except (KeyError, ValueError) as exc:
            return f"REJECTED INVALID_PARAMETER {index}: {exc}"
    study = {**study, "n_timepoints": study.get("n_timepoints") or 1}
    dataset = ObservedDataset(id=new_dataset_id(), kind="pk_parameters", study=study, reported=tuple(reported),
                              origin=Origin.LITERATURE, extraction="TABLE",
                              source=_source(ctx, doc_sha256, int(page), locator), purpose=purpose, provider="LITERATURE",
                              unit=reported[0].unit.split("*")[0].strip() or "ng/ml")
    try:
        stored = propose_dataset(ctx.ws, dataset, actor=ctx.actor)
    except (DatasetError, ValueError) as exc:
        return f"REJECTED INVALID_DATASET: {exc}"
    ctx.proposed.append(stored.id)
    return f"RECORDED PK-parameter dataset {stored.id}"


def build_tools(ctx: ResearchContext) -> list[Tool]:
    s = {"type": "string"}
    study = {"type": "object", "description": "the study record (see the system prompt)"}

    def request_digitization(doc_sha256: str, page: int, figure: str, study_description: str) -> str:
        request_id, _ = request_access(ctx.ws, title=f"Digitize {figure} (p. {page})", authors="", doi=None, journal=None,
                                       year=None, needed_for=f"figure digitization: {study_description} [doc {doc_sha256[:12]}]",
                                       by=ctx.actor)
        ctx.access_requests.append(request_id)
        return f"RECORDED digitization task {request_id} for a person"

    return [
        *reading_tools(ctx, kinds=("dataset",)),
        Tool("propose_profile", "Propose a concentration-time series from a TABLE, every row quoted verbatim.",
             {"type": "object", "properties": {
                 "study": study, "time_unit": s, "unit": s, "doc_sha256": s, "page": {"type": "integer"}, "locator": s,
                 "statistic": {"type": "string", "enum": ["individual", "arithmetic_mean", "geometric_mean", "median"]},
                 "n": {"type": "integer"}, "error_kind": {"type": "string", "enum": ["SD", "SE", "CV%", "none"]},
                 "series_name": s, "analyte": s, "matrix": s,
                 "purpose": {"type": "string", "enum": ["model_building", "internal_validation", "external_validation",
                                                        "application_verification"]},
                 "rows": {"type": "array", "items": {"type": "object", "properties": {
                     "time": {"type": "number"}, "value": {"type": "number"}, "error": {"type": "number"}, "quote": s},
                     "required": ["time", "value", "quote"]}}},
              "required": ["study", "time_unit", "unit", "rows", "doc_sha256", "page"]},
             lambda **kw: propose_profile(ctx, **kw)),
        Tool("propose_pk_table", "Propose reported NCA results (AUC, Cmax, tmax, t1/2) of a study, each quoted verbatim.",
             {"type": "object", "properties": {
                 "study": study, "doc_sha256": s, "page": {"type": "integer"}, "locator": s, "purpose": s,
                 "parameters": {"type": "array", "items": {"type": "object", "properties": {
                     "parameter": {"type": "string", "enum": ["AUC_last", "AUC_inf", "Cmax", "tmax", "t_half", "Ctrough"]},
                     "value": {"type": "number"}, "unit": s, "statistic": s, "variability": s, "quote": s},
                     "required": ["parameter", "value", "unit", "quote"]}}},
              "required": ["study", "parameters", "doc_sha256", "page"]},
             lambda **kw: propose_pk_table(ctx, **kw)),
        Tool("request_digitization", "Hand a figure to a person for digitization (calibrated axes, picked points).",
             {"type": "object", "properties": {"doc_sha256": s, "page": {"type": "integer"}, "figure": s,
                                               "study_description": s},
              "required": ["doc_sha256", "page", "figure", "study_description"]}, request_digitization),
    ]


def run_observed_data(model: ChatModel, ctx: ResearchContext, *, drug: str, max_turns: int = 120,
                      log_step: Callable[[dict[str, Any]], None] = lambda s: None) -> ResearchOutcome:
    needs = sum(r.kind == "dataset" for r in ctx.requirements)
    user = f"Drug: {drug}. Find observed clinical PK data for the {needs} dataset needs. Start with list_requirements."
    outcome = run_tool_loop(model, system=SYSTEM_PROMPT, user=user, tools=build_tools(ctx), max_turns=max_turns,
                            log_step=log_step)
    return ResearchOutcome(status=outcome.status, proposed=ctx.proposed, rejected=ctx.rejected, not_found=ctx.not_found,
                           access_requests=ctx.access_requests, summary=outcome.final_text, usage=outcome.usage,
                           error=outcome.error)
