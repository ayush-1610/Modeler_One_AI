from types import SimpleNamespace

import pytest
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool

from modeler_agents.literature import (
    LiteratureContext,
    record_access_request,
    record_observed_study,
    run_literature_research,
)
from modeler_agents.mcp_servers import MCPServerConfig, RecordingSession, RetrievalStore
from modeler_agents.parameter_curation import record_proposal

PUBCHEM_TEXT = "Compound Example-A. Experimental Properties: LogP 3.14 (shake flask, 25 °C). pKa 6.2 (base)."


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeSession:
    def __init__(self, tools, text=PUBCHEM_TEXT, is_error=False):
        self._tools = tools
        self._text = text
        self._is_error = is_error
        self.calls = []

    async def list_tools(self):
        return ListToolsResult(tools=self._tools)

    async def call_tool(self, name, arguments=None, **kwargs):
        self.calls.append((name, arguments))
        return CallToolResult(content=[TextContent(type="text", text=self._text)], is_error=self._is_error)


def tool(name):
    return Tool.model_validate({"name": name, "description": f"{name} tool", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}}})


def context(store):
    return LiteratureContext(tenant_id="t1", compound_name="Example-A", requested_parameters=["logP", "pKa"], documents=store)


@pytest.mark.anyio
async def test_mcp_results_are_recorded_and_become_citable():
    store = RetrievalStore()
    steps = []
    session = RecordingSession("pubchem", FakeSession([]), store, steps.append)
    result = await session.call_tool("pubchem_get_compound_details", {"query": "Example-A"})

    (record,) = store.records.values()
    assert record.text == PUBCHEM_TEXT
    assert result.content[-1].text.startswith(f"[Retrieved record doc_sha256={record.doc_sha256} page=1")
    assert steps[0]["tool"] == "pubchem_get_compound_details"

    ctx = context(store)
    ok = record_proposal(
        ctx, parameter="logP", value=3.14, unit=None, source_type="Database", doc_sha256=record.doc_sha256, page=1,
        quote="LogP 3.14 (shake flask, 25 °C)",
    )
    assert ok.startswith("RECORDED")
    fabricated = record_proposal(
        ctx, parameter="pKa", value=7.0, unit=None, source_type="Database", doc_sha256=record.doc_sha256, page=1,
        quote="pKa 7.0 (base) measured",
    )
    assert fabricated.startswith("REJECTED INVALID_CITATION")


@pytest.mark.anyio
async def test_error_results_are_not_citable():
    store = RetrievalStore()
    session = RecordingSession("biomcp", FakeSession([], text="upstream timeout", is_error=True), store, lambda s: None)
    await session.call_tool("article_searcher", {"query": "x"})
    (record,) = store.records.values()
    assert store.page_text(record.doc_sha256, 1) is None


def test_access_requests_are_deduplicated_and_observed_studies_need_citations():
    store = RetrievalStore()
    record = store.add(server="biomcp", tool="article_getter", arguments={"pmid": "1"}, text="Plasma concentrations after 10 mg were measured for 48 h in 12 volunteers (Figure 2).")
    ctx = context(store)
    assert record_access_request(ctx, title="A PK study", authors="Doe J", doi="10.1000/xyz", journal=None, year=2020, needed_for="fu").startswith("RECORDED")
    assert record_access_request(ctx, title="A PK study (dup)", authors="Doe J", doi="10.1000/XYZ", journal=None, year=2020, needed_for="fu").startswith("ALREADY")
    assert len(ctx.access_requests) == 1

    assert record_observed_study(
        ctx, reference="Doe 2020", description="SAD 10 mg oral", doc_sha256=record.doc_sha256, page=1,
        quote="Plasma concentrations after 10 mg were measured for 48 h",
    ).startswith("RECORDED")
    assert record_observed_study(ctx, reference="Doe 2020", description="x", doc_sha256=record.doc_sha256, page=1, quote="measured for 72 h in 20 patients").startswith("REJECTED")


@pytest.mark.anyio
async def test_research_loop_offers_allowlisted_mcp_tools_and_platform_tools():
    captured = {}

    class FakeRunner:
        def __aiter__(self):
            async def gen():
                yield SimpleNamespace(
                    model="claude-opus-5", stop_reason="end_turn", usage=SimpleNamespace(to_dict=lambda: {"output_tokens": 5}),
                    content=[SimpleNamespace(type="text", text="Found logP; pKa missing.", to_dict=lambda: {"type": "text"})],
                )
            return gen()

    def tool_runner(**kwargs):
        captured.update(kwargs)
        return FakeRunner()

    llm = SimpleNamespace(
        async_client=SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(tool_runner=tool_runner))),
        model="claude-opus-5", request_options={}, beta_options={},
    )
    servers = (MCPServerConfig(name="pubchem", transport="stdio", license="Apache-2.0", allowed_tools=frozenset({"pubchem_get_compound_details"})),)
    sessions = {"pubchem": FakeSession([tool("pubchem_get_compound_details"), tool("pubchem_get_compound_image")])}
    store = RetrievalStore()
    steps = []
    outcome = await run_literature_research(context(store), llm, sessions, servers, steps.append)

    names = [t.name for t in captured["tools"]]
    assert "pubchem_get_compound_details" in names and "pubchem_get_compound_image" not in names
    assert {"propose_parameter", "request_full_text", "propose_observed_study"} <= set(names)
    assert captured["model"] == "claude-opus-5"
    assert outcome.status == "COMPLETED" and outcome.summary == "Found logP; pKa missing."
