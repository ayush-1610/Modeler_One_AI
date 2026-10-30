"""Agent A1 · Proposal Intake (plan §14.2, T-41): fill the fixed Project Brief from the technical proposal.

The model reads the uploaded documents through tools and proposes one field at a time. Deterministic code checks every
proposal before it enters the brief: the field exists, the value fits the field (enum, number, list), the quote is
found verbatim on the cited page, and the field is not locked by a person. A rejection is returned to the model with
its reason, so it can correct the citation or move on. What no document states is marked MISSING with a question;
nothing is inferred, with one exception: the ICH M15 draft (page review 1, the owner's decisions 1b and 4 of
2026-10-29). From the question of interest and context of use, the agent suggests the model influence and the decision
consequence, each with why. All four are DRAFTED: none is a value until a person confirms it. The ratings that count
and the risk tier stay human-only and are never written by the agent.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from modeler_agents.llm import ChatModel, LoopOutcome, Tool, run_tool_loop
from modeler_intake.citations import quote_appears_in, value_stated_in_quote
from modeler_project.brief import (
    FIELDS,
    GROUPS,
    RATINGS,
    SECTIONS,
    BriefPathError,
    Citation,
    FieldStatus,
    ProjectBrief,
    add_question,
    definition_of,
    parse_path,
)
from modeler_project.brief_ops import HUMAN_ONLY, EditError, agent_set, locked, summary
from modeler_project.documents import document_record


class DocumentSource(Protocol):
    def documents(self) -> list[Any]: ...  # DOCUMENT artifact versions (content: name, sha256, n_pages, role)

    def page_text(self, doc_sha256: str, page: int) -> str | None: ...

    def search(self, query: str, max_results: int = 8) -> list[Any]: ...


# The suggested ratings come only from draft_risk_assessment, never from a quote
DRAFT_ONLY = frozenset({"m15.influence_suggested", "m15.consequence_suggested"})


def _catalog_text() -> str:
    """The fields the agent may fill: every field but the ones only a person sets (the ICH M15 ratings and risk) and the
    suggested ratings, which come from the draft."""
    lines = []
    for code, title in SECTIONS.items():
        scalar = [f for f in FIELDS if f.section == code and f.id not in HUMAN_ONLY | DRAFT_ONLY]
        groups = [g for g in GROUPS if g.section == code]
        if not scalar and not groups:
            continue
        lines.append(f"## {code} {title}")
        for f in scalar:
            opts = f" one of: {', '.join(f.options)}" if f.options else ""
            unit = f" [{f.unit}]" if f.unit else ""
            lines.append(f"- {f.id} ({f.kind}{unit}{', required' if f.required else ''}): {f.label}.{opts}")
        for g in groups:
            lines.append(f"- {g.id}[i] — {g.label}, one entry per item, i = 0, 1, 2 …")
            for f in g.fields:
                opts = f" one of: {', '.join(f.options)}" if f.options else ""
                unit = f" [{f.unit}]" if f.unit else ""
                lines.append(f"  - {g.id}[i].{f.id} ({f.kind}{unit}): {f.label}.{opts}")
    return "\n".join(lines)


SYSTEM_PROMPT = """You prepare the Project Brief of a PBPK / population-PK modeling project from the client's technical proposal and the other uploaded documents. The model will be built in PK-Sim and may be submitted to regulators, so a PBPK scientist reviews every field you fill.

Rules:
- Extract only what the documents state. Every value needs a quote copied exactly from the cited page (at least 12 characters) that contains or directly states the value. If a field is not stated, call mark_missing with a short question for the reviewer instead of guessing.
- Use exactly the field paths and option values listed below. For lists of things (products, scenarios, populations, data_plan), use one index per item, starting at 0, and fill the item's required sub-fields first.
- The data plan (data_plan[i]) records every statement about who provides which data: the client, the literature, the sponsor, or nobody yet; with its category and purpose (model building, internal validation, external validation, application verification).
- Doses and strengths are numbers with their unit as stated (e.g. value 50, unit mg). Keep the unit the document uses.
- Never propose the ICH M15 ratings, the risk tier or acceptance.tier with propose_field: people decide those. Once qoi.text and qoi.context_of_use are recorded, call draft_risk_assessment once. Suggest the model influence (how much the model's evidence weighs in the decision: low when other evidence decides, high when the model is the main evidence, e.g. in place of a clinical study) and the decision consequence (what a wrong decision would mean for patients: low when it would do no harm, high when it could seriously harm them). Explain each in one or two plain sentences built from the question and context of use. A person confirms or changes the draft.
- Do not repeat a field that was RECORDED unless a document states a different value; then propose it again with the new quote and say why in the note.
- When a proposal is REJECTED, fix it from the page text (exact quote, correct page, valid option) or move on.
- Work document by document: list_documents, then read pages; search_documents helps to find specific facts. Call several tools in one turn whenever you can (e.g. propose every field you found on a page together). Finish with a short summary of what was filled, what is missing, and any contradictions between documents.

The brief's fields:
""" + _catalog_text()


@dataclass
class IntakeContext:
    library: DocumentSource
    brief: ProjectBrief
    actor: str                       # "agent:<run id>"
    accepted: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)


def _reject(ctx: IntakeContext, code: str, path: str, message: str) -> str:
    ctx.rejected.append({"code": code, "path": path, "message": message})
    return f"REJECTED {code}: {message}"


def propose_field(ctx: IntakeContext, *, path: str, value: Any, quote: str, doc_sha256: str, page: int,
                  unit: str = "", locator: str = "", note: str = "") -> str:
    try:
        parse_path(path)
    except BriefPathError as exc:
        return _reject(ctx, "UNKNOWN_FIELD", path, str(exc))
    if path in HUMAN_ONLY:
        return _reject(ctx, "HUMAN_ONLY", path, "this field is set by a person; extract the description fields instead")
    if path in DRAFT_ONLY:
        return _reject(ctx, "DRAFT_ONLY", path, "suggest the ratings with draft_risk_assessment")
    if locked(ctx.brief, path):
        return _reject(ctx, "LOCKED", path, "a person already set this field; it is not changed by the agent")
    page_text = ctx.library.page_text(doc_sha256, int(page))
    if page_text is None:
        return _reject(ctx, "UNKNOWN_PAGE", path, "no such document page; use list_documents and read_page")
    if not quote_appears_in(page_text, quote):
        return _reject(ctx, "INVALID_CITATION", path,
                       "the quote was not found verbatim on that page (min. 12 characters); copy it exactly")
    definition = definition_of(path)
    confidence = "A"
    notes = [note] if note else []
    if definition.kind == "number":
        try:
            number = float(str(value).replace(",", "").split()[0])
        except (ValueError, IndexError):
            return _reject(ctx, "INVALID_VALUE", path, f"{value!r} is not a number")
        if not value_stated_in_quote(number, quote):
            confidence = "B"
            notes.append("the number is not written literally in the quote")
    cite = Citation(doc_sha256=doc_sha256, page=int(page), quote=quote, locator=locator,
                    source=_doc_name(ctx.library, doc_sha256))
    try:
        ctx.brief = agent_set(ctx.brief, path, value=value, unit=unit or None, citations=(cite,),
                              status=FieldStatus.EXTRACTED, confidence=confidence, by=ctx.actor, note="; ".join(notes))
    except (EditError, BriefPathError) as exc:
        return _reject(ctx, "INVALID_VALUE", path, str(exc))
    ctx.accepted.append({"path": path, "value": value, "unit": unit, "doc": doc_sha256, "page": page})
    return f"RECORDED {path}" + (" (confidence B: number not literal in the quote)" if confidence == "B" else "")


def draft_risk_assessment(ctx: IntakeContext, *, influence: str, how_the_model_is_used: str, consequence: str,
                          what_a_wrong_decision_means: str) -> str:
    """The ICH M15 draft: the two ratings the agent suggests, with why, built from the question of interest and context of
    use already in the brief and citing their quotes. Checked whole before anything is written. A field a person set,
    or a description the proposal itself states (EXTRACTED), is kept."""
    basis = [ctx.brief.get(p) for p in ("qoi.text", "qoi.context_of_use")]
    if any(r.value in (None, "") for r in basis):
        return _reject(ctx, "NOTHING_TO_DRAFT_FROM", "m15.influence",
                       "record qoi.text and qoi.context_of_use first: the draft is built from them")
    drafts = [("m15.influence_suggested", influence), ("m15.consequence_suggested", consequence),
              ("m15.influence", how_the_model_is_used.strip()), ("m15.consequence", what_a_wrong_decision_means.strip())]
    for path, value in drafts[:2]:
        if value not in RATINGS:
            return _reject(ctx, "INVALID_VALUE", path, f"{value!r} is not one of {', '.join(RATINGS)}")
    for path, value in drafts[2:]:
        if len(value) < 20:
            return _reject(ctx, "INVALID_VALUE", path, "say why in a sentence or two (at least 20 characters)")
    citations = tuple(c for r in basis for c in r.citations)
    note = "drafted by the intake agent from the question of interest and context of use; a person confirms it"
    written, kept = [], []
    for path, value in drafts:
        if locked(ctx.brief, path) or ctx.brief.get(path).status is FieldStatus.EXTRACTED:
            kept.append(path)
            continue
        ctx.brief = agent_set(ctx.brief, path, value=value, unit=None, citations=citations, status=FieldStatus.DRAFTED,
                              confidence=None, by=ctx.actor, note=note)
        written.append(path)
        ctx.accepted.append({"path": path, "value": value, "unit": "", "doc": "", "page": None})
    return (f"DRAFTED {', '.join(written) or 'nothing'}"
            + (f"; kept {', '.join(kept)} (set by a person or stated in a document)" if kept else ""))


def _doc_name(library: DocumentSource, sha: str) -> str:
    return next((r.name for r in map(document_record, library.documents()) if r.sha256 == sha), "")


def build_tools(ctx: IntakeContext) -> list[Tool]:
    def list_documents() -> str:
        rows = [f"{r.sha256} | {r.name} | role {r.role} | {r.n_pages} pages"
                for r in map(document_record, ctx.library.documents()) if r.role != "retrieved_record"]
        return "\n".join(rows) or "no documents"

    def read_page(doc_sha256: str, page: int) -> str:
        text = ctx.library.page_text(doc_sha256, int(page))
        return text if text is not None else "ERROR: no such document page"

    def search_documents(query: str, max_results: int = 8) -> str:
        hits = ctx.library.search(query, max(1, min(int(max_results), 20)))
        return "\n".join(f"{h.doc_sha256} p.{h.page} {h.title}: {h.snippet}" for h in hits) or "no matches"

    def brief_status() -> str:
        filled = {}
        for f in FIELDS:
            record = ctx.brief.fields.get(f.id)
            if record is not None and record.status is not FieldStatus.MISSING:
                filled[f.id] = f"{record.status.value}: {record.value}"
        groups = {g: len(items) for g, items in ctx.brief.groups.items()}
        return json.dumps({"filled": filled, "group_counts": groups, **summary(ctx.brief)}, default=str)

    def mark_missing(path: str, question: str) -> str:
        try:
            parse_path(path)
        except BriefPathError as exc:
            return f"REJECTED UNKNOWN_FIELD: {exc}"
        if ctx.brief.value(path) is not None:
            return "IGNORED: that field already has a value"
        ctx.brief = add_question(ctx.brief, path, question, raised_by=ctx.actor)
        return f"QUESTION RECORDED for {path}"

    string = {"type": "string"}
    return [
        Tool("list_documents", "List the uploaded documents (sha256, name, role, number of pages).",
             {"type": "object", "properties": {}}, list_documents),
        Tool("read_page", "Return the text of one page of a document.",
             {"type": "object", "properties": {"doc_sha256": string, "page": {"type": "integer"}},
              "required": ["doc_sha256", "page"]}, read_page),
        Tool("search_documents", "Keyword search over every page of every uploaded document.",
             {"type": "object", "properties": {"query": string, "max_results": {"type": "integer"}}, "required": ["query"]},
             search_documents),
        Tool("brief_status", "Which brief fields are filled, how many items each list has, open questions.",
             {"type": "object", "properties": {}}, brief_status),
        Tool("propose_field", "Propose the value of one brief field with a verbatim quote from the cited page.",
             {"type": "object", "properties": {
                 "path": {"type": "string", "description": "field path, e.g. drug.salt_form or products[0].role"},
                 "value": {"type": "string", "description": "the value; for lists, items separated by ';'"},
                 "unit": string, "quote": string, "doc_sha256": string, "page": {"type": "integer"},
                 "locator": {"type": "string", "description": "e.g. Table 2, Section 3.1"}, "note": string},
              "required": ["path", "value", "quote", "doc_sha256", "page"]},
             lambda **kw: propose_field(ctx, **kw)),
        Tool("mark_missing", "Record that a field is not stated in any document, with a question for the reviewer.",
             {"type": "object", "properties": {"path": string, "question": string}, "required": ["path", "question"]},
             mark_missing),
        Tool("draft_risk_assessment",
             "Suggest the ICH M15 model influence and decision consequence, each with why, from the recorded question of "
             "interest and context of use. A draft only: a person confirms or changes it.",
             {"type": "object", "properties": {
                 "influence": {"type": "string", "enum": list(RATINGS)},
                 "how_the_model_is_used": {"type": "string", "description": "why the model's influence is rated so"},
                 "consequence": {"type": "string", "enum": list(RATINGS)},
                 "what_a_wrong_decision_means": {"type": "string", "description": "why the consequence is rated so"}},
              "required": ["influence", "how_the_model_is_used", "consequence", "what_a_wrong_decision_means"]},
             lambda **kw: draft_risk_assessment(ctx, **kw)),
    ]


@dataclass
class IntakeOutcome:
    status: str
    brief: ProjectBrief
    accepted: list[dict[str, Any]]
    rejected: list[dict[str, Any]]
    summary: str
    usage: dict[str, int]
    error: str = ""


def run_proposal_intake(model: ChatModel, ctx: IntakeContext, *, context_note: str = "", max_turns: int = 80,
                        log_step: Callable[[dict[str, Any]], None] = lambda s: None) -> IntakeOutcome:
    user = (f"Drug: {ctx.brief.drug_name}.\n"
            + (f"Context from the person who started the project: {context_note}\n" if context_note else "")
            + "Fill the Project Brief from the uploaded documents. Start with list_documents.")
    outcome: LoopOutcome = run_tool_loop(model, system=SYSTEM_PROMPT, user=user, tools=build_tools(ctx),
                                         max_turns=max_turns, log_step=log_step)
    return IntakeOutcome(status=outcome.status, brief=ctx.brief, accepted=ctx.accepted, rejected=ctx.rejected,
                         summary=outcome.final_text, usage=outcome.usage, error=outcome.error)
