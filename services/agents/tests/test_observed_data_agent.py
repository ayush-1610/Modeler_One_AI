"""T-45: agent A3 extracts table data only when every row is quoted from the page and states its numbers."""

from __future__ import annotations

import pytest

from modeler_agents.evidence_agent import ResearchContext
from modeler_agents.llm import ChatResult, ToolCall
from modeler_agents.observed_data_agent import run_observed_data
from modeler_agents.sources import EuropePMC
from modeler_project import ArtifactKind, FileProjectStore, Workspace
from modeler_project.brief import empty_brief
from modeler_project.dataset_register import datasets
from modeler_project.documents import DocumentLibrary
from modeler_project.requirements import derive, literature_items

pytestmark = pytest.mark.req("T-45")

PAPER = """Table 3. Mean (SD) plasma concentrations (ng/mL) after a single 10 mg oral dose (n = 12, fasted)
Time (h) | Concentration (ng/mL)
0.5 | 52.1 (11.0)
1 | 118.4 (25.3)
2 | 97.0 (20.2)
4 | 61.5 (14.8)
8 | 24.9 (6.1)
Table 4. Pharmacokinetic parameters: Cmax 121 ng/mL; AUC0-t 540 ng·h/mL"""

STUDY = {"study_id": "doe-2019-po-10mg", "reference": "Doe 2019", "n": 12, "route": "oral", "dose_mg": 10,
         "formulation": "ir_tablet", "food_state": "fasted", "statistic": "mean_sd"}


class Scripted:
    provider, model = "test", "s"

    def __init__(self, sha):
        self.sha, self.turn = sha, 0

    def complete(self, messages, tools):
        self.turn += 1
        rows = [{"time": t, "value": v, "error": e, "quote": f"{t} | {v} ({e})"} for t, v, e in
                [(0.5, 52.1, 11.0), (1, 118.4, 25.3), (2, 97.0, 20.2), (4, 61.5, 14.8), (8, 24.9, 6.1)]]
        calls = []
        if self.turn == 1:
            calls = [
                ("propose_profile", {"study": STUDY, "time_unit": "h", "unit": "ng/mL", "rows": rows, "doc_sha256": self.sha,
                                     "page": 1, "locator": "Table 3", "n": 12, "error_kind": "SD"}),
                # a row whose quote does not contain its value is refused as a whole
                ("propose_profile", {"study": STUDY, "time_unit": "h", "unit": "ng/mL", "doc_sha256": self.sha, "page": 1,
                                     "rows": [{"time": 1, "value": 150, "quote": "1 | 118.4 (25.3)"}]}),
                ("request_digitization", {"doc_sha256": self.sha, "page": 1, "figure": "Figure 2",
                                          "study_description": "fed arm, 10 mg"}),
            ]
        return ChatResult(content="" if calls else "done", tool_calls=tuple(ToolCall(id=f"c{i}", name=n, arguments=a)
                                                                         for i, (n, a) in enumerate(calls)),
                          finish_reason="", usage={}, model="s")


def test_a3_table_extraction_is_quoted_row_by_row(tmp_path):
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    library = DocumentLibrary(ws)
    sha = library.add(PAPER.encode(), "doe-2019.txt", role="paper", by="u").content["sha256"]
    ctx = ResearchContext(ws=ws, library=library, requirements=literature_items(derive(empty_brief("X", by="u"))),
                          actor="agent:ar_3", europe_pmc=EuropePMC())
    outcome = run_observed_data(Scripted(sha), ctx, drug="Exampleamide")
    found = datasets(ws)
    assert len(found) == 1 and outcome.status == "COMPLETED"
    ds = found[0]
    assert ds.series[0].values == (52.1, 118.4, 97.0, 61.5, 24.9) and ds.series[0].error_kind == "SD"
    assert ds.origin.value == "LITERATURE" and ds.source.locator == "Table 3" and ds.study["n_timepoints"] == 5
    assert len(ws.list(ArtifactKind.ACCESS_REQUEST)) == 1
