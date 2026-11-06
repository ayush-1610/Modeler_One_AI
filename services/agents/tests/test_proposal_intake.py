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
    why_tier = "The label claim rests on the model alone, so the stricter risk, high, is the one to judge it by"
    draft = ("draft_risk_assessment", {"influence": "high", "how_the_model_is_used": why_influence,
                                       "consequence": "medium", "what_a_wrong_decision_means": why_consequence,
                                       "why_this_tier": why_tier})
    model = Scripted([
        [draft],                                                          # refused: nothing to draft from yet
        [("propose_field", {"path": "qoi.text", "value": "predict the food effect of the 10 mg IR tablet",
                            "quote": "predict the food effect of the 10 mg immediate-release tablet", "doc_sha256": sha, "page": 1}),
         ("propose_field", {"path": "qoi.context_of_use", "value": "food-effect labelling",
                            "quote": "under fasted and fed conditions", "doc_sha256": sha, "page": 1}),
         ("propose_field", {"path": "m15.influence_suggested", "value": "low", "quote": "PBPK model of dapagliflozin",
                            "doc_sha256": sha, "page": 1})],                # refused: suggestions come only from the draft
        [("draft_risk_assessment", {**draft[1], "influence": "very high"})],  # refused whole: not a rating
        [("draft_risk_assessment", {**draft[1], "why_this_tier": "stricter"})],  # refused whole: the ratings differ, no reason
        [draft, ("propose_field", {"path": "m15.influence_rating", "value": "high", "quote": "PBPK model of dapagliflozin",
                                   "doc_sha256": sha, "page": 1})],           # the rating itself stays human-only
        [],
    ])
    ctx = IntakeContext(library=library, brief=empty_brief("Dapagliflozin", by="u1"), actor="agent:ar_2")
    outcome = run_proposal_intake(model, ctx)
    b = outcome.brief
    assert [r["code"] for r in outcome.rejected] == ["NOTHING_TO_DRAFT_FROM", "DRAFT_ONLY", "INVALID_VALUE", "NO_TIER_REASON",
                                                     "HUMAN_ONLY"]
    for path, value in (("m15.influence_suggested", "high"), ("m15.consequence_suggested", "medium"),
                        ("m15.influence", why_influence), ("m15.consequence", why_consequence),
                        ("m15.risk_justification", why_tier)):     # the stricter tier's reason (the owner, 2026-11-06)
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


def test_a1_proposes_what_the_proposal_implies_with_the_quote_and_why(library):
    # plan 2026-11-05 §3.4 (build D): the question, context of use, applications, formulation types and routes a proposal
    # usually implies are drafted with the quote and why; a person confirms them; what a person or a document set is kept
    sha = library.documents()[0].content["sha256"]
    why = "a food-effect prediction for the tablet is what the objective asks for"
    brief = edit_field(empty_brief("Dapagliflozin", by="u1"), "qoi.text", value="the person's own question",
                       status=FieldStatus.EDITED, by="u1")
    model = Scripted([
        [("propose_implied", {"path": "qoi.applications", "value": "APP-12 food effect", "why": why, "doc_sha256": sha,
                              "page": 1, "quote": "predict the food effect of the 10 mg immediate-release tablet"}),
         ("propose_implied", {"path": "scope.formulation_types", "value": "ir_tablet", "doc_sha256": sha, "page": 1,
                              "quote": "10 mg immediate-release tablet",
                              "why": "an immediate-release tablet is the only product the proposal names"}),
         ("propose_implied", {"path": "scenarios[0].route", "value": "oral", "doc_sha256": sha, "page": 1,
                              "quote": "received a single oral dose", "why": "the volunteers took the dose by mouth"}),
         # refused: not an implied field, a reason too short, an invented quote, a field the person set, not an option
         ("propose_implied", {"path": "drug.salt_form", "value": "free base", "quote": "PBPK model of dapagliflozin",
                              "doc_sha256": sha, "page": 1, "why": "the proposal names no salt, so it is the free base"}),
         ("propose_implied", {"path": "qoi.context_of_use", "value": "labelling", "quote": "under fasted and fed conditions",
                              "doc_sha256": sha, "page": 1, "why": "food effect"}),
         ("propose_implied", {"path": "qoi.context_of_use", "value": "labelling", "quote": "for the label claim on food",
                              "doc_sha256": sha, "page": 1, "why": "a food-effect study is run to support the label"}),
         ("propose_implied", {"path": "qoi.text", "value": "food effect", "quote": "predict the food effect", "doc_sha256": sha,
                              "page": 1, "why": "the objective states what the model predicts"}),
         ("propose_implied", {"path": "scenarios[1].route", "value": "by mouth", "quote": "received a single oral dose",
                              "doc_sha256": sha, "page": 1, "why": "the volunteers took the dose by mouth"})],
        [],
    ])
    outcome = run_proposal_intake(model, IntakeContext(library=library, brief=brief, actor="agent:ar_4"))
    b = outcome.brief
    assert [r["code"] for r in outcome.rejected] == ["NOT_IMPLIED", "NO_REASON", "INVALID_CITATION", "KEPT", "INVALID_VALUE"]
    for path, value in (("qoi.applications", ["APP-12 food effect"]), ("scope.formulation_types", ["ir_tablet"]),
                        ("scenarios[0].route", "oral")):
        record = b.get(path)
        assert record.status is FieldStatus.DRAFTED and record.value == value and b.value(path) is None   # not a value yet
        assert record.citations[0].page == 1 and "from what the document implies" in record.note
    assert b.value("qoi.text") == "the person's own question"
    assert all(a["implied"] for a in outcome.accepted)
    # a person confirms the draft: it becomes their value; a document that states a field keeps it from an implied one
    b = edit_field(b, "qoi.applications", status=FieldStatus.CONFIRMED, by="u1")
    assert b.value("qoi.applications") == ["APP-12 food effect"] and b.get("qoi.applications").by == "u1"
    stated = Scripted([[("propose_field", {"path": "qoi.context_of_use", "value": "food-effect labelling", "doc_sha256": sha,
                                           "page": 1, "quote": "under fasted and fed conditions"}),
                        ("propose_implied", {"path": "qoi.context_of_use", "value": "labelling", "doc_sha256": sha, "page": 1,
                                             "quote": "under fasted and fed conditions",
                                             "why": "a food-effect study is run to support the label"})], []])
    again = run_proposal_intake(stated, IntakeContext(library=library, brief=b, actor="agent:ar_5"))
    assert [r["code"] for r in again.rejected] == ["KEPT"] and again.brief.value("qoi.context_of_use") == "food-effect labelling"


def test_a1_fills_in_focused_passes_what_its_general_read_left_empty(library):
    # the owner, 2026-11-06: everything Start needs proposed and pre-selected; a long open task loses fields, so each
    # group of Start fields still empty gets a short pass with the proposal's text in the message, then the M15 draft
    sha = library.documents()[0].content["sha256"]
    page = {"doc_sha256": sha, "page": 1}
    seen: list[str] = []

    class Passes:
        provider, model = "test", "passes"

        def complete(self, messages, tools):
            user = messages[1]["content"]
            if any(m.get("role") == "tool" for m in messages) or "Fill the Project Brief" in user:
                return ChatResult(content="done", finish_reason="", tool_calls=(), usage={}, model="p")   # reads nothing
            seen.append(user)
            if "Now fill the question" in user:
                calls = [("propose_field", {"path": "qoi.text", "value": "predict the food effect of the 10 mg IR tablet",
                                            "quote": "predict the food effect of the 10 mg immediate-release tablet", **page}),
                         ("propose_implied", {"path": "qoi.context_of_use", "value": "food-effect labelling", **page,
                                              "quote": "under fasted and fed conditions",
                                              "why": "a fed versus fasted study supports the food statement of the label"}),
                         ("propose_implied", {"path": "qoi.applications", "value": "APP-12 food effect", **page,
                                              "quote": "predict the food effect", "why": "the objective is a food effect"})]
            elif "Now fill the product" in user:
                calls = [("propose_implied", {"path": "scope.formulation_types", "value": "ir_tablet", **page,
                                              "quote": "10 mg immediate-release tablet", "why": "the product is an IR tablet"}),
                         ("propose_field", {"path": "scenarios[0].route", "value": "oral", "quote": "a single oral dose", **page})]
            elif "Now fill what is modelled" in user:
                calls = [("propose_implied", {"path": "scope.pbpk_model", "value": "full", **page,
                                              "quote": "Technical proposal: PBPK model of dapagliflozin",
                                              "why": "a PBPK model of the drug is a whole-body model here"})]
            else:                                                        # the M15 draft
                calls = [("draft_risk_assessment", {
                    "influence": "high", "consequence": "medium",
                    "how_the_model_is_used": "The food-effect claim rests on the model for the new tablet",
                    "what_a_wrong_decision_means": "A wrong fed prediction would misdose patients taking it with meals",
                    "why_this_tier": "The label claim rests on the model alone, so the stricter risk applies"})]
            return ChatResult(content="", finish_reason="", usage={}, model="p",
                              tool_calls=tuple(ToolCall(id=str(i), name=n, arguments=a) for i, (n, a) in enumerate(calls)))

    b = run_proposal_intake(Passes(), IntakeContext(library=library, brief=empty_brief("Dapagliflozin", by="u1"),
                                                    actor="agent:ar_7")).brief
    assert len(seen) == 4 and all("single oral dose of 10 mg" in m for m in seen[:3])    # the proposal's text, in each pass
    assert "drug.modality" in seen[2] and "scope.site_of_action" in seen[2]               # only what is still empty
    for path in ("qoi.text", "qoi.context_of_use", "qoi.applications", "scope.formulation_types", "scenarios[0].route",
                 "scope.pbpk_model", "m15.influence_suggested", "m15.risk_justification"):
        assert b.get(path).value not in (None, "", []), path
    assert b.get("qoi.context_of_use").status is FieldStatus.DRAFTED and b.get("qoi.text").status is FieldStatus.EXTRACTED
