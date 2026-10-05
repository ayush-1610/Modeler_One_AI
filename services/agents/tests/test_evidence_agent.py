"""T-44: agent A2 on Europe PMC (mocked) — stored texts, verified quotes, access requests, graded evidence."""

from __future__ import annotations

import json

import httpx
import pytest

from modeler_agents.evidence_agent import ResearchContext, run_research
from modeler_agents.llm import ChatResult, ToolCall
from modeler_agents.sources import EuropePMC, jats_to_text
from modeler_project import ArtifactKind, FileProjectStore, Workspace
from modeler_project.brief import empty_brief
from modeler_project.documents import DocumentLibrary
from modeler_project.evidence_register import items
from modeler_project.requirements import derive, literature_items

pytestmark = pytest.mark.req("T-44")

JATS = """<article><front><article-meta><title-group><article-title>Pharmacokinetics of exampleamide</article-title>
</title-group><abstract><p>We measured plasma protein binding.</p></abstract></article-meta></front><body>
<sec><title>Results</title><p>The fraction unbound in human plasma was 9.1 % by equilibrium dialysis at 1 µM.</p>
<table-wrap><label>Table 2</label><caption><p>Physicochemical properties</p></caption><table>
<tr><th>Property</th><th>Value</th></tr><tr><td>logD7.4</td><td>2.1</td></tr></table></table-wrap></sec></body></article>"""

SEARCH = {"resultList": {"result": [
    {"id": "111", "source": "MED", "pmid": "111", "pmcid": "PMC9", "doi": "10.1/oa", "title": "Pharmacokinetics of exampleamide",
     "authorString": "Doe J, Roe R.", "journalInfo": {"journal": {"title": "Clin Pharmacokinet"}}, "pubYear": "2019",
     "isOpenAccess": "Y", "abstractText": "Exampleamide has an oral bioavailability of 78 %."},
    {"id": "222", "source": "MED", "pmid": "222", "pmcid": None, "doi": "10.1/closed", "title": "Closed paper",
     "authorString": "Smith A.", "journalInfo": {"journal": {"title": "J Pharm"}}, "pubYear": "2015", "isOpenAccess": "N"}]}}


def _transport(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/search"):
        return httpx.Response(200, json=SEARCH)
    if request.url.path.endswith("/PMC9/fullTextXML"):
        return httpx.Response(200, text=JATS)
    return httpx.Response(404)


def test_jats_tables_become_quotable_rows():
    text = jats_to_text(JATS)
    assert text.startswith("# Pharmacokinetics of exampleamide")
    assert "[Table 2] Physicochemical properties" in text and "logD7.4 | 2.1" in text


class Scripted:
    provider, model = "test", "scripted"

    def __init__(self, ctx):
        self.ctx = ctx
        self.turn = 0

    def complete(self, messages, tools):
        self.turn += 1
        calls = []
        if self.turn == 1:
            calls = [("list_requirements", {}), ("search_literature", {"query": "exampleamide protein binding"})]
        elif self.turn == 2:
            calls = [("read_full_text", {"paper_id": "111"}), ("read_full_text", {"paper_id": "222"})]
        elif self.turn == 3:
            sha = next(v.content["sha256"] for v in self.ctx.library.documents() if v.content["name"].startswith("fulltext"))
            calls = [
                ("propose_value", {"req_id": "REQ-bind.fu", "target": "bind.fu", "value": "9.1", "unit": "%",
                                   "quote": "fraction unbound in human plasma was 9.1 %", "doc_sha256": sha, "page": 1,
                                   "source_type": "PUBLICATION", "locator": "Results",
                                   "conditions": {"species": "human", "matrix": "plasma", "method": "equilibrium dialysis",
                                                  "drug concentration": "1 µM"}}),
                ("propose_value", {"req_id": "REQ-phys.logp", "target": "phys.logp", "value": "2.1", "quote": "logD7.4 | 2.1",
                                   "doc_sha256": sha, "page": 1, "source_type": "PUBLICATION", "locator": "Table 2",
                                   "conditions": {"type": "logD", "pH": "7.4"}}),
                ("propose_value", {"req_id": "REQ-bind.fu", "target": "bind.fu", "value": "0.2", "quote": "invented sentence here",
                                   "doc_sha256": sha, "page": 1, "source_type": "PUBLICATION"}),
                ("propose_value", {"req_id": "REQ-bind.fu", "target": "phys.logp", "value": "2", "quote": "x" * 20,
                                   "doc_sha256": sha, "page": 1, "source_type": "PUBLICATION"}),
                ("request_full_text", {"title": "Closed paper", "authors": "Smith A.", "needed_for": "solubility",
                                       "doi": "10.1/closed"}),
                ("mark_not_found", {"req_id": "REQ-phys.pka", "searched": "exampleamide pKa; europe pmc"}),
            ]
        return ChatResult(content="" if calls else "fu found; logD found; pKa not found", finish_reason="", model="s",
                          usage={"input_tokens": 1, "output_tokens": 1},
                          tool_calls=tuple(ToolCall(id=f"c{i}", name=n, arguments=a) for i, (n, a) in enumerate(calls)))


def test_a2_stores_what_it_reads_and_only_verified_values_enter_the_register(tmp_path):
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    ctx = ResearchContext(ws=ws, library=DocumentLibrary(ws), requirements=literature_items(derive(empty_brief("X", by="u"))),
                          actor="agent:ar_2", europe_pmc=EuropePMC(transport=httpx.MockTransport(_transport)))
    outcome = run_research(Scripted(ctx), ctx, drug="Exampleamide")
    assert outcome.status == "COMPLETED"
    assert {r["code"] for r in outcome.rejected} == {"INVALID_CITATION", "WRONG_TARGET"}
    evidence = {e.target: e for e in items(ws)}
    fu = evidence["bind.fu"]
    assert fu.value_pksim == pytest.approx(0.091) and fu.confidence == "A" and fu.source.doi == "10.1/oa"
    assert fu.source.title == "Pharmacokinetics of exampleamide" and fu.source.year == 2019
    assert evidence["phys.logp"].source.locator == "Table 2"
    assert len(ws.list(ArtifactKind.ACCESS_REQUEST)) == 1 and outcome.not_found == {"REQ-phys.pka": "exampleamide pKa; europe pmc"}
    assert json.loads(json.dumps(outcome.usage))["input_tokens"] == 4
