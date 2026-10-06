"""Agent A2 · Literature Parameter Agent (plan §14.2, T-44): find measured values for the data plan's literature items.

Works like a literature-review scientist: searches open literature (Europe PMC), reads abstracts and open-access full
texts, and the documents the team uploaded, and proposes values with the exact quote, page and conditions. Every text
it reads is stored as a document first, so every proposal is checked by code against exactly that text (quote found
verbatim; numbers stated; requirement and target known). Code converts units and grades confidence; a person accepts
or rejects each proposal. A paper that is not open access becomes an access request, never an unofficial copy.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from modeler_agents.citations import quote_appears_in, value_stated_in_quote
from modeler_agents.llm import ChatModel, Tool, run_tool_loop
from modeler_agents.sources import EuropePMC, SourceError
from modeler_agents.web_search import search_tool
from modeler_project.documents import DocumentLibrary
from modeler_project.evidence import EvidenceItem, Extraction, SourceRef, SourceType, new_id
from modeler_project.evidence_register import propose, request_access
from modeler_project.requirements import RequirementItem
from modeler_project.workspace import Workspace

SYSTEM_PROMPT = """You find input values for a PBPK model built in PK-Sim that may be submitted to regulators. Work like a literature-review scientist: look for measured values in primary sources and record exactly where each value comes from.

Sources, most to least preferred: regulatory review documents (FDA clinical pharmacology / biopharmaceutics reviews, EMA assessment reports); peer-reviewed publications with measured data; the documents the team uploaded; curated databases. A value a database computed or predicted (e.g. a computed logP) is a prediction: propose it only when no measured value exists, with source_type PREDICTED.

Rules:
- Read before proposing: search_literature, then read_abstract or read_full_text (open access only), or search_documents / read_page for uploaded documents. Every proposal cites a document sha256 and page that you read, with a quote copied exactly from that page (at least 12 characters) containing the value.
- Use the requirement ids and targets listed by list_requirements. For a parameter of a specific enzyme or transporter use the concrete target (e.g. elim.hepatic.UGT1A9.clspec for a UGT1A9 intrinsic clearance; record the in vitro value with its unit, the IVIVE is done later by a person).
- Report values and units exactly as the source states them; do not convert, do not average. When sources disagree, propose each value separately.
- Record the conditions that give the value its meaning (species, matrix, method, concentration, pH, temperature, system, fu,inc, cell line, direction) in `conditions` as an object.
- When a relevant paper is not open access, call request_full_text and continue with other sources.
- If web_search is available, use it to find primary sources (papers, regulatory reviews, labels) that Europe PMC does not
  reach. Each result page is stored; read it with read_page and quote from it. Never cite a value from a search result
  you have not read.
- When nothing is found for an item after a reasonable search, call mark_not_found with what you searched.
- Call several tools in one turn whenever you can. Finish with a short summary per requirement: found, not found, conflicting."""


@dataclass
class ResearchContext:
    ws: Workspace
    library: DocumentLibrary
    requirements: list[RequirementItem]
    actor: str
    europe_pmc: EuropePMC
    proposed: list[str] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    not_found: dict[str, str] = field(default_factory=dict)
    access_requests: list[str] = field(default_factory=list)
    papers: dict[str, Any] = field(default_factory=dict)   # id -> Paper seen in searches


def _target_allowed(requirement: RequirementItem, target: str) -> bool:
    base = requirement.target.split("{", 1)[0].rstrip(".")
    return target == requirement.target or target == base or target.startswith(base + ".")


def _reject(ctx: ResearchContext, code: str, message: str, **detail: Any) -> str:
    ctx.rejected.append({"code": code, "message": message, **detail})
    return f"REJECTED {code}: {message}"


def propose_value(ctx: ResearchContext, *, req_id: str, target: str, value: Any, unit: str = "", quote: str,
                  doc_sha256: str, page: int, source_type: str = "PUBLICATION", locator: str = "",
                  conditions: dict[str, Any] | str | None = None, note: str = "") -> str:
    requirement = next((r for r in ctx.requirements if r.req_id == req_id), None)
    if requirement is None:
        return _reject(ctx, "UNKNOWN_REQUIREMENT", "use a req_id from list_requirements", req_id=req_id)
    if not _target_allowed(requirement, target):
        return _reject(ctx, "WRONG_TARGET", f"{req_id} covers {requirement.target}", req_id=req_id, target=target)
    try:
        kind = SourceType(source_type)
    except ValueError:
        return _reject(ctx, "INVALID_SOURCE_TYPE", f"use one of {', '.join(s.value for s in SourceType)}")
    text = ctx.library.page_text(doc_sha256, int(page))
    if text is None:
        return _reject(ctx, "UNKNOWN_PAGE", "read the document first (read_abstract / read_full_text / read_page)")
    if not quote_appears_in(text, quote):
        return _reject(ctx, "INVALID_CITATION", "the quote was not found verbatim on that page; copy it exactly",
                       req_id=req_id)
    if isinstance(conditions, str):
        try:
            conditions = json.loads(conditions) if conditions.strip() else {}
        except json.JSONDecodeError:
            conditions = {"as stated": conditions}
    number: float | None
    try:
        number = float(str(value).replace(",", "").split()[0])
    except (ValueError, IndexError):
        number = None
    doc = ctx.library.by_sha(doc_sha256)
    meta = (doc.content.get("note") or "") if doc else ""
    paper = ctx.papers.get(meta.split("paper:", 1)[1].split()[0]) if "paper:" in meta else None
    source = SourceRef(doc_sha256=doc_sha256, page=int(page), locator=locator,
                       title=getattr(paper, "title", "") or (doc.content["name"] if doc else ""),
                       authors=getattr(paper, "authors", ""), year=getattr(paper, "year", None),
                       doi=getattr(paper, "doi", None), pmid=getattr(paper, "pmid", None))
    item = EvidenceItem(id=new_id(), req_id=req_id, target=target, value=number if number is not None else str(value),
                        unit=unit or None, source_type=kind, source=source, quote=quote, extraction=Extraction.TEXT,
                        conditions={str(k): str(v) for k, v in (conditions or {}).items()},
                        purpose=requirement.purpose or "model_building", provider="LITERATURE", note=note)
    stated = value_stated_in_quote(number, quote) if number is not None else None
    stored = propose(ctx.ws, item, actor=ctx.actor, requirement=requirement, value_in_quote=stated)
    ctx.proposed.append(stored.id)
    flags = f"; flags: {', '.join(stored.flags)}" if stored.flags else ""
    return f"RECORDED {stored.id} grade {stored.confidence}{flags}"


def reading_tools(ctx: ResearchContext, *, kinds: tuple[str, ...] = ("parameter", "formulation", "system")) -> list[Tool]:
    def list_requirements() -> str:
        rows = []
        for r in ctx.requirements:
            if r.kind not in kinds:
                continue
            rows.append({"req_id": r.req_id, "label": r.label, "target": r.target, "unit_in_pksim": r.unit,
                         "record_conditions": list(r.conditions), "criticality": r.criticality,
                         "client_item_cross_check": r.cross_check})
        return json.dumps(rows)

    def search_literature(query: str, max_results: int = 10) -> str:
        try:
            papers = ctx.europe_pmc.search(query, page_size=int(max_results))
        except SourceError as exc:
            return f"ERROR: {exc}"
        for p in papers:
            ctx.papers[p.id] = p
        return "\n".join(f"id {p.id} | pmid {p.pmid or '-'} | pmcid {p.pmcid or '-'} | {p.year} | {p.journal} | "
                         f"{'open access' if p.open_access else 'not open access'} | {p.title}" for p in papers) or "no hits"

    def read_abstract(paper_id: str) -> str:
        paper = ctx.papers.get(paper_id)
        if paper is None:
            return "ERROR: search for the paper first (search_literature)"
        if not paper.abstract:
            return "ERROR: no abstract available"
        text = f"{paper.title}\n{paper.authors}. {paper.journal} {paper.year}. doi {paper.doi}\n\n{paper.abstract}"
        doc = ctx.library.add_text(text, f"abstract-{paper_id}.md", role="paper", by=ctx.actor,
                                   note=f"paper:{paper_id} abstract from Europe PMC")
        return f"doc_sha256 {doc.content['sha256']} page 1\n{text}"

    def read_full_text(paper_id: str) -> str:
        paper = ctx.papers.get(paper_id)
        if paper is None:
            return "ERROR: search for the paper first (search_literature)"
        if not (paper.open_access and paper.pmcid):
            return "NOT OPEN ACCESS: call request_full_text if the paper is needed"
        try:
            text = ctx.europe_pmc.full_text(paper.pmcid)
        except SourceError as exc:
            return f"ERROR: {exc}"
        doc = ctx.library.add_text(text, f"fulltext-{paper.pmcid}.md", role="paper", by=ctx.actor,
                                   note=f"paper:{paper_id} open-access full text from Europe PMC")
        first = ctx.library.page_text(doc.content["sha256"], 1) or ""
        return f"doc_sha256 {doc.content['sha256']} pages {doc.content['n_pages']}\n--- page 1 ---\n{first}"

    def read_page(doc_sha256: str, page: int) -> str:
        text = ctx.library.page_text(doc_sha256, int(page))
        return text if text is not None else "ERROR: no such document page"

    def search_documents(query: str, max_results: int = 8) -> str:
        hits = ctx.library.search(query, max(1, min(int(max_results), 20)))
        return "\n".join(f"{h.doc_sha256} p.{h.page} {h.title}: {h.snippet}" for h in hits) or "no matches"

    def request_full_text(title: str, authors: str, needed_for: str, doi: str = "", journal: str = "", year: int = 0) -> str:
        request_id, created = request_access(ctx.ws, title=title, authors=authors, doi=doi or None, journal=journal or None,
                                             year=year or None, needed_for=needed_for, by=ctx.actor)
        if created:
            ctx.access_requests.append(request_id)
        return f"{'RECORDED' if created else 'ALREADY REQUESTED'} {request_id}; continue with other sources"

    def mark_not_found(req_id: str, searched: str) -> str:
        ctx.not_found[req_id] = searched
        return f"NOTED: {req_id} not found"

    def store_page(result: dict[str, str]) -> str:
        """A web search result page, stored as a document so a quote from it is checked verbatim."""
        text = f"{result['title']}\n{result['url']}\n\n{result['content']}"
        name = "web-" + "".join(ch if ch.isalnum() else "-" for ch in result["url"].split("//", 1)[-1])[:80] + ".md"
        doc = ctx.library.add_text(text, name, role="retrieved_record", by=ctx.actor, note=f"web:{result['url']} (web search)")
        return doc.content["sha256"]

    s = {"type": "string"}
    web = search_tool(store_page)
    return [*([web] if web is not None else []),
        Tool("list_requirements", "The data-plan items to find, with the conditions to record.",
             {"type": "object", "properties": {}}, list_requirements),
        Tool("search_literature", "Search Europe PMC (PubMed, PMC). Returns ids, years, journals, open-access status.",
             {"type": "object", "properties": {"query": s, "max_results": {"type": "integer"}}, "required": ["query"]},
             search_literature),
        Tool("read_abstract", "Store and return the abstract of a paper from the last searches.",
             {"type": "object", "properties": {"paper_id": s}, "required": ["paper_id"]}, read_abstract),
        Tool("read_full_text", "Store and return page 1 of an open-access paper's full text (tables as rows).",
             {"type": "object", "properties": {"paper_id": s}, "required": ["paper_id"]}, read_full_text),
        Tool("read_page", "Return one page of a stored document.",
             {"type": "object", "properties": {"doc_sha256": s, "page": {"type": "integer"}}, "required": ["doc_sha256", "page"]},
             read_page),
        Tool("search_documents", "Keyword search over the uploaded and stored documents.",
             {"type": "object", "properties": {"query": s, "max_results": {"type": "integer"}}, "required": ["query"]},
             search_documents),
        Tool("request_full_text", "Ask a person to supply a paper that is not open access.",
             {"type": "object", "properties": {"title": s, "authors": s, "needed_for": s, "doi": s, "journal": s,
                                               "year": {"type": "integer"}}, "required": ["title", "authors", "needed_for"]},
             request_full_text),
        Tool("mark_not_found", "Record that nothing usable was found for a requirement, and what was searched.",
             {"type": "object", "properties": {"req_id": s, "searched": s}, "required": ["req_id", "searched"]},
             mark_not_found),
    ]


def build_tools(ctx: ResearchContext) -> list[Tool]:
    """A2: the reading tools plus propose_value."""
    s = {"type": "string"}
    return [*reading_tools(ctx), Tool(
        "propose_value", "Propose one value for a requirement, with a verbatim quote from a page you read.",
        {"type": "object", "properties": {
            "req_id": s, "target": s, "value": s, "unit": s, "quote": s, "doc_sha256": s, "page": {"type": "integer"},
            "source_type": {"type": "string", "enum": [t.value for t in SourceType]}, "locator": s,
            "conditions": {"type": "object", "description": "e.g. {\"species\": \"human\", \"method\": \"equilibrium dialysis\"}"},
            "note": s},
         "required": ["req_id", "target", "value", "quote", "doc_sha256", "page", "source_type"]},
        lambda **kw: propose_value(ctx, **kw))]


@dataclass
class ResearchOutcome:
    status: str
    proposed: list[str]
    rejected: list[dict[str, Any]]
    not_found: dict[str, str]
    access_requests: list[str]
    summary: str
    usage: dict[str, int]
    error: str = ""


def run_research(model: ChatModel, ctx: ResearchContext, *, drug: str, max_turns: int = 120,
                 log_step: Callable[[dict[str, Any]], None] = lambda s: None) -> ResearchOutcome:
    user = (f"Drug: {drug}. Find values for every requirement listed by list_requirements "
            f"({len(ctx.requirements)} items). Start with list_requirements.")
    outcome = run_tool_loop(model, system=SYSTEM_PROMPT, user=user, tools=build_tools(ctx), max_turns=max_turns,
                            log_step=log_step)
    return ResearchOutcome(status=outcome.status, proposed=ctx.proposed, rejected=ctx.rejected, not_found=ctx.not_found,
                           access_requests=ctx.access_requests, summary=outcome.final_text, usage=outcome.usage,
                           error=outcome.error)
