from types import SimpleNamespace

from openpyxl import Workbook

from modeler_agents import data_mapping
from modeler_agents.data_mapping import propose_mapping
from modeler_intake.grid import read_workbook
from modeler_intake.recipe_review import RecipeProposal


def one_sheet_workbook(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "PK_SAD"
    ws["A1"], ws["B1"] = "Time (h)", "Concentration (ng/mL)"
    ws["A2"], ws["B2"] = 1, 25.4
    path = tmp_path / "client.xlsx"
    wb.save(path)
    return read_workbook(path, "d" * 64)


def test_propose_mapping_sends_the_sheet_preview_and_uses_structured_output(tmp_path, monkeypatch):
    calls, reviewed = [], []
    proposal = RecipeProposal(tables=[], questions_for_reviewer=["What is the LLOQ?"])

    def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(stop_reason="end_turn", parsed_output=proposal)

    # the proposal is reviewed by code (modeler_intake.recipe_review), exactly as the model returned it
    monkeypatch.setattr(data_mapping, "review_proposal", lambda wb, p, rid: reviewed.append((p, rid)) or "review")
    llm = SimpleNamespace(client=SimpleNamespace(messages=SimpleNamespace(parse=parse)), model="claude-opus-5", request_options={})
    assert propose_mapping(one_sheet_workbook(tmp_path), llm, recipe_id="xyz-101") == "review"
    assert reviewed == [(proposal, "xyz-101")]
    (call,) = calls
    assert call["output_format"] is RecipeProposal
    assert "## Sheet: PK_SAD" in call["messages"][0]["content"] and "Concentration (ng/mL)" in call["messages"][0]["content"]

    def refuse(**kwargs):
        return SimpleNamespace(stop_reason="refusal", parsed_output=None)

    llm.client.messages.parse = refuse
    assert propose_mapping(one_sheet_workbook(tmp_path), llm, recipe_id="xyz-101").issues[0].code == "NO_PROPOSAL"
