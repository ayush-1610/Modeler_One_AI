"""D3: the table mapper (contracts §6.2, §8.5; plan §7.4). A scripted model stands in for the configured one: code checks
every spec it proposes on the region's grid, answers ACCEPTED or REJECTED with every finding redacted, and keeps only a
spec it accepted; the model is never shown a digit of the table's body and never types a number. Software test data
(the made-up Exampleamide), not a model's judgement."""

from __future__ import annotations

import hashlib
import inspect
import re

import pytest

from modeler_agents import prose_extractor, table_mapper
from modeler_agents.evals.scripted import Scripted
from modeler_agents.table_mapper import PROMPT_SHA256, SYSTEM_PROMPT, map_table
from modeler_intake import synthetic
from modeler_intake.mapping.execute import execute
from modeler_intake.mapping.fingerprint import header_band
from modeler_intake.mapping.redact import redact
from modeler_intake.mapping.validate import validate_spec
from modeler_intake.mapping_spec import Cite, Constant, MappingSpec
from modeler_intake.source_model import Region, RegionGrid, has_number

pytestmark = pytest.mark.req("T-47", "T-21")

MESSY = synthetic.messy_workbook()
FILES = (MESSY, synthetic.pdf_report(), synthetic.word_report(), synthetic.delimited(), synthetic.template_workbook())
TABLES = [(f, t) for f in FILES for t in f.tables]


def _setup(file: synthetic.SyntheticFile = MESSY, table_id: str = "fasting-individual"):
    table = next(t for t in file.tables if t.id == table_id)
    grid = synthetic.truth_grid(file, table_id)
    region = Region(id=grid.region_id, kind="table", where=table.where, table_kind=table.kind)
    shown = redact(grid, region, file_name=file.name, document_role="data_workbook")
    return table, grid, shown


def _check(grid: RegionGrid):
    return lambda spec: validate_spec(spec, grid)


def _spec(spec: MappingSpec) -> dict:
    return spec.model_dump(mode="json", by_alias=True, exclude_none=True)


def test_a_valid_spec_is_accepted_and_reads_the_table():
    table, grid, shown = _setup()
    model = Scripted([[("propose_mapping", {"spec": _spec(table.spec)})], []])
    steps: list[dict] = []
    mapped = map_table(model, table=shown, check=_check(grid), log_step=steps.append)
    assert model.answers == ["ACCEPTED"]
    assert (mapped.spec, mapped.rejected, mapped.status) == (table.spec, (), "COMPLETED")
    assert mapped.usage == {"input_tokens": 2, "output_tokens": 2} and mapped.prompt_sha256 == PROMPT_SHA256
    assert PROMPT_SHA256 == hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()
    assert [s["type"] for s in steps] == ["model_turn", "tool_result", "model_turn"]
    values = [r for r in execute(mapped.spec, grid).rows if r.statistic == "individual"]
    assert len(values) == 36 and {r.labels["study"] for r in values} == {"230-23"}


def test_an_invalid_spec_is_rejected_with_redacted_findings_and_a_corrected_one_accepted():
    table, grid, shown = _setup()
    wrong = table.spec.model_copy(update={
        "value_unit": "µg/mL",                                                     # the header writes ng/mL
        "constants": (*table.spec.constants[:1], Constant(field="dose", cite=Cite(row=4, column=4)))})   # a body cell
    model = Scripted([[("propose_mapping", {"spec": _spec(wrong)})], [("propose_mapping", {"spec": _spec(table.spec)})], []])
    mapped = map_table(model, table=shown, check=_check(grid))
    rejected, accepted = model.answers
    assert rejected.startswith("REJECTED: ") and accepted == "ACCEPTED"
    assert "UNIT_NOT_STATED at value_unit" in rejected and "CONSTANT_NOT_STATED at constants[1] (dose)" in rejected
    body = grid.cell(4, 4).text
    assert has_number(body) and body not in rejected and "'#.#'" in rejected            # the quoted body cell, redacted
    assert not re.search(r"\d", rejected.split("\n", 1)[1].replace("constants[1]", ""))  # no digit but the spec's index
    assert mapped.rejected == (rejected,) and mapped.spec == table.spec


def test_a_spec_that_types_a_number_is_refused():
    table, grid, shown = _setup()
    typed = table.spec.model_copy(update={"constants": (Constant(field="dose", cite=Cite(near="caption", line=1), text="50"),)})
    model = Scripted([[("propose_mapping", {"spec": _spec(typed)})], []])
    mapped = map_table(model, table=shown, check=_check(grid))
    assert "NUMBER_TYPED at constants[0] (dose)" in model.answers[0] and mapped.spec is None
    # refused by the mapper itself, whatever the region's check says
    lenient = Scripted([[("propose_mapping", {"spec": _spec(typed)})], []])
    assert map_table(lenient, table=shown, check=lambda spec: ()).spec is None
    assert lenient.answers[0].startswith("REJECTED: ") and "NUMBER_TYPED" in lenient.answers[0]


def _sections(message: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = "title"
    for line in message.splitlines():
        if not line:
            continue
        if not line.startswith(" "):
            current = line.split(" ", 1)[0]
        sections.setdefault(current, []).append(line)
    return sections


@pytest.mark.parametrize(("file", "table"), TABLES, ids=[f"{f.name}:{t.id}" for f, t in TABLES])
def test_the_user_message_holds_no_digit_of_the_body(file, table):
    _t, grid, shown = _setup(file, table.id)
    model = Scripted([[]])
    map_table(model, table=shown, check=_check(grid), context="The delivery map names this sheet the main PK listing.")
    message = model.user()
    assert message.startswith("Map this table.") and message.endswith("main PK listing.")
    sections = _sections(message)
    for line in sections["Body"][1:]:
        assert not re.search(r"\d", line.split(":", 1)[1]), line                         # every body cell redacted
    for line in sections["Columns"][1:]:
        assert not re.search(r"\d", line.partition("; texts:")[2]), line
    band = header_band(grid)
    without_context = "\n".join(line for name, lines in sections.items() if name != "Context" for line in lines)
    for (row, _c), cell in grid.cells.items():
        if row > band and has_number(cell.text) and re.search(r"[.,]\d|\d{3}", cell.text):
            assert cell.text not in without_context, cell.text


def test_incomplete_gives_no_spec():
    table, grid, shown = _setup()
    # accepted on the last turn the loop allows: the model never ended the conversation
    late = Scripted([[("propose_mapping", {"spec": _spec(table.spec)})]])
    mapped = map_table(late, table=shown, check=_check(grid), max_turns=1)
    assert (mapped.status, mapped.spec) == ("INCOMPLETE", None)
    wrong = _spec(table.spec.model_copy(update={"value_unit": "µg/mL"}))
    stubborn = Scripted([[("propose_mapping", {"spec": wrong})]] * 5)
    mapped = map_table(stubborn, table=shown, check=_check(grid))
    assert (mapped.status, mapped.spec, len(mapped.rejected)) == ("INCOMPLETE", None, 4)


def test_a_malformed_spec_is_rejected_and_the_model_hears_what_to_fix():
    table, grid, shown = _setup()
    broken = {**_spec(table.spec), "layout": "diagonal", "time_unit_cite": {"row": 1}}
    model = Scripted([[("propose_mapping", {"spec": broken})], [("propose_mapping", {"spec": "a table of times"})],
                      [("propose_mapping", {"spec": _spec(table.spec)})], []])
    mapped = map_table(model, table=shown, check=_check(grid))
    assert model.answers[0].startswith("REJECTED: ") and "INVALID_SPEC at layout" in model.answers[0]
    assert "INVALID_SPEC at time_unit_cite" in model.answers[0]
    assert "INVALID_SPEC at spec" in model.answers[1] and model.answers[2] == "ACCEPTED"
    assert mapped.spec == table.spec and len(mapped.rejected) == 2


def test_a_table_that_holds_no_data_is_answered_with_not_data_and_a_reason():
    template = synthetic.template_workbook()
    _table, grid, shown = _setup(template, "template-readme")
    model = Scripted([[("not_data", {"reason": " "})], [("not_data", {"reason": "the template's column guide"})], []])
    mapped = map_table(model, table=shown, check=_check(grid))
    assert model.answers[0].startswith("REJECTED: ") and "REASON_MISSING" in model.answers[0]
    assert model.answers[1] == "ACCEPTED"
    assert (mapped.spec.kind, mapped.spec.not_data_reason) == ("not_data", "the template's column guide")
    assert {u.use for u in execute(mapped.spec, grid).cell_use} == {"excluded"}


def test_a_warning_is_accepted_with_its_note_redacted():
    grid = RegionGrid.from_rows([["Time (h)", "Conc (ng/dL)"], [1, 12.5], [2, 8.4]])
    region = Region(id=grid.region_id, kind="table", where="s:'T'!A1:B3", table_kind="pk_summary")
    shown = redact(grid, region, file_name="x.xlsx", document_role="data_workbook")
    spec = {"schema": "mapping/2", "kind": "pk_summary", "layout": "wide_series", "header_rows": 1, "first_data_row": 2,
            "field": "concentration", "value_unit": "ng/dL", "value_unit_cite": {"row": 1, "column": 2},
            "columns": [{"column": 1, "role": "time"}, {"column": 2, "role": "value"}]}
    model = Scripted([[("propose_mapping", {"spec": spec})], []])
    mapped = map_table(model, table=shown, check=_check(grid))
    assert model.answers[0].startswith("ACCEPTED (a person will see these notes):") and "UNIT_NOT_IN_TABLES" in model.answers[0]
    assert mapped.spec is not None and mapped.spec.value_unit == "ng/dL"


def test_the_agents_take_no_grid_and_no_source_document():
    """Contracts §8.5: no function of the two agents takes a RegionGrid or a SourceDocument, and neither imports the
    storage or contracts packages."""
    for module in (table_mapper, prose_extractor):
        source = inspect.getsource(module)
        assert "modeler_storage" not in source and "modeler_contracts" not in source
        for name, function in inspect.getmembers(module, inspect.isfunction):
            if function.__module__ != module.__name__:
                continue
            annotations = " ".join(str(p.annotation) for p in inspect.signature(function).parameters.values())
            assert "RegionGrid" not in annotations and "SourceDocument" not in annotations, name


def test_a_run_cut_short_keeps_every_answer_through_the_step_log():
    """`run_tool_loop` never calls the model after its last turn, so the last turn's answers reach `Scripted.answers`
    only through `log_step=model.log_step`."""
    table, grid, shown = _setup()
    broken = {**_spec(table.spec), "layout": "diagonal"}
    turns = [[("propose_mapping", {"spec": broken})], [("propose_mapping", {"spec": _spec(table.spec)})]]
    logged = Scripted([list(t) for t in turns])
    mapped = map_table(logged, table=shown, check=_check(grid), max_turns=2, log_step=logged.log_step)
    assert mapped.status == "INCOMPLETE" and mapped.spec is None
    assert [a.split(":")[0].split(" ")[0] for a in logged.answers] == ["REJECTED", "ACCEPTED"]
    unlogged = Scripted([list(t) for t in turns])
    map_table(unlogged, table=shown, check=_check(grid), max_turns=2)
    assert len(unlogged.answers) == 1                                    # the last turn's answer is not seen
