"""Parameter Curation Agent (F-501).

Claude searches the tenant's document library and proposes parameter values with citations. The
agent never writes to a model: proposals land in the provenance ledger as PROPOSED and a curator
accepts or rejects each one. Every proposal is checked deterministically; a quote that is not
found verbatim on the cited page is rejected and the agent is told why.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from anthropic import beta_tool
from pydantic import BaseModel

from modeler_agents.citations import quote_appears_in, value_stated_in_quote
from modeler_agents.providers import LLMConfig

SourceType = Literal["InVitro", "Publication", "Database", "Assumption"]

SYSTEM_PROMPT = """You curate input parameters for PBPK models that are built in PK-Sim and may be submitted to regulators.

Your job is to find values for the requested parameters in the documents available through your tools and to propose each value with an exact citation. A PBPK scientist reviews every proposal before it can enter a model, so a missing value is far better than a doubtful one.

How to work:
- Search the library, read the relevant pages, and call propose_parameter once per value you find.
- The quote must be copied verbatim from the cited page and must contain the number you report or the sentence/table row it comes from.
- Record experimental conditions that change the meaning of a value (species, matrix such as HLM or hepatocytes, protein concentration, fu,inc, pH, temperature, assay type) in `conditions`.
- Report values in the units the document uses; do not convert. Unit conversion is done later by a validated tool.
- When documents disagree, propose each value separately with its own citation; do not average or choose.
- If a proposal is rejected, fix the citation from the page text or move on. Never invent a quote.
- When you have covered every requested parameter you can, finish with a short summary listing which parameters were not found."""


class DocumentHit(BaseModel):
    doc_sha256: str
    title: str
    page: int
    snippet: str


class DocumentStore(Protocol):
    def search(self, query: str, max_results: int) -> list[DocumentHit]: ...

    def page_text(self, doc_sha256: str, page: int) -> str | None: ...


class ParameterProposal(BaseModel):
    proposal_id: str
    parameter: str
    value: float
    unit: str | None
    source_type: SourceType
    doc_sha256: str
    page: int
    quote: str
    conditions: str
    note: str
    value_stated_in_quote: bool


@dataclass
class CurationContext:
    tenant_id: str
    compound_name: str
    requested_parameters: list[str]
    documents: DocumentStore
    max_turns: int = 40
    proposals: list[ParameterProposal] = field(default_factory=list)
    rejections: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class CurationOutcome:
    status: Literal["COMPLETED", "INCOMPLETE", "REFUSED"]
    proposals: list[ParameterProposal]
    rejections: list[dict[str, Any]]
    summary: str


def record_proposal(
    ctx: CurationContext,
    *,
    parameter: str,
    value: float,
    unit: str | None,
    source_type: str,
    doc_sha256: str,
    page: int,
    quote: str,
    conditions: str = "",
    note: str = "",
) -> str:
    """Validate and store one proposal; the returned text is what the agent sees."""

    def reject(code: str, message: str) -> str:
        ctx.rejections.append({"code": code, "parameter": parameter, "doc_sha256": doc_sha256, "page": page, "message": message})
        return f"REJECTED {code}: {message}"

    if parameter not in ctx.requested_parameters:
        return reject("PARAMETER_NOT_REQUESTED", f"requested parameters are: {', '.join(ctx.requested_parameters)}")
    if source_type not in ("InVitro", "Publication", "Database", "Assumption"):
        return reject("INVALID_SOURCE_TYPE", "use InVitro, Publication, Database, or Assumption")
    page_text = ctx.documents.page_text(doc_sha256, page)
    if page_text is None:
        return reject("UNKNOWN_DOCUMENT_PAGE", "that document page is not in the library")
    if not quote_appears_in(page_text, quote):
        return reject("INVALID_CITATION", "the quote was not found verbatim on that page; copy it exactly from the page text")

    proposal = ParameterProposal(
        proposal_id=str(uuid.uuid4()),
        parameter=parameter,
        value=value,
        unit=unit,
        source_type=source_type,  # type: ignore[arg-type]
        doc_sha256=doc_sha256,
        page=page,
        quote=quote,
        conditions=conditions,
        note=note,
        value_stated_in_quote=value_stated_in_quote(value, quote),
    )
    ctx.proposals.append(proposal)
    return f"RECORDED proposal {proposal.proposal_id} for curator review"


def build_tools(ctx: CurationContext) -> list:
    @beta_tool
    def search_documents(query: str, max_results: int = 8) -> str:
        """Search the tenant's literature and study-report library.

        Args:
            query: Keywords, e.g. "midazolam fraction unbound plasma" or "CYP3A4 Ki itraconazole human liver microsomes".
            max_results: Maximum number of page hits to return (1-20).
        """
        hits = ctx.documents.search(query, max(1, min(max_results, 20)))
        return json.dumps([hit.model_dump() for hit in hits])

    @beta_tool
    def read_document_page(doc_sha256: str, page: int) -> str:
        """Return the full text of one page of a library document.

        Args:
            doc_sha256: Document identifier from search_documents.
            page: 1-based page number.
        """
        text = ctx.documents.page_text(doc_sha256, page)
        return text if text is not None else "ERROR: no such document page"

    @beta_tool
    def propose_parameter(
        parameter: str,
        value: float,
        unit: str,
        source_type: str,
        doc_sha256: str,
        page: int,
        quote: str,
        conditions: str = "",
        note: str = "",
    ) -> str:
        """Propose one parameter value for curator review.

        Args:
            parameter: One of the requested parameter names, spelled exactly as requested.
            value: The numeric value as stated in the document.
            unit: The unit as stated in the document; use an empty string for dimensionless values.
            source_type: InVitro, Publication, Database, or Assumption.
            doc_sha256: Document identifier from search_documents.
            page: 1-based page the quote is on.
            quote: Verbatim text from that page supporting the value.
            conditions: Experimental conditions that qualify the value.
            note: Anything the curator should know (e.g. derived from a figure, mean of n=6).
        """
        return record_proposal(
            ctx,
            parameter=parameter,
            value=value,
            unit=unit or None,
            source_type=source_type,
            doc_sha256=doc_sha256,
            page=page,
            quote=quote,
            conditions=conditions,
            note=note,
        )

    return [search_documents, read_document_page, propose_parameter]


def run_parameter_curation(
    ctx: CurationContext,
    llm: LLMConfig,
    log_step: Callable[[dict[str, Any]], None],
) -> CurationOutcome:
    """Run the agent loop. ``log_step`` persists each model turn to ``agent_steps`` (append-only)."""
    task = (
        f"Compound: {ctx.compound_name}\n"
        f"Requested parameters: {', '.join(ctx.requested_parameters)}\n"
        "Find and propose values for these parameters from the library."
    )
    runner = llm.client.beta.messages.tool_runner(
        model=llm.model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        tools=build_tools(ctx),
        messages=[{"role": "user", "content": task}],
        output_config={"effort": "high"},
        **llm.request_options,
        **llm.beta_options,
    )

    status: Literal["COMPLETED", "INCOMPLETE", "REFUSED"] = "COMPLETED"
    summary = ""
    for turn, message in enumerate(runner, start=1):
        log_step(
            {
                "turn": turn,
                "model": message.model,
                "stop_reason": message.stop_reason,
                "usage": message.usage.to_dict(),
                "content": [block.to_dict() for block in message.content],
            }
        )
        if message.stop_reason == "refusal":
            status = "REFUSED"
            break
        summary = "".join(block.text for block in message.content if block.type == "text") or summary
        if turn >= ctx.max_turns:
            status = "INCOMPLETE"
            break

    return CurationOutcome(status=status, proposals=list(ctx.proposals), rejections=list(ctx.rejections), summary=summary)
