"""Literature and database research agent.

Claude searches open sources through self-hosted MCP servers (PubMed, Europe PMC, ClinicalTrials.gov, OpenFDA
and Drugs@FDA via BioMCP; ChEMBL; PubChem) and the tenant's uploaded documents. It proposes parameter values
with verifiable citations, lists studies with observed PK data worth extracting, and files an access request
(title, authors, DOI) for any paper it cannot read legally. People review every proposal.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from anthropic import beta_async_tool
from anthropic.lib.tools.mcp import async_mcp_tool
from pydantic import BaseModel

from modeler_agents.citations import quote_appears_in
from modeler_agents.mcp_servers import MCPServerConfig, RecordingSession, RetrievalStore
from modeler_agents.parameter_curation import CurationContext, ParameterProposal, record_proposal

SYSTEM_PROMPT = """You research input data for PBPK models built in PK-Sim that may be submitted to regulators.

Find values for the requested parameters and studies with observed pharmacokinetic data for the compound, using the tools available: literature and regulatory databases, ChEMBL and PubChem, and the client's uploaded documents. A PBPK scientist reviews everything you propose, so a gap you report is more useful than a doubtful value.

Sources, most to least preferred: regulatory review documents (FDA clinical pharmacology and biopharmaceutics reviews, EMA assessment reports), peer-reviewed publications with measured data, the client's own study reports, curated databases. Values that a database calculated or predicted (for example computed logP) are predictions: propose them only when no measured value exists, and say so in the note.

- Every proposed value needs a citation: the doc_sha256 and page shown with the retrieved record or document, and a quote copied exactly from that text that contains the value.
- Record conditions that change a value's meaning (species, matrix, protein concentration, fu,inc, pH, temperature, assay) and report values in the units the source uses.
- When sources disagree, propose each value separately; do not average or choose.
- When a relevant paper's full text is not available through the tools, call request_full_text with its title, authors and DOI and continue with other sources. Only use content the tools return; never use unofficial copies of articles.
- For studies that report concentration-time data or PK parameters useful for model building or validation, call propose_observed_study.
- Finish with a short summary of what was found, what is missing, and which access requests were filed."""


class AccessRequest(BaseModel):
    title: str
    authors: str
    doi: str | None
    journal: str | None
    year: int | None
    needed_for: str


class ObservedStudyCandidate(BaseModel):
    reference: str
    description: str
    doc_sha256: str
    page: int
    quote: str


@dataclass
class LiteratureContext(CurationContext):
    access_requests: list[AccessRequest] = field(default_factory=list)
    observed_studies: list[ObservedStudyCandidate] = field(default_factory=list)


@dataclass
class ResearchOutcome:
    status: Literal["COMPLETED", "INCOMPLETE", "REFUSED"]
    proposals: list[ParameterProposal]
    rejections: list[dict[str, Any]]
    access_requests: list[AccessRequest]
    observed_studies: list[ObservedStudyCandidate]
    summary: str


def record_access_request(
    ctx: LiteratureContext, *, title: str, authors: str, doi: str | None, journal: str | None, year: int | None, needed_for: str
) -> str:
    key = (doi or title).strip().lower()
    if any((r.doi or r.title).strip().lower() == key for r in ctx.access_requests):
        return "ALREADY REQUESTED; continue with other sources"
    ctx.access_requests.append(AccessRequest(title=title, authors=authors, doi=doi, journal=journal, year=year, needed_for=needed_for))
    return "RECORDED access request; a person will supply the full text. Continue with other sources."


def record_observed_study(ctx: LiteratureContext, *, reference: str, description: str, doc_sha256: str, page: int, quote: str) -> str:
    text = ctx.documents.page_text(doc_sha256, page)
    if text is None or not quote_appears_in(text, quote):
        ctx.rejections.append({"code": "INVALID_CITATION", "parameter": "observed_study", "doc_sha256": doc_sha256, "page": page, "message": reference})
        return "REJECTED INVALID_CITATION: the quote was not found verbatim in that record or page"
    ctx.observed_studies.append(ObservedStudyCandidate(reference=reference, description=description, doc_sha256=doc_sha256, page=page, quote=quote))
    return "RECORDED observed-data study for extraction review"


def build_platform_tools(ctx: LiteratureContext) -> list:
    @beta_async_tool
    async def propose_parameter(
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
            value: The numeric value as stated in the source.
            unit: The unit as stated in the source; empty string for dimensionless values.
            source_type: InVitro, Publication, Database, or Assumption.
            doc_sha256: Identifier of the retrieved record or uploaded document.
            page: Page number (1 for retrieved records).
            quote: Exact text from that record or page containing the value.
            conditions: Experimental conditions that qualify the value.
            note: Anything the curator should know, e.g. 'computed by ChEMBL, not measured'.
        """
        return record_proposal(
            ctx, parameter=parameter, value=value, unit=unit or None, source_type=source_type,
            doc_sha256=doc_sha256, page=page, quote=quote, conditions=conditions, note=note,
        )

    @beta_async_tool
    async def read_document_page(doc_sha256: str, page: int) -> str:
        """Return the text of an uploaded document page or of a retrieved record (page 1).

        Args:
            doc_sha256: Document or retrieved-record identifier.
            page: 1-based page number.
        """
        return ctx.documents.page_text(doc_sha256, page) or "ERROR: no such document page"

    @beta_async_tool
    async def search_uploaded_documents(query: str, max_results: int = 8) -> str:
        """Search documents the client uploaded (study reports, investigator's brochure, licensed papers).

        Args:
            query: Keywords.
            max_results: Maximum number of hits (1-20).
        """
        hits = ctx.documents.search(query, max(1, min(max_results, 20)))
        return "\n".join(f"{h.doc_sha256} p.{h.page} {h.title}: {h.snippet}" for h in hits) or "no matches"

    @beta_async_tool
    async def request_full_text(title: str, authors: str, needed_for: str, doi: str = "", journal: str = "", year: int = 0) -> str:
        """Ask a person to supply the full text of a paper the tools cannot access.

        Args:
            title: Article title.
            authors: Author list as given in the record.
            needed_for: Which parameters or data this paper is expected to provide.
            doi: DOI if known.
            journal: Journal name if known.
            year: Publication year if known, otherwise 0.
        """
        return record_access_request(
            ctx, title=title, authors=authors, doi=doi or None, journal=journal or None, year=year or None, needed_for=needed_for
        )

    @beta_async_tool
    async def propose_observed_study(reference: str, description: str, doc_sha256: str, page: int, quote: str) -> str:
        """Register a study reporting concentration-time data or PK parameters for later extraction.

        Args:
            reference: Citation (authors, year, journal or report id).
            description: Population, dose, route, formulation, sampling and what is reported (table/figure).
            doc_sha256: Identifier of the retrieved record or document describing the study.
            page: Page number (1 for retrieved records).
            quote: Exact text supporting that the study reports these data.
        """
        return record_observed_study(ctx, reference=reference, description=description, doc_sha256=doc_sha256, page=page, quote=quote)

    return [propose_parameter, read_document_page, search_uploaded_documents, request_full_text, propose_observed_study]


async def build_mcp_tools(
    sessions: Mapping[str, Any],
    servers: tuple[MCPServerConfig, ...],
    store: RetrievalStore,
    log_step: Callable[[dict[str, Any]], None],
) -> list:
    allowed = {s.name: s.allowed_tools for s in servers}
    tools, seen = [], set()
    for name, session in sessions.items():
        recording = RecordingSession(name, session, store, log_step)
        for tool in (await session.list_tools()).tools:
            if allowed.get(name) is not None and tool.name not in allowed[name]:
                continue
            if tool.name in seen:
                log_step({"type": "mcp_tool_skipped", "server": name, "tool": tool.name, "reason": "duplicate name"})
                continue
            seen.add(tool.name)
            tools.append(async_mcp_tool(tool, recording))
    return tools


async def run_literature_research(
    ctx: LiteratureContext,
    llm: Any,
    sessions: Mapping[str, Any],
    servers: tuple[MCPServerConfig, ...],
    log_step: Callable[[dict[str, Any]], None],
) -> ResearchOutcome:
    """Run the research loop. ``ctx.documents`` must be the RetrievalStore that the MCP sessions record into."""
    if not isinstance(ctx.documents, RetrievalStore):
        raise TypeError("ctx.documents must be a RetrievalStore so retrieved records are citable")
    tools = [*await build_mcp_tools(sessions, servers, ctx.documents, log_step), *build_platform_tools(ctx)]
    task = (
        f"Compound: {ctx.compound_name}\n"
        f"Requested parameters: {', '.join(ctx.requested_parameters)}\n"
        "Also identify studies with observed PK data (single and multiple dose, IV and oral, DDI, special populations)."
    )
    runner = llm.async_client.beta.messages.tool_runner(
        model=llm.model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        tools=tools,
        messages=[{"role": "user", "content": task}],
        output_config={"effort": "high"},
        **llm.request_options,
        **llm.beta_options,
    )

    status: Literal["COMPLETED", "INCOMPLETE", "REFUSED"] = "COMPLETED"
    summary = ""
    turn = 0
    async for message in runner:
        turn += 1
        log_step(
            {
                "type": "assistant_message",
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

    return ResearchOutcome(status, list(ctx.proposals), list(ctx.rejections), list(ctx.access_requests), list(ctx.observed_studies), summary)
