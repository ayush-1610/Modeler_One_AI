"""Agent A4 · Client documents (docs/plans/2026-11-03-inputs-and-client-data.md §3.4, build I4): a client's PDF or Word
file read for project data.

Code lists first what each page seems to hold (`modeler_intake.document_reading.inventory`), in the order the file's
tag asks for. The agent reads the pages and proposes, page by page:
- a study's facts (dose, route, food state, dosage form, design, n, LLOQ), each with its quote;
- a concentration-time table or NCA results of a study, every row quoted, the units on a quoted header;
- a dissolution table of a product, its conditions (strength, batch, apparatus, rpm, medium, pH, volume) each quoted;
- two names the document gives one study ("Protocol EXZ-101 (Study 101)"), quoted;
- a figure to digitize, handed to a person.

Code checks every proposal before it is kept: the quote is on its page verbatim, it states the number (and the unit),
or a word that says the category; a name is written in the document; a profile's study has its dose, n and route
quoted. Code converts the dose to mg; the agent computes nothing. What code refuses is told to the agent, which may
fix it, and is kept in the reading's record. Nothing loads: each item waits on Inputs until a person confirms its
group (§3.3).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from modeler_agents.llm import ChatModel, LoopOutcome, Tool, run_tool_loop
from modeler_intake.citations import normalize_for_match, value_stated_in_quote
from modeler_intake.document_reading import (
    CHOICES,
    FACT_FIELDS,
    FactError,
    check_component,
    check_fact,
    check_quote,
    name_key,
    names_in,
    supports_choice,
    text_in,
)
from modeler_intake.validate import CONCENTRATION_UNITS, canonical_unit
from modeler_project.dataset_register import propose_dataset
from modeler_project.datasets import DatasetError, ObservedDataset, Origin, ReportedPK, Series, new_dataset_id
from modeler_project.documents import DocumentLibrary
from modeler_project.evidence import SourceRef
from modeler_project.evidence_register import request_access
from modeler_project.workspace import Workspace
from pbpk_domain.dissolution import profiles_from_rows

PAGE_CHARS = 8000
LINK_KINDS = ("study", "product", "batch")
FIND_LINES = 12
_TIME_WORDS = {"h": ("h", "hr", "hrs", "hour", "hours"), "min": ("min", "mins", "minute", "minutes"),
               "d": ("d", "day", "days")}
_CONDITION_NUMBERS = ("strength_mg", "rpm", "ph", "volume_ml")
_CONDITION_TEXTS = ("batch", "apparatus", "medium")
_STATISTICS = ("individual", "arithmetic_mean", "geometric_mean", "median")

SYSTEM_PROMPT = """You read one file a pharmaceutical client sent for a PBPK model built in PK-Sim (a protocol or synopsis, a clinical study report, a bioanalytical report, a formulation or dissolution report) and propose the project data it states. A program checks every proposal against the page you cite, and a scientist confirms everything before it is used, so propose only what the file states.

Work from the inventory of pages you are given; read_page reads a page, find looks for words across the file.

Propose with:
- propose_study_facts: a study's facts, each {fact, value, unit, page, quote}. fact is one of dose (value and unit: mg, g, µg, mcg or mg/kg), n (subjects dosed or evaluated, as the file says), route (oral, iv_bolus, iv_infusion), food_state (fasted, fed), formulation (solution, suspension, ir_tablet, ir_capsule, mr, other), design (SD single dose, MD multiple dose), lloq (value and its unit, e.g. ng/mL); and the subjects' demographics: age_mean, age_min, age_max (years), weight_mean (kg), height_mean (cm), females (a count) or female_percent, ethnicity (as written, e.g. "Caucasian"). The quote is copied exactly from that page and states the value: the number with its unit, or the words that say the category ("after an overnight fast", "film-coated tablet", "30-minute intravenous infusion"). Use the study's name exactly as the file writes it.
- propose_profile: a concentration-time TABLE of a study, one call per series (each dose group, each analyte); every row {time, value, error, quote} with a quote copied from that table row on that page (it must contain the time and the value), and header_quote, a line of the table that states the time unit and the concentration unit. Values below the LLOQ are null. Record the study's facts first: a profile needs the study's dose, n and route.
- propose_pk_table: NCA results (Cmax, AUC, tmax, t1/2) of a study, each quoted.
- propose_dissolution: a dissolution TABLE of one product under one set of conditions: product and product_quote (a line naming it), conditions [{field, value, page, quote}] for role (TEST, RLD, REFERENCE), strength_mg, batch, apparatus, rpm, medium, ph, volume_ml as the file states them, header_quote stating the time unit and %, and rows {time, mean, sd, quote}.
- propose_composition: a product's composition as the file reports it (shown to the reviewer, not used by the model): product and product_quote, and components [{name, amount, unit, function, quote}], each quote writing the component and its amount.
- propose_link: when the file says two names are one study (a protocol number and a study code), one product (a code and a trade name) or one batch (a batch and a lot number): kind study, product or batch, with the quote that says so.
- request_digitization: data shown only in a FIGURE; never read numbers off a figure.

Rules: a quote is at least 12 characters, so quote a table row whole. Never compute, convert or guess a number; copy units as written. If a fact is not stated, leave it out and say so in your summary. A proposal the program refuses comes back with the reason: fix it or leave it. Call several tools in one turn when you can. Finish with a short summary: what you proposed, what the file does not state, what is only in figures."""


@dataclass
class DocumentContext:
    ws: Workspace
    library: DocumentLibrary
    sha: str
    file: str
    actor: str
    tag: str = "other"
    tag_study: str = ""
    facts: list[dict[str, Any]] = field(default_factory=list)
    dissolution: list[dict[str, Any]] = field(default_factory=list)
    links: list[dict[str, Any]] = field(default_factory=list)
    datasets: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)
    digitization: list[str] = field(default_factory=list)
    compositions: list[dict[str, Any]] = field(default_factory=list)

    def pages(self) -> list[str]:
        return self.library.pages(self.sha)

    def page(self, page: Any) -> str | None:
        try:
            return self.library.page_text(self.sha, int(page))
        except (TypeError, ValueError):
            return None

    def refuse(self, what: str, why: str) -> str:
        self.refused.append(f"{what}: {why}")
        return f"REFUSED {what}: {why}"


def _parse(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def _named_in_file(ctx: DocumentContext, study_id: str) -> bool:
    """A study is named as the file writes it, or as the person tagged the file."""
    key = name_key(study_id)
    return bool(key) and (key == name_key(ctx.tag_study) or (len(key) >= 3 and any(key in name_key(p) for p in ctx.pages())))


def _time_unit_in(unit: str, quote: str) -> bool:
    words = {w.lower() for w in re.findall(r"[a-z]+", normalize_for_match(quote), re.IGNORECASE)}
    return any(w in words for w in _TIME_WORDS.get(unit, (unit,)))


def _unit_in(unit: str, quote: str) -> bool:
    return re.sub(r"\s", "", unit).lower() in re.sub(r"\s", "", normalize_for_match(quote)).lower()


# --- the tools -----------------------------------------------------------------------------------------------------


def read_page(ctx: DocumentContext, page: int) -> str:
    text = ctx.page(page)
    if text is None:
        return f"ERROR: no page {page}; the file has {len(ctx.pages())} pages"
    return f"Page {page} of {len(ctx.pages())}:\n{text[:PAGE_CHARS]}"


def find(ctx: DocumentContext, words: str) -> str:
    wanted = [w.lower() for w in re.findall(r"[\w%/.-]+", words) if len(w) > 1]
    if not wanted:
        return "ERROR: give one or more words"
    hits = []
    for number, text in enumerate(ctx.pages(), start=1):
        for raw in text.splitlines():
            line = " ".join(raw.split())
            score = sum(w in line.lower() for w in wanted)
            if score:
                hits.append((-score, number, line[:200]))
    hits.sort()
    return "\n".join(f"p. {n}: {line}" for _s, n, line in hits[:FIND_LINES]) or "nothing found"


def propose_study_facts(ctx: DocumentContext, *, study_id: str, facts: Any) -> str:
    facts = _parse(facts)
    if not isinstance(facts, list) or not facts:
        return "ERROR: facts must be a non-empty list of {fact, value, unit, page, quote}"
    study_id = str(study_id).strip()
    if not _named_in_file(ctx, study_id):
        return ctx.refuse(f"study {study_id!r}", "the file never writes this name; use the study's name as written")
    answers = []
    for f in facts:
        what = f"{study_id} {f.get('fact')}" if isinstance(f, dict) else str(f)
        if not isinstance(f, dict):
            answers.append(ctx.refuse(what, "each fact is an object"))
            continue
        problem = check_quote(ctx.page(f.get("page")), str(f.get("quote", "")))
        if problem:
            answers.append(ctx.refuse(what, problem))
            continue
        try:
            sets = check_fact(str(f.get("fact")), f.get("value"), f.get("unit"), str(f["quote"]))
        except FactError as exc:
            answers.append(ctx.refuse(what, str(exc)))
            continue
        shown = f"{f.get('value')} {f.get('unit') or ''}".strip()
        entry = {"study_id": study_id, "fact": str(f["fact"]), "sets": sets, "shown": shown, "page": int(f["page"]),
                 "quote": str(f["quote"])}
        if not any(e["study_id"] == study_id and e["fact"] == entry["fact"] and e["sets"] == sets for e in ctx.facts):
            ctx.facts.append(entry)
        answers.append(f"ACCEPTED {what} = {shown} (p. {entry['page']})")
    return "\n".join(answers)


def _study_record(ctx: DocumentContext, study_id: str, *, n_timepoints: int, statistic: str,
                  unit: str | None = None) -> tuple[dict[str, Any] | None, list[str]]:
    """The study record of a dataset from the facts accepted for its study: None with what is missing."""
    sets: dict[str, Any] = {}
    for f in ctx.facts:
        if name_key(f["study_id"]) == name_key(study_id):
            for k, v in f["sets"].items():
                sets.setdefault(k, v)
    missing = [k for k in ("dose_mg", "n", "route") if k not in sets]
    if missing:
        return None, missing
    record = {"study_id": study_id, "reference": ctx.file, "n": sets["n"], "dose_mg": sets["dose_mg"],
              "dose_per_kg": bool(sets.get("dose_per_kg")), "route": sets["route"], "statistic": statistic,
              "n_timepoints": max(1, n_timepoints)}
    for k in ("formulation", "food_state", "design"):
        if k in sets:
            record[k] = sets[k]
    if "lloq" in sets and unit and canonical_unit(sets.get("lloq_unit", ""), CONCENTRATION_UNITS) == canonical_unit(unit, CONCENTRATION_UNITS):
        record["lloq"] = sets["lloq"]
    return record, []


def _source(ctx: DocumentContext, page: int, locator: str) -> SourceRef:
    return SourceRef(doc_sha256=ctx.sha, page=page, locator=locator or f"p. {page}", title=ctx.file)


def propose_profile(ctx: DocumentContext, *, study_id: str, time_unit: str, unit: str, rows: Any, page: int,
                    header_quote: str, locator: str = "", statistic: str = "arithmetic_mean", n: int | None = None,
                    error_kind: str = "none", series_name: str = "mean", analyte: str = "parent",
                    matrix: str = "plasma") -> str:
    rows = _parse(rows)
    what = f"profile of {study_id} (p. {page})"
    if not isinstance(rows, list) or not rows:
        return ctx.refuse(what, "rows must be a non-empty list")
    text = ctx.page(page)
    problem = check_quote(text, header_quote)
    if problem:
        return ctx.refuse(what, f"header_quote: {problem}")
    if not _time_unit_in(time_unit, header_quote) or not _unit_in(unit, header_quote):
        return ctx.refuse(what, f"header_quote must state the time unit {time_unit!r} and the unit {unit!r}")
    if statistic not in _STATISTICS:
        return ctx.refuse(what, f"statistic: one of {', '.join(_STATISTICS)}")
    times, values, errors = [], [], []
    for index, row in enumerate(rows):
        try:
            t = float(row["time"])
            v = row.get("value")
            v = None if v in (None, "", "BLQ", "<LLOQ") else float(v)
        except (KeyError, TypeError, ValueError):
            return ctx.refuse(what, f"row {index}: a numeric time and value (null below the LLOQ)")
        quote = str(row.get("quote", ""))
        problem = check_quote(text, quote)
        if problem:
            return ctx.refuse(what, f"row {index}: {problem}")
        if not value_stated_in_quote(t, quote) or (v is not None and not value_stated_in_quote(v, quote)):
            return ctx.refuse(what, f"row {index}: the quoted row must contain the time {t:g} and the value")
        times.append(t)
        values.append(v)
        if row.get("error") not in (None, ""):
            errors.append(float(row["error"]))
    record, missing = _study_record(ctx, study_id, n_timepoints=len(times),
                                    statistic="individual" if statistic == "individual" else "mean_sd" if errors else "mean",
                                    unit=unit)
    if record is None:
        return ctx.refuse(what, f"record the study's {', '.join(missing)} first with propose_study_facts (quoted from "
                                "this file); if the file does not state them, say so in your summary")
    full = len(errors) == len(times)
    dataset = ObservedDataset(
        id=new_dataset_id(), kind="profile", study=record, analyte=analyte, matrix=matrix, time_unit=time_unit, unit=unit,
        series=(Series(name=series_name, statistic=statistic, times=tuple(times), values=tuple(values),  # type: ignore[arg-type]
                       error=tuple(errors) if full else None, error_kind=error_kind if full else "none",  # type: ignore[arg-type]
                       n=n),),
        origin=Origin.CLIENT, extraction="TABLE", provider="CLIENT", source=_source(ctx, int(page), locator),
        quote=str(rows[0].get("quote", "")))
    try:
        stored = propose_dataset(ctx.ws, dataset, actor=ctx.actor)
    except (DatasetError, ValueError) as exc:
        return ctx.refuse(what, f"not a valid dataset: {exc}")
    ctx.datasets.append(stored.id)
    return f"ACCEPTED {what}: dataset {stored.id}, {len(times)} times" + (f"; flags: {', '.join(stored.flags)}" if stored.flags else "")


def propose_pk_table(ctx: DocumentContext, *, study_id: str, parameters: Any, page: int, locator: str = "") -> str:
    parameters = _parse(parameters)
    what = f"NCA of {study_id} (p. {page})"
    if not isinstance(parameters, list) or not parameters:
        return ctx.refuse(what, "parameters must be a non-empty list")
    text = ctx.page(page)
    reported = []
    for index, p in enumerate(parameters):
        quote = str(p.get("quote", ""))
        problem = check_quote(text, quote)
        try:
            value = float(p.get("value"))
        except (TypeError, ValueError):
            return ctx.refuse(what, f"parameter {index}: a numeric value")
        if problem or not value_stated_in_quote(value, quote):
            return ctx.refuse(what, f"parameter {index}: {problem or 'the quote must contain the value'}")
        try:
            reported.append(ReportedPK(parameter=p["parameter"], value=value, unit=str(p["unit"]),
                                       statistic=str(p.get("statistic", "arithmetic_mean")),
                                       variability=str(p.get("variability", "")), quote=quote))
        except (KeyError, ValueError) as exc:
            return ctx.refuse(what, f"parameter {index}: {exc}")
    record, missing = _study_record(ctx, study_id, n_timepoints=1, statistic="mean")
    if record is None:
        return ctx.refuse(what, f"record the study's {', '.join(missing)} first with propose_study_facts")
    dataset = ObservedDataset(id=new_dataset_id(), kind="pk_parameters", study=record, reported=tuple(reported),
                              origin=Origin.CLIENT, extraction="TABLE", provider="CLIENT",
                              source=_source(ctx, int(page), locator), purpose="external_validation",
                              unit=reported[0].unit.split("*")[0].strip() or "ng/ml", quote=reported[0].quote)
    try:
        stored = propose_dataset(ctx.ws, dataset, actor=ctx.actor)
    except (DatasetError, ValueError) as exc:
        return ctx.refuse(what, f"not a valid dataset: {exc}")
    ctx.datasets.append(stored.id)
    return f"ACCEPTED {what}: dataset {stored.id}"


def _condition(ctx: DocumentContext, c: dict[str, Any], page: int) -> tuple[str, Any]:
    """A dissolution condition its quote states, or FactError."""
    name = str(c.get("field"))
    quote = str(c.get("quote", ""))
    problem = check_quote(ctx.page(c.get("page", page)), quote)
    if problem:
        raise FactError(problem)
    if name == "role":
        role = str(c.get("value", "")).upper()
        if role not in CHOICES["role"] or not supports_choice(role, quote):
            raise FactError(f"the quote does not say the product is the {role}")
        return name, role
    if name in _CONDITION_NUMBERS:
        try:
            number = float(c.get("value"))
        except (TypeError, ValueError) as exc:
            raise FactError("a number") from exc
        if not value_stated_in_quote(number, quote) or (name == "strength_mg" and not _unit_in("mg", quote)):
            raise FactError(f"the quote must state {number:g}" + (" mg" if name == "strength_mg" else ""))
        return name, number
    if name in _CONDITION_TEXTS:
        value = str(c.get("value", "")).strip()
        if not text_in(value, quote):
            raise FactError(f"the quote must write {value!r}")
        return name, value
    raise FactError(f"unknown condition: one of role, {', '.join(_CONDITION_NUMBERS + _CONDITION_TEXTS)}")


def propose_dissolution(ctx: DocumentContext, *, product: str, product_quote: str, page: int, time_unit: str,
                        header_quote: str, rows: Any, conditions: Any = None, n: int | None = None) -> str:
    rows, conditions = _parse(rows), _parse(conditions) or []
    what = f"dissolution of {product} (p. {page})"
    text = ctx.page(page)
    problem = check_quote(text, product_quote)
    if problem or not names_in(product_quote, product):
        return ctx.refuse(what, f"product_quote: {problem or 'it must name the product as written'}")
    problem = check_quote(text, header_quote)
    if problem or not _time_unit_in(time_unit, header_quote) or "%" not in header_quote:
        return ctx.refuse(what, f"header_quote: {problem or f'it must state the time unit {time_unit!r} and %'}")
    if not isinstance(rows, list) or not rows or not isinstance(conditions, list):
        return ctx.refuse(what, "rows must be a non-empty list and conditions a list")
    values: dict[str, Any] = {"product": product.strip(), "role": "", "strength_mg": None, "batch": "", "apparatus": "",
                              "rpm": None, "medium": "", "ph": None, "volume_ml": None}
    for c in conditions:
        try:
            name, value = _condition(ctx, c if isinstance(c, dict) else {}, page)
        except FactError as exc:
            return ctx.refuse(what, f"condition {c.get('field') if isinstance(c, dict) else c}: {exc}")
        values[name] = value
    if not values["medium"]:
        return ctx.refuse(what, "the medium is needed (quoted): profiles are compared by their conditions")
    out = []
    for index, row in enumerate(rows):
        try:
            t, mean = float(row["time"]), float(row["mean"])
        except (KeyError, TypeError, ValueError):
            return ctx.refuse(what, f"row {index}: a numeric time and mean")
        quote = str(row.get("quote", ""))
        problem = check_quote(text, quote)
        if problem or not value_stated_in_quote(t, quote) or not value_stated_in_quote(mean, quote):
            return ctx.refuse(what, f"row {index}: {problem or 'the quoted row must contain the time and the mean'}")
        sd = row.get("sd")
        out.append({"row": None, "page": int(page), "quote": quote,
                    "values": {**values, "time": t, "time_unit": time_unit, "mean": mean,
                               "sd": float(sd) if sd not in (None, "") else None, "n": n},
                    "cells": {"mean": f"p. {page}"}})
    built, problems = profiles_from_rows(out)
    if problems or not built:
        return ctx.refuse(what, "; ".join(problems) or "no profile")
    ctx.dissolution += out
    return f"ACCEPTED {what}: {len(out)} times, medium {values['medium']}"


def propose_link(ctx: DocumentContext, *, names: Any, page: int, quote: str, kind: str = "study") -> str:
    names = _parse(names)
    if not isinstance(names, list) or len(names) != 2:
        return "ERROR: names is a list of the two names"
    if kind not in LINK_KINDS:
        return f"ERROR: kind is one of {', '.join(LINK_KINDS)}"
    a, b = (str(n).strip() for n in names)
    what = f"{kind} link {a} = {b}"
    problem = check_quote(ctx.page(page), quote)
    if problem:
        return ctx.refuse(what, problem)
    if name_key(a) == name_key(b) or not names_in(quote, a, b):
        return ctx.refuse(what, "the quote must write both names, and they must differ")
    ctx.links.append({"kind": kind, "names": [a, b], "page": int(page), "quote": quote})
    return f"ACCEPTED {what}: a person is asked whether they are one {kind}"


def propose_composition(ctx: DocumentContext, *, product: str, product_quote: str, page: int, components: Any) -> str:
    components = _parse(components)
    what = f"composition of {product} (p. {page})"
    text = ctx.page(page)
    problem = check_quote(text, product_quote)
    if problem or not names_in(product_quote, product):
        return ctx.refuse(what, f"product_quote: {problem or 'it must name the product as written'}")
    if not isinstance(components, list) or not components:
        return ctx.refuse(what, "components must be a non-empty list")
    lines = []
    for index, c in enumerate(components):
        c = c if isinstance(c, dict) else {}
        quote = str(c.get("quote", ""))
        problem = check_quote(text, quote)
        try:
            if problem:
                raise FactError(problem)
            line = check_component(str(c.get("name", "")), c.get("amount"), str(c.get("unit", "")), quote)
        except FactError as exc:
            return ctx.refuse(what, f"component {index}: {exc}")
        lines.append({**line, "function": str(c.get("function") or "").strip(), "quote": quote})
    ctx.compositions.append({"product": product.strip(), "page": int(page), "product_quote": product_quote,
                             "components": lines})
    return f"ACCEPTED {what}: {len(lines)} components, shown on the product's card as reported"


def build_tools(ctx: DocumentContext) -> list[Tool]:
    s, i = {"type": "string"}, {"type": "integer"}
    num = {"type": "number"}

    def request_digitization(page: int, figure: str, what: str) -> str:
        request_id, _ = request_access(ctx.ws, title=f"Digitize {figure} (p. {page}) of {ctx.file}", authors="", doi=None,
                                       journal=None, year=None, needed_for=f"figure digitization: {what} [doc {ctx.sha[:12]}]",
                                       by=ctx.actor)
        ctx.digitization.append(request_id)
        return f"RECORDED digitization task {request_id} for a person"

    fact = {"type": "object", "properties": {"fact": {"type": "string", "enum": list(FACT_FIELDS)}, "value": {},
                                             "unit": s, "page": i, "quote": s}, "required": ["fact", "value", "page", "quote"]}
    return [
        Tool("read_page", "Read one page of the file.", {"type": "object", "properties": {"page": i}, "required": ["page"]},
             lambda **kw: read_page(ctx, **kw)),
        Tool("find", "Find lines with these words across the file (page and line).",
             {"type": "object", "properties": {"words": s}, "required": ["words"]}, lambda **kw: find(ctx, **kw)),
        Tool("propose_study_facts", "Propose facts of one study, each quoted from its page.",
             {"type": "object", "properties": {"study_id": s, "facts": {"type": "array", "items": fact}},
              "required": ["study_id", "facts"]}, lambda **kw: propose_study_facts(ctx, **kw)),
        Tool("propose_profile", "Propose a concentration-time series from a TABLE, every row quoted.",
             {"type": "object", "properties": {
                 "study_id": s, "time_unit": s, "unit": s, "page": i, "header_quote": s, "locator": s,
                 "statistic": {"type": "string", "enum": list(_STATISTICS)}, "n": i,
                 "error_kind": {"type": "string", "enum": ["SD", "SE", "CV%", "none"]}, "series_name": s, "analyte": s,
                 "matrix": s, "rows": {"type": "array", "items": {"type": "object", "properties": {
                     "time": num, "value": {"type": ["number", "null"]}, "error": num, "quote": s},
                     "required": ["time", "value", "quote"]}}},
              "required": ["study_id", "time_unit", "unit", "rows", "page", "header_quote"]},
             lambda **kw: propose_profile(ctx, **kw)),
        Tool("propose_pk_table", "Propose NCA results of a study (Cmax, AUC, tmax, t1/2), each quoted.",
             {"type": "object", "properties": {
                 "study_id": s, "page": i, "locator": s, "parameters": {"type": "array", "items": {"type": "object", "properties": {
                     "parameter": {"type": "string", "enum": ["AUC_last", "AUC_inf", "Cmax", "tmax", "t_half", "Ctrough"]},
                     "value": num, "unit": s, "statistic": s, "variability": s, "quote": s},
                     "required": ["parameter", "value", "unit", "quote"]}}},
              "required": ["study_id", "parameters", "page"]}, lambda **kw: propose_pk_table(ctx, **kw)),
        Tool("propose_dissolution", "Propose a dissolution TABLE of one product under one set of conditions, quoted.",
             {"type": "object", "properties": {
                 "product": s, "product_quote": s, "page": i, "time_unit": s, "header_quote": s, "n": i,
                 "conditions": {"type": "array", "items": {"type": "object", "properties": {
                     "field": {"type": "string", "enum": ["role", *_CONDITION_NUMBERS, *_CONDITION_TEXTS]}, "value": {},
                     "page": i, "quote": s}, "required": ["field", "value", "quote"]}},
                 "rows": {"type": "array", "items": {"type": "object", "properties": {
                     "time": num, "mean": num, "sd": num, "quote": s}, "required": ["time", "mean", "quote"]}}},
              "required": ["product", "product_quote", "page", "time_unit", "header_quote", "rows", "conditions"]},
             lambda **kw: propose_dissolution(ctx, **kw)),
        Tool("propose_link", "Two names the file gives one study, product or batch, with the quote that says so.",
             {"type": "object", "properties": {"names": {"type": "array", "items": s}, "page": i, "quote": s,
                                               "kind": {"type": "string", "enum": list(LINK_KINDS)}},
              "required": ["names", "page", "quote"]}, lambda **kw: propose_link(ctx, **kw)),
        Tool("propose_composition", "A product's composition as the file reports it (not used by the model), quoted.",
             {"type": "object", "properties": {
                 "product": s, "product_quote": s, "page": i, "components": {"type": "array", "items": {
                     "type": "object", "properties": {"name": s, "amount": num, "unit": s, "function": s, "quote": s},
                     "required": ["name", "amount", "unit", "quote"]}}},
              "required": ["product", "product_quote", "page", "components"]}, lambda **kw: propose_composition(ctx, **kw)),
        Tool("request_digitization", "Hand data shown only in a figure to a person for digitization.",
             {"type": "object", "properties": {"page": i, "figure": s, "what": s}, "required": ["page", "figure", "what"]},
             request_digitization),
    ]


def brief_for(ctx: DocumentContext, *, inventory: list[dict[str, Any]], drug: str, known_studies: list[str],
              context: str = "") -> str:
    """The agent's task: the file, its tag, code's inventory and the study names the client's other files use."""
    tag = f"tagged “{ctx.tag}”" + (f" for study {ctx.tag_study}" if ctx.tag_study else "")
    lines = [f"Drug: {drug or 'not named'}. File: {ctx.file}, {len(ctx.pages())} pages, {tag}."]
    if inventory:
        lines.append("Pages that seem to hold project data (code's inventory, in the order to read them):")
        lines += [f"- p. {i['page']}: {i['label']}: “{i['line']}”" for i in inventory]
    else:
        lines.append("Code found no page that clearly holds project data: use find, then read_page.")
    if known_studies:
        lines.append(f"Study names in the client's other files: {', '.join(known_studies)}. If this file gives one of "
                     "them another name, propose_link with the quote.")
    if context:   # what the delivery map says of this file and the others (plan 2026-11-10, R4)
        lines.append(context)
    return "\n".join(lines)


def read_document(model: ChatModel, ctx: DocumentContext, *, inventory: list[dict[str, Any]], drug: str = "",
                  known_studies: list[str] = (), max_turns: int = 30,
                  log_step: Callable[[dict[str, Any]], None] = lambda s: None, context: str = "") -> LoopOutcome:
    """Read one client document; what code accepted is on `ctx` (facts, dissolution rows, links, datasets proposed),
    and what it refused on `ctx.refused`."""
    return run_tool_loop(model, system=SYSTEM_PROMPT,
                         user=brief_for(ctx, inventory=inventory, drug=drug, known_studies=list(known_studies),
                                        context=context),
                         tools=build_tools(ctx), max_turns=max_turns, log_step=log_step)


def read_and_record(model: ChatModel, ws: Workspace, library: DocumentLibrary, sid: str, *, actor: str, drug: str = "",
                    run_id: str | None = None, max_turns: int = 30,
                    log_step: Callable[[dict[str, Any]], None] = lambda s: None,
                    context: str = "") -> tuple[DocumentContext, LoopOutcome]:
    """Read one client file (its submission `sid`) and record on it what code accepted and refused
    (`client_data.record_document_reading`): the API's reading job and the delivery evaluation both read this way."""
    from modeler_intake.document_reading import inventory
    from modeler_project.client_data import ClientDataError, record_document_reading, submission
    from modeler_project.dataset_register import datasets

    content = submission(ws, sid)
    if content is None:
        raise ClientDataError(f"no client file {sid}")
    sha = content["sha256"]
    tag = library.entry(sha).tag if library.has_record else None
    listed = content.get("inventory") or [i.to_content() for i in inventory(library.pages(sha), tag.kind if tag else "other")]
    known = sorted({str(d.study.get("study_id")) for d in datasets(ws) if d.provider == "CLIENT"})
    ctx = DocumentContext(ws=ws, library=library, sha=sha, file=content["file"], actor=actor,
                          tag=tag.kind if tag else "other", tag_study=tag.study if tag else "")
    outcome = read_document(model, ctx, inventory=listed, drug=drug, known_studies=known, max_turns=max_turns,
                            log_step=log_step, context=context)
    record_document_reading(ws, sid, facts=ctx.facts, dissolution=ctx.dissolution, links=ctx.links, datasets=ctx.datasets,
                            refused=ctx.refused, digitization=ctx.digitization, summary=outcome.final_text, run_id=run_id,
                            by=actor, compositions=ctx.compositions)
    return ctx, outcome
