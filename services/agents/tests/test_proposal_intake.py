"""T-41: agent A1 fills the brief only with verified, cited values and never overrides a person."""

from __future__ import annotations

import pytest

from modeler_agents.llm import ChatResult, ToolCall
from modeler_agents.proposal_intake import IntakeContext, run_proposal_intake
from modeler_agents.run_store import FileRunStore
from modeler_project import FileProjectStore, Workspace
from modeler_project.brief import FieldStatus, empty_brief
from modeler_project.brief_ops import edit_field
from modeler_project.documents import DocumentLibrary

pytestmark = pytest.mark.req("T-41")

PROPOSAL = (b"Technical proposal: PBPK model of dapagliflozin.\n"
            b"Objective: predict the food effect of the 10 mg immediate-release tablet.\n"
            b"Healthy volunteers received a single oral dose of 10 mg under fasted and fed conditions.\n"
            b"The client will provide dissolution profiles in three media.")


class Scripted:
    provider, model = "test", "scripted"

    def __init__(self, turns):
        self.turns = list(turns)

    def complete(self, messages, tools):
        calls = self.turns.pop(0) if self.turns else []
        return ChatResult(content="" if calls else "summary: filled 4 fields", finish_reason="",
                          tool_calls=tuple(ToolCall(id=f"c{i}", name=n, arguments=a) for i, (n, a) in enumerate(calls)),
                          usage={"input_tokens": 5, "output_tokens": 5}, model="scripted")


@pytest.fixture
def library(tmp_path):
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    lib = DocumentLibrary(ws)
    lib.add(PROPOSAL, "proposal.txt", role="proposal", by="u1")
    return lib


def test_a1_records_verified_fields_and_rejects_the_rest(library):
    sha = library.documents()[0].content["sha256"]
    brief = edit_field(empty_brief("Dapagliflozin", by="u1"), "drug.salt_form", value="propanediol monohydrate",
                       status=FieldStatus.EDITED, note="from the client's CMC summary", by="u1")
    model = Scripted([
        [("list_documents", {}), ("read_page", {"doc_sha256": sha, "page": 1})],
        [("propose_field", {"path": "qoi.text", "value": "predict the food effect of the 10 mg IR tablet",
                            "quote": "predict the food effect of the 10 mg immediate-release tablet", "doc_sha256": sha, "page": 1}),
         ("propose_field", {"path": "scenarios[0].dose", "value": "10", "unit": "mg",
                            "quote": "single oral dose of 10 mg under fasted", "doc_sha256": sha, "page": 1}),
         ("propose_field", {"path": "scenarios[0].route", "value": "oral", "quote": "a single oral dose", "doc_sha256": sha,
                            "page": 1}),
         ("propose_field", {"path": "data_plan[0].item", "value": "dissolution profiles in three media",
                            "quote": "The client will provide dissolution profiles in three media", "doc_sha256": sha, "page": 1}),
         ("propose_field", {"path": "data_plan[0].provider", "value": "client",
                            "quote": "The client will provide dissolution profiles", "doc_sha256": sha, "page": 1}),
         # rejected: invented quote, wrong option, locked field, human-only field, skipped index
         ("propose_field", {"path": "scenarios[0].food_state", "value": "fed", "quote": "subjects ate a high-fat breakfast",
                            "doc_sha256": sha, "page": 1}),
         ("propose_field", {"path": "drug.modality", "value": "tablet", "quote": "PBPK model of dapagliflozin",
                            "doc_sha256": sha, "page": 1}),
         ("propose_field", {"path": "drug.salt_form", "value": "free base", "quote": "PBPK model of dapagliflozin",
                            "doc_sha256": sha, "page": 1}),
         ("propose_field", {"path": "acceptance.tier", "value": "high", "quote": "PBPK model of dapagliflozin",
                            "doc_sha256": sha, "page": 1}),
         ("propose_field", {"path": "products[3].name", "value": "tablet", "quote": "10 mg immediate-release tablet",
                            "doc_sha256": sha, "page": 1}),
         ("mark_missing", {"path": "proj.client", "question": "Which company is the client?"})],
        [],
    ])
    ctx = IntakeContext(library=library, brief=brief, actor="agent:ar_1")
    outcome = run_proposal_intake(model, ctx)
    assert outcome.status == "COMPLETED" and outcome.summary.startswith("summary")
    b = outcome.brief
    assert b.get("qoi.text").status is FieldStatus.EXTRACTED and b.get("qoi.text").citations[0].page == 1
    assert b.value("scenarios[0].dose") == 10.0 and b.get("scenarios[0].dose").confidence == "A"
    assert b.value("data_plan[0].provider") == "CLIENT"
    assert {r["code"] for r in outcome.rejected} == {"INVALID_CITATION", "INVALID_VALUE", "LOCKED", "HUMAN_ONLY"}
    assert b.value("drug.salt_form") == "propanediol monohydrate"
    assert [q.field for q in b.questions] == ["proj.client"]


def test_run_store_keeps_steps_and_the_finished_run(tmp_path):
    store = FileRunStore(tmp_path, project_id="p1")
    run_id = store.start_run(tenant_id="t1", agent="A1", provider="litellm", model="m", campaign_id=None, budget={})
    store.record_step(run_id=run_id, seq=1, kind="model_turn", content={"x": 1}, usage={"input_tokens": 3})
    store.finish_run(run_id=run_id, status="COMPLETED", input_tokens=3, output_tokens=1, cost_usd=0.0, summary={"ok": True})
    assert store.get(run_id)["status"] == "COMPLETED" and store.steps(run_id)[0]["content"] == {"x": 1}
    assert [r["run_id"] for r in store.runs("t1", project_id="p1")] == [run_id]


def test_a1_drafts_the_m15_assessment_for_a_person_to_confirm(library):
    # page review 1 (the owner's decisions 1b and 4 of 2026-10-29): suggested ratings and why, DRAFTED, never a value
    sha = library.documents()[0].content["sha256"]
    why_influence = "The food-effect label claim rests on the model, with no fed study of the new tablet"
    why_consequence = "A wrong fed prediction would misdose patients taking the tablet with meals"
    draft = ("draft_risk_assessment", {"influence": "high", "how_the_model_is_used": why_influence,
                                       "consequence": "medium", "what_a_wrong_decision_means": why_consequence})
    model = Scripted([
        [draft],                                                          # refused: nothing to draft from yet
        [("propose_field", {"path": "qoi.text", "value": "predict the food effect of the 10 mg IR tablet",
                            "quote": "predict the food effect of the 10 mg immediate-release tablet", "doc_sha256": sha, "page": 1}),
         ("propose_field", {"path": "qoi.context_of_use", "value": "food-effect labelling",
                            "quote": "under fasted and fed conditions", "doc_sha256": sha, "page": 1}),
         ("propose_field", {"path": "m15.influence_suggested", "value": "low", "quote": "PBPK model of dapagliflozin",
                            "doc_sha256": sha, "page": 1})],                # refused: suggestions come only from the draft
        [("draft_risk_assessment", {**draft[1], "influence": "very high"})],  # refused whole: not a rating
        [draft, ("propose_field", {"path": "m15.influence_rating", "value": "high", "quote": "PBPK model of dapagliflozin",
                                   "doc_sha256": sha, "page": 1})],           # the rating itself stays human-only
        [],
    ])
    ctx = IntakeContext(library=library, brief=empty_brief("Dapagliflozin", by="u1"), actor="agent:ar_2")
    outcome = run_proposal_intake(model, ctx)
    b = outcome.brief
    assert [r["code"] for r in outcome.rejected] == ["NOTHING_TO_DRAFT_FROM", "DRAFT_ONLY", "INVALID_VALUE", "HUMAN_ONLY"]
    for path, value in (("m15.influence_suggested", "high"), ("m15.consequence_suggested", "medium"),
                        ("m15.influence", why_influence), ("m15.consequence", why_consequence)):
        record = b.get(path)
        assert record.status is FieldStatus.DRAFTED and record.value == value and b.value(path) is None
        assert [c.quote for c in record.citations] == ["predict the food effect of the 10 mg immediate-release tablet",
                                                      "under fasted and fed conditions"]
    assert b.get("m15.influence_rating").status is FieldStatus.MISSING and b.value("acceptance.tier") is None
    # a person confirms the draft: it becomes their value; the agent then keeps it on a second draft
    b = edit_field(b, "m15.influence", status=FieldStatus.CONFIRMED, by="u1")
    assert b.value("m15.influence") == why_influence and b.get("m15.influence").by == "u1"
    ctx2 = IntakeContext(library=library, brief=b, actor="agent:ar_3")
    result = run_proposal_intake(Scripted([[("draft_risk_assessment", {**draft[1], "how_the_model_is_used": "x" * 30})], []]), ctx2)
    assert result.brief.value("m15.influence") == why_influence
