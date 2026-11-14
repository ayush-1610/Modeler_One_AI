"""D3: the prose extractor (contracts §6.2, §8.5; plan §7.5). A scripted model states facts of a report's paragraphs;
code checks each one under the strict prose check and keeps only its own reading (numbers, units, names, spans); a
table's text is never shown. Software test data (the made-up Exampleamide), not a model's judgement."""

from __future__ import annotations

import io

import pytest

from modeler_agents.evals.scripted import Scripted
from modeler_agents.prose_extractor import PROMPT_SHA256, extract_prose
from modeler_intake import synthetic
from modeler_intake.mapping.prose_check import ProseFactError, check_prose_fact
from modeler_intake.mapping_spec import ProseFact, ProseParagraph

pytestmark = pytest.mark.req("T-47", "T-21")

WORD = synthetic.word_report()
FIELDS = ("study_id", "n", "dose", "route", "food_state", "crossover")


def _paragraphs() -> list[ProseParagraph]:
    """The Word report's design paragraphs, as the parser hands them (contracts §6.1: `paragraphs`)."""
    import docx

    paragraphs = docx.Document(io.BytesIO(WORD.data)).paragraphs
    return [ProseParagraph(index=i, text=paragraphs[i - 1].text, locator=f"d:p:{i}-{i}", heading=paragraphs[0].text,
                           heading_locator="d:p:1-1") for i in (2, 3)]


def _check(paragraphs: list[ProseParagraph]):
    by_index = {p.index: p for p in paragraphs}

    def check(field, value, quote, paragraph, study, arm) -> ProseFact:
        return check_prose_fact(field, value, quote, by_index[paragraph], study=study, arm=arm)

    return check


def _fact(field, value, quote, paragraph, **labels) -> tuple[str, dict]:
    return "state_fact", {"field": field, "value": value, "quote": quote, "paragraph": paragraph, **labels}


def test_only_facts_the_check_accepts_are_returned_with_codes_numbers():
    paragraphs = _paragraphs()
    model = Scripted([[
        _fact("n", "18", "It enrolled 18 healthy volunteers.", 2, study="230-27"),
        _fact("dose", 0.02, "a single oral dose of 20 mg Exampleamide", 3),            # converted to g: not written
        _fact("dose", "20", "a single oral dose of 20 mg Exampleamide", 3),
        _fact("food_state", "fasted", "under fasted conditions", 3),
        _fact("crossover", "yes", "a randomised, two-way crossover study", 2),
    ], []])
    reading = extract_prose(model, paragraphs=paragraphs, fields=FIELDS, check=_check(paragraphs))
    assert [a.split(":")[0] for a in model.answers] == ["ACCEPTED", "REFUSED", "ACCEPTED", "ACCEPTED", "ACCEPTED"]
    assert model.answers[0] == "ACCEPTED: n = 18, study '230-27'" and model.answers[2] == "ACCEPTED: dose = 20 mg"
    got = [(f.field, f.value, f.unit, f.locator, f.study_locator) for f in reading.facts]
    assert got == [("n", 18.0, None, "d:p:2/ch:68-70", "d:p:2/ch:6-12"), ("dose", 20.0, "mg", "d:p:3/ch:44-46", None),
                   ("food_state", "fasted", None, "d:p:3/ch:69-75", None), ("crossover", "yes", None, "d:p:2/ch:39-48", None)]
    # the truth's spans, read by code
    truth = {v.field: v.locator for v in WORD.values if v.table == ""}
    assert {f.field: f.locator for f in reading.facts if f.field in truth} == truth
    assert (reading.status, reading.prompt_sha256, reading.usage) == ("COMPLETED", PROMPT_SHA256,
                                                                       {"input_tokens": 2, "output_tokens": 2})


def test_a_refused_facts_reason_is_in_the_answers():
    paragraphs = _paragraphs()
    model = Scripted([[
        _fact("n", 19, "It enrolled 18 healthy volunteers.", 2),
        _fact("n", 18, "Study 230-27 was a randomised, two-way crossover study. It enrolled 18", 2),
        _fact("route", "oral", "a single oral dose of 20 mg", 9),
        _fact("species", "human", "It enrolled 18 healthy volunteers.", 2),
        _fact("n", 18, "It enrolled 18 healthy volunteers.", 2, study="230-24"),
    ], []])
    reading = extract_prose(model, paragraphs=paragraphs, fields=FIELDS, check=_check(paragraphs))
    assert reading.facts == () and reading.rejected == tuple(model.answers)
    assert model.answers[0] == ("REFUSED: no clause of the quote states n 19 as a number; code reads 18 (the value is "
                                "the number as written: no unit conversion, no times 100)")
    assert "does not name n" in model.answers[1]
    assert model.answers[2] == "REFUSED: paragraph 9 is not one of the paragraphs shown (2, 3)"
    assert model.answers[3].startswith("REFUSED: 'species' is not one of the fields asked")
    assert "study label '230-24' is not written in paragraph 2" in model.answers[4]


def test_the_study_and_arm_reach_the_check():
    paragraphs = _paragraphs()
    seen: list[tuple] = []
    real = _check(paragraphs)

    def recording(field, value, quote, paragraph, study, arm) -> ProseFact:
        seen.append((field, paragraph, study, arm))
        return real(field, value, quote, paragraph, study, arm)

    model = Scripted([[
        _fact("study_id", "230-27", "Study 230-27 was a randomised", 2, study="230-27", arm="two-way"),
        _fact("dose", 20, "a single oral dose of 20 mg Exampleamide", 3, study=""),
    ], []])
    reading = extract_prose(model, paragraphs=paragraphs, fields=FIELDS, check=recording)
    assert seen == [("study_id", 2, "230-27", "two-way"), ("dose", 3, None, None)]
    first = reading.facts[0]
    assert (first.study_label, first.study_locator, first.arm_label, first.arm_locator) == (
        "230-27", "d:p:2/ch:6-12", "two-way", "d:p:2/ch:31-38")


def test_a_tables_text_is_never_in_the_input():
    paragraphs = _paragraphs()
    table_rows = [" ".join(row) for row in WORD.tables[0].rows]
    as_table = ProseParagraph(index=4, text="\n".join(table_rows), locator="d:t:1")      # a table handed in by mistake
    model = Scripted([[_fact("dose", 20, "Exampleamide plasma concentration", 4)], []])
    reading = extract_prose(model, paragraphs=[*paragraphs, as_table], fields=FIELDS, check=_check(paragraphs))
    message = model.user()
    assert "Paragraph 2" in message and "Paragraph 3" in message and "Paragraph 4" not in message
    shown = [text for row in WORD.tables[0].rows for text in row if "." in text or "(" in text]     # 8.1, 14.6, Mean (...)
    assert len(shown) > 12 and not any(text in message for text in shown)
    assert model.answers == ["REFUSED: paragraph 4 is not one of the paragraphs shown (2, 3)"] and reading.facts == ()


def test_the_message_names_the_fields_and_a_fact_stated_twice_is_kept_once():
    paragraphs = _paragraphs()
    twice = _fact("dose", 20, "a single oral dose of 20 mg Exampleamide", 3)
    model = Scripted([[twice], [twice], []])
    reading = extract_prose(model, paragraphs=paragraphs, fields=("dose", "food_state"), check=_check(paragraphs))
    assert model.answers == ["ACCEPTED: dose = 20 mg", "ACCEPTED (already stated): dose = 20 mg"]
    assert len(reading.facts) == 1
    message = model.user()
    assert "- dose: a number, with its mass unit" in message and "- food_state: one of fasted, fed" in message
    assert 'Paragraph 3 (under the heading "Study design"):' in message
    with pytest.raises(ValueError, match="not a field"):
        extract_prose(Scripted([]), paragraphs=paragraphs, fields=("dosage",), check=_check(paragraphs))


def test_a_conversation_cut_short_keeps_the_facts_code_accepted():
    paragraphs = _paragraphs()
    model = Scripted([[_fact("n", 18, "It enrolled 18 healthy volunteers.", 2)],
                      [_fact("dose", 20, "a single oral dose of 20 mg Exampleamide", 3)]])
    reading = extract_prose(model, paragraphs=paragraphs, fields=FIELDS, check=_check(paragraphs), max_turns=2)
    assert reading.status == "INCOMPLETE" and [f.field for f in reading.facts] == ["n", "dose"]


def test_a_check_that_refuses_with_its_own_reason():
    def refuse(field, value, quote, paragraph, study, arm) -> ProseFact:
        raise ProseFactError("the paragraph is a table's caption")

    model = Scripted([[_fact("dose", 20, "a single oral dose of 20 mg Exampleamide", 3)], []])
    reading = extract_prose(model, paragraphs=_paragraphs(), fields=FIELDS, check=refuse)
    assert reading.rejected == ("REFUSED: the paragraph is a table's caption",) and reading.facts == ()


def test_no_paragraph_makes_no_model_call():
    model = Scripted([])
    reading = extract_prose(model, paragraphs=[], fields=FIELDS, check=_check([]))
    assert (reading.facts, reading.status, model.received) == ((), "COMPLETED", [])
