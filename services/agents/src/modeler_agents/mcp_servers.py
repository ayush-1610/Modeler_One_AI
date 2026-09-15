"""MCP servers the research agents may use, and the recording layer between them and the agent.

Servers run inside the platform's network (self-hosted, pinned versions); public hosted endpoints are not used
for client work. Every tool result is stored as a retrieved record with a content hash, so a value the agent
proposes from it can be checked word for word against exactly what the source returned.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    transport: Literal["stdio", "http"]
    license: str
    command: str | None = None
    args: tuple[str, ...] = ()
    env: dict[str, str] | None = None
    url: str | None = None
    allowed_tools: frozenset[str] | None = None  # None: every tool the server lists


DEFAULT_SERVERS = (
    # BioMCP (MIT): PubMed/PubTator3, Europe PMC, ClinicalTrials.gov, OpenFDA, Drugs@FDA, ChEMBL, MyChem.
    # Run inside the network with: biomcp serve-http --host 127.0.0.1 --port 8080
    MCPServerConfig(name="biomcp", transport="http", license="MIT", url="http://127.0.0.1:8080/mcp"),
    MCPServerConfig(
        name="chembl",
        transport="stdio",
        license="Apache-2.0",
        command="npx",
        args=("-y", "@cyanheads/chembl-mcp-server@0.2.4"),
        env={"MCP_TRANSPORT_TYPE": "stdio"},
        allowed_tools=frozenset(
            {"chembl_search_molecules", "chembl_get_bioactivities", "chembl_search_targets", "chembl_get_drug_info", "chembl_get_assay"}
        ),
    ),
    MCPServerConfig(
        name="pubchem",
        transport="stdio",
        license="Apache-2.0",
        command="npx",
        args=("-y", "@cyanheads/pubchem-mcp-server@0.6.2"),
        env={"MCP_TRANSPORT_TYPE": "stdio"},
        allowed_tools=frozenset(
            {"pubchem_search_compounds", "pubchem_get_compound_details", "pubchem_get_compound_xrefs", "pubchem_get_bioactivity", "pubchem_get_summary"}
        ),
    ),
)


@asynccontextmanager
async def open_mcp_sessions(servers: tuple[MCPServerConfig, ...] = DEFAULT_SERVERS) -> AsyncIterator[dict[str, ClientSession]]:
    async with AsyncExitStack() as stack:
        sessions: dict[str, ClientSession] = {}
        for server in servers:
            if server.transport == "http":
                read, write = await stack.enter_async_context(streamable_http_client(server.url))
            else:
                params = StdioServerParameters(command=server.command, args=list(server.args), env=server.env)
                read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            sessions[server.name] = session
        yield sessions


@dataclass(frozen=True)
class RetrievedRecord:
    doc_sha256: str
    server: str
    tool: str
    arguments: dict[str, Any]
    retrieved_at: str
    text: str
    is_error: bool


@dataclass
class RetrievalStore:
    """Citable store of everything the agent retrieved, layered over the tenant's document library."""

    library: Any = None  # a DocumentStore (search, page_text) for uploaded documents, optional
    records: dict[str, RetrievedRecord] = field(default_factory=dict)

    def add(self, *, server: str, tool: str, arguments: dict[str, Any], text: str, is_error: bool = False) -> RetrievedRecord:
        payload = json.dumps({"server": server, "tool": tool, "arguments": arguments, "text": text}, sort_keys=True, ensure_ascii=False)
        sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        record = self.records.get(sha) or RetrievedRecord(sha, server, tool, arguments, datetime.now(UTC).isoformat(), text, is_error)
        self.records[sha] = record
        return record

    def search(self, query: str, max_results: int):
        return self.library.search(query, max_results) if self.library is not None else []

    def page_text(self, doc_sha256: str, page: int) -> str | None:
        record = self.records.get(doc_sha256)
        if record is not None:
            return record.text if page == 1 and not record.is_error else None
        return self.library.page_text(doc_sha256, page) if self.library is not None else None


class RecordingSession:
    """Wraps an MCP ClientSession: stores each tool result and tells the agent how to cite it."""

    def __init__(self, server: str, session: Any, store: RetrievalStore, log_step: Callable[[dict[str, Any]], None]):
        self._server = server
        self._session = session
        self._store = store
        self._log_step = log_step

    async def list_tools(self):
        return await self._session.list_tools()

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None, **kwargs: Any):
        result = await self._session.call_tool(name=name, arguments=arguments, **kwargs)
        text = "\n".join(block.text for block in result.content if getattr(block, "type", None) == "text")
        record = self._store.add(server=self._server, tool=name, arguments=arguments or {}, text=text, is_error=bool(result.is_error))
        self._log_step(
            {"type": "mcp_tool_call", "server": self._server, "tool": name, "arguments": arguments or {}, "doc_sha256": record.doc_sha256, "is_error": record.is_error}
        )
        if record.is_error:
            return result
        note = TextContent(
            type="text",
            text=f"[Retrieved record doc_sha256={record.doc_sha256} page=1. To use a value from it, cite this id with an exact quote.]",
        )
        return result.model_copy(update={"content": [*result.content, note]})
