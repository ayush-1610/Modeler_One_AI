"""A1's evaluation set (plan 2026-11-05 §3.4, P1's open item): the answer, made through A1's own tools, scores every field
right; a careless reader is caught on what it got wrong, missed, invented, or recorded as the wrong kind."""

from __future__ import annotations

import pytest

from modeler_agents.evals.proposal_intake import PROPOSALS, AnswerModel, evaluate, read, report, score
from modeler_agents.llm import ChatResult, ToolCall

pytestmark = pytest.mark.req("T-41")


def test_the_answer_scores_every_field_right_through_a1s_tools():
    scores = evaluate(AnswerModel)
    assert all(not (s.wrong or s.missed or s.invented or s.status) for s in scores), report(scores)
    assert sum(s.checks for s in scores) >= 30 and len(scores) == len(PROPOSALS)


def test_a_careless_reader_is_caught():
    proposal = next(p for p in PROPOSALS if p.name == "food effect of an IR tablet")

    class Careless:
        provider, model = "test", "careless"

        def __init__(self, _proposal, sha):
            page = {"doc_sha256": sha, "page": 1}
            self.turns = [[
                # a stated route recorded as the wrong value; a salt the proposal never names; the food state as a draft
                ToolCall(id="1", name="propose_field", arguments={"path": "scenarios[0].route", "value": "iv_bolus",
                                                                  "quote": "a single oral dose of 25 mg", **page}),
                ToolCall(id="2", name="propose_field", arguments={"path": "drug.salt_form", "value": "hydrochloride",
                                                                  "quote": "Exampleamide 25 mg immediate-release", **page}),
                ToolCall(id="3", name="propose_field", arguments={"path": "scope.formulation_types", "value": "ir_tablet",
                                                                  "quote": "25 mg immediate-release film-coated tablets",
                                                                  **page})]]

        def complete(self, messages, tools):
            calls = tuple(self.turns.pop(0)) if self.turns else ()
            return ChatResult(content="" if calls else "done", finish_reason="", tool_calls=calls, usage={}, model="c")

    result = score(proposal, read(proposal, Careless))
    assert result.wrong == ["scenarios[0].route (stated): 'iv_bolus'"]
    assert result.invented == ["drug.salt_form (absent)"]
    assert "qoi.applications (implied)" in result.missed and "m15.influence_suggested (draft)" in result.missed
    assert result.status == ["scope.formulation_types (implied): EXTRACTED"]   # an implied field recorded as stated
