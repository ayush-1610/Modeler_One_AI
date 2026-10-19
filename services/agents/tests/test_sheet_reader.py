"""R3c: the reading agent proposes how to read a client sheet; code checks every proposal and keeps only one it accepts.
A scripted model stands in for the configured one (software test data, not a model's judgement)."""

from __future__ import annotations

import pytest

from modeler_agents.evals.sheet_reading import agent_reader
from modeler_agents.llm import ChatResult, ToolCall
from modeler_agents.sheet_reader import check_reading, read_rows, read_sheet
from modeler_intake.reading_eval import CASES, evaluate, score, workbook
from modeler_intake.sheet_form import Evidence

pytestmark = pytest.mark.req("T-47", "T-21")


def _case(name: str):
    return next(c for c in CASES if c.name == name)


class Scripted:
    """Answers each turn with the next list of tool calls; an empty list ends the run. It keeps what code answered."""

    provider, model = "test", "scripted"

    def __init__(self, turns):
        self.turns = list(turns)
        self.answers: list[str] = []

    def complete(self, messages, tools):
        self.answers += [m["content"] for m in messages if m["role"] == "tool"][len(self.answers):]
        calls = self.turns.pop(0) if self.turns else []
        return ChatResult(content="done", finish_reason="", model="s", usage={"input_tokens": 1, "output_tokens": 1},
                          tool_calls=tuple(ToolCall(id=f"c{i}", name=n, arguments=a) for i, (n, a) in enumerate(calls)))


def _form(case, **changes) -> dict:
    return case.form.model_copy(update=changes).model_dump(mode="json")


def test_a_reading_code_refuses_is_fixed_and_only_the_accepted_one_is_kept():
    case = _case("decimal-comma")
    guessed = _form(case, constants={**case.form.constants, "dose": "10"})          # a dose the sheet never states
    model = Scripted([[("propose_reading", {"form": guessed})], [("propose_reading", {"form": _form(case)})], []])
    reading = read_sheet(model, workbook=workbook(case), sheet=case.sheet, drug=case.drug, actor="agent:test")
    assert model.answers[0].startswith("REJECTED") and "dose 10: cite the cell" in model.answers[0]
    assert "never guessed" in model.answers[0]
    assert model.answers[1].startswith("ACCEPTED") and "12.4" in model.answers[1]       # it hears what code read
    assert reading.form is not None and reading.form.decimal_comma and len(reading.rejected) == 1
    assert score(case, reading.form).exact


def test_a_quote_must_be_in_its_cell_and_state_the_value_it_is_cited_for():
    case = _case("published-mean")
    grid = workbook(case)
    wrong_cell = case.form.model_copy(update={"evidence": [
        Evidence(cell="Mean PK!A1", quote="ng/mL", supports="value unit", field="value_unit", value="ng/mL"),
        Evidence(cell="Mean PK!A1", quote="h", supports="time unit", field="time_unit", value="h")]})
    problems = check_reading(grid, wrong_cell, [])
    assert any("the cell says 'Time (h)', which does not contain 'ng/mL'" in p for p in problems)
    wrong_value = case.form.model_copy(update={"time_unit": "min"})                    # "Time (h)" does not say minutes
    assert any("'h' does not state time_unit min" in p for p in check_reading(grid, wrong_value, []))
    assert check_reading(grid, case.form, []) == []


def test_an_unstated_unit_is_kept_with_a_note_but_an_lloq_is_never_assumed():
    case = _case("wide-subjects")
    no_unit = case.form.model_copy(update={"evidence": [e for e in case.form.evidence if e.field != "time_unit"]})
    model = Scripted([[("propose_reading", {"form": no_unit.model_dump(mode="json"), "unstated": ["time_unit"]})], []])
    reading = read_sheet(model, workbook=workbook(case), sheet=case.sheet, drug=case.drug, actor="agent:test")
    assert reading.form is not None
    assert reading.notes == ["The time unit is not written in the sheet: h is assumed; check it."]
    guessed = case.form.model_copy(update={"lloq": 0.5})
    assert any("lloq 0.5" in p and "never guessed" in p for p in check_reading(workbook(case), guessed, ["lloq"]))


def test_a_reading_that_does_not_apply_is_refused_with_the_problems():
    case = _case("be-times-across")
    no_ns = _form(case, missing_tokens=[])                                              # "NS" is then not a number
    model = Scripted([[("propose_reading", {"form": no_ns})], []])
    reading = read_sheet(model, workbook=workbook(case), sheet=case.sheet, drug=case.drug, actor="agent:test")
    assert reading.form is None and "UNPARSEABLE_VALUE Sheet1!G6" in model.answers[0]


def test_the_agent_can_read_rows_beyond_those_shown():
    case = _case("long-subject-time")
    model = Scripted([[("read_rows", {"first_row": 19, "last_row": 400})], []])
    read_sheet(model, workbook=workbook(case), sheet=case.sheet, drug=case.drug, actor="agent:test")
    assert "21\tLLOQ = 0.5 ng/mL" in model.answers[0] and "\n18\t" not in model.answers[0]
    from modeler_agents.sheet_reader import ReadingContext

    ctx = ReadingContext(workbook=workbook(case), sheet=case.sheet, start=case.form, start_notes=[], actor="a")
    assert read_rows(ctx, first_row=500, last_row=510) == "the sheet has 21 rows"


def test_the_evaluation_scores_the_agent_as_the_api_runs_it():
    """The agent reader starts from code's first filling, as the API does; a model that proposes the person's reading
    gets full marks, so the score measures the model, not the plumbing."""
    by_file = {c.file: c for c in CASES}

    class Oracle(Scripted):
        def complete(self, messages, tools):
            if len(messages) == 2:
                case = next(c for f, c in by_file.items() if f"File {f}," in messages[1]["content"])
                self.turns = [[("propose_reading", {"form": case.form.model_dump(mode="json")})], []]
            return super().complete(messages, tools)

    scores = evaluate(agent_reader(Oracle([])))
    assert [s.case for s in scores if not s.exact] == []
