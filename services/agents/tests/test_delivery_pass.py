"""R4 (plan 2026-11-10): the delivery pass maps a client's files together before each is read; code checks every quote
(a page, a cell or the file's name) and that it states the value; the map is context for each file's reading, and its
links become the questions a person answers on Inputs. A scripted model stands in for the configured one (software
test data, not a model's judgement)."""

from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from modeler_agents.delivery_pass import check_value, map_and_record
from modeler_agents.llm import ChatResult, ToolCall
from modeler_project import FileProjectStore, Workspace
from modeler_project.client_data import delivery_map, document_links, ingest, submissions
from modeler_project.delivery_eval import synthetic_pdf
from modeler_project.delivery_map import file_line, note_for
from modeler_project.documents import DocumentLibrary

pytestmark = pytest.mark.req("T-47")


class Scripted:
    """Answers each turn with the next list of tool calls; an empty list ends the run. It keeps the user message and
    what code answered."""

    provider, model = "test", "scripted"

    def __init__(self, turns):
        self.turns = list(turns)
        self.answers: list[str] = []
        self.user = ""

    def complete(self, messages, tools):
        self.user = self.user or next(m["content"] for m in messages if m["role"] == "user")
        self.answers += [m["content"] for m in messages if m["role"] == "tool"][len(self.answers):]
        calls = self.turns.pop(0) if self.turns else []
        return ChatResult(content="mapped", finish_reason="", model="s", usage={"input_tokens": 1, "output_tokens": 1},
                          tool_calls=tuple(ToolCall(id=f"c{i}", name=n, arguments=a) for i, (n, a) in enumerate(calls)))


def _dissolution() -> bytes:
    wb = Workbook()
    one = wb.active
    one.title = "pH 1.2"
    one.append(["Dissolution of Desvenlafaxine ER 50 mg (APL 50), batch B123, 0.1 N HCl pH 1.2, USP II 50 rpm"])
    one.append(["Time (h)", "% dissolved"])
    one.append([1, 22.0])
    six = wb.create_sheet("pH 6.8")
    six.append(["Dissolution of Desvenlafaxine ER 50 mg (APL 50), batch B123, phosphate buffer pH 6.8"])
    six.append(["Time (h)", "% dissolved"])
    six.append([1, 18.0])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


SYNOPSIS = [[("Study 093-26 synopsis: a single dose of the test product APL 50 (Desvenlafaxine ER 50 mg) "
              "was given after an overnight fast."),
             "The test product APL 50, batch B123, was compared with the reference listed drug Pristiq 50 mg."]]


def _delivery(tmp_path):
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    library = DocumentLibrary(ws)
    pdf = ingest(ws, library, synthetic_pdf(SYNOPSIS), "093-26 synopsis.pdf", by="u")
    sheet = ingest(ws, library, _dissolution(), "APL 50 dissolution.xlsx", by="u")
    return ws, library, pdf["id"], sheet["id"]


def test_the_pass_maps_each_file_and_sheet_and_code_refuses_what_its_quote_does_not_state(tmp_path):
    ws, library, pdf, xlsx = _delivery(tmp_path)
    model = Scripted([[
        ("propose_facts", {"sid": pdf, "facts": [
            {"fact": "study", "value": "093-26", "source": "name", "quote": "093-26"},
            {"fact": "role", "value": "TEST", "source": "page", "page": 1, "quote": "the test product APL 50"},
            {"fact": "product", "value": "APL 50", "source": "page", "page": 1, "quote": "the test product APL 50"},
            {"fact": "strength_mg", "value": 50, "source": "page", "page": 1, "quote": "Desvenlafaxine ER 50 mg"},
            {"fact": "food_state", "value": "fasted", "source": "page", "page": 1, "quote": "after an overnight fast"},
            {"fact": "food_state", "value": "fed", "source": "page", "page": 1, "quote": "after an overnight fast"},
            {"fact": "strength_mg", "value": 100, "source": "page", "page": 1, "quote": "Desvenlafaxine ER 50 mg"},
            {"fact": "study", "value": "094-26", "source": "name", "quote": "094-26"}]}),
         ("propose_facts", {"sid": xlsx, "sheet": "pH 1.2", "facts": [
             {"fact": "ph", "value": 1.2, "source": "cell", "cell": "pH 1.2!A1", "quote": "0.1 N HCl pH 1.2"},
             {"fact": "medium", "value": "0.1 N HCl", "source": "cell", "cell": "pH 1.2!A1", "quote": "0.1 N HCl pH 1.2"},
             {"fact": "batch", "value": "B123", "source": "cell", "cell": "pH 1.2!A1", "quote": "batch B123"}]}),
         ("propose_facts", {"sid": xlsx, "sheet": "pH 6.8", "facts": [
             {"fact": "ph", "value": 6.8, "source": "cell", "cell": "pH 6.8!A1", "quote": "phosphate buffer pH 6.8"},
             {"fact": "ph", "value": 6.8, "source": "cell", "cell": "pH 6.8!A2", "quote": "phosphate buffer pH 6.8"}]}),
         ("propose_link", {"kind": "product", "names": ["APL 50", "test product"], "sid": pdf, "source": "page", "page": 1,
                           "quote": "The test product APL 50, batch B123"}),
         ("propose_link", {"kind": "product", "names": ["APL 50", "Pristiq"], "sid": pdf, "source": "page", "page": 1,
                           "quote": "the test product APL 50"})]])
    ctx, outcome = map_and_record(model, ws, library, [pdf, xlsx], actor="agent:t", drug="desvenlafaxine")
    assert outcome.status == "COMPLETED"
    # what the agent first saw: each file's name, the workbook's sheets, the synopsis's first page
    assert "093-26 synopsis.pdf" in model.user and "sheet pH 6.8" in model.user and "overnight fast" in model.user

    refused = "\n".join(ctx.refused)
    assert "food_state of 093-26 synopsis.pdf: the quote does not say it" in refused          # fed is not "overnight fast"
    assert "strength_mg of 093-26 synopsis.pdf: the quote does not state 100 with its mg" in refused
    assert "study of 093-26 synopsis.pdf: the quote is not words of the file's name" in refused
    assert "ph of APL 50 dissolution.xlsx sheet pH 6.8: the quote is not in cell pH 6.8!A2" in refused
    assert "link ['APL 50', 'Pristiq']: the quote must write both names" in refused

    mapped = delivery_map(ws)
    assert sorted(mapped["looked_at"]) == sorted([pdf, xlsx])
    facts = mapped["files"][pdf]["facts"]
    assert {k: v["value"] for k, v in facts.items()} == {"study": "093-26", "role": "TEST", "product": "APL 50",
                                                         "strength_mg": 50.0, "food_state": "fasted"}
    assert facts["study"]["where"] == "file name" and facts["role"]["where"] == "p. 1"
    sheets = mapped["files"][xlsx]["sheets"]
    assert {k: v["value"] for k, v in sheets["pH 1.2"]["facts"].items()} == {"ph": 1.2, "medium": "0.1 N HCl", "batch": "B123"}
    assert sheets["pH 6.8"]["facts"]["ph"]["where"] == "pH 6.8!A1"
    assert file_line(mapped["files"][pdf]) == "study 093-26 · product APL 50 · TEST · 50 mg · fasted"

    # the link reaches the person's questions as a document's link does: with its file, its page and its quote
    (link,) = document_links(ws, "product")
    assert link["names"] == ["APL 50", "test product"] and link["file"] == "093-26 synopsis.pdf" and link["page"] == 1
    assert mapped["runs"][-1]["links"] == 1 and len(mapped["runs"][-1]["refused"]) == 5
    assert all(s["file"] != "delivery" for s in submissions(ws))                      # the map is not a client file


def test_each_reading_is_told_what_the_map_says_and_a_single_file_is_checked_against_it(tmp_path):
    ws, library, pdf, xlsx = _delivery(tmp_path)
    map_and_record(Scripted([[
        ("propose_facts", {"sid": pdf, "facts": [
            {"fact": "study", "value": "093-26", "source": "name", "quote": "093-26"}]}),
        ("propose_facts", {"sid": xlsx, "sheet": "pH 6.8", "facts": [
            {"fact": "ph", "value": 6.8, "source": "cell", "cell": "pH 6.8!A1", "quote": "phosphate buffer pH 6.8"}]})]]),
        ws, library, [pdf, xlsx], actor="agent:t")
    note = note_for(delivery_map(ws), xlsx, sheet="pH 6.8")
    assert "every value you propose must still be quoted from this file" in note
    assert "- pH: pH 6.8 (“phosphate buffer pH 6.8”, pH 6.8!A1)" in note
    assert "- 093-26 synopsis.pdf: study 093-26" in note                       # the other files of the delivery
    assert note_for(delivery_map(ws), "file-unknown").startswith("The delivery map")

    later = ingest(ws, library, synthetic_pdf([["Study 093-26 PK table: plasma desvenlafaxine, fasting."]]),
                   "093-26 PK Table.pdf", by="u")
    single = Scripted([[]])
    map_and_record(single, ws, library, [later["id"]], actor="agent:t")
    assert "The map already says, of files delivered before" in single.user
    assert "- 093-26 synopsis.pdf: study 093-26" in single.user
    assert later["id"] in delivery_map(ws)["looked_at"]                        # looked at, though nothing was found


@pytest.mark.parametrize(("field", "value", "quote", "kept"), [
    ("strength_mg", "50", "ER 50 mg tablets", 50.0),
    ("strength_mg", 50, "ER 50 tablets", None),               # no mg
    ("strength_mg", 50, "USP II 50 rpm, 25 mg tablet", None),  # 50 is not the mg (the R4 review)
    ("strength_mg", 1, "Desvenlafaxine ER 100 mg", None),      # no x100 for mg
    ("strength_mg", 10, "a dose of 10 mg/kg", None),           # mg/kg is not a strength
    ("ph", 6.8, "buffer 6.8", None),                          # no pH
    ("ph", "4.5", "acetate buffer pH 4.5", 4.5),
    ("ph", 0.1, "0.1 N HCl pH 1.2", None),                    # 0.1 is the HCl's, not the pH
    ("ph", 37, "phosphate buffer pH 6.8 at 37 °C", None),      # outside 0-14
    ("role", "rld", "the reference listed drug", "RLD"),
    ("role", "RLD", "RLD 50 vs APL 50 MMD", "RLD"),
    ("role", "OTHER", "anything", None),
    ("food_state", "fed", "after a high-fat breakfast", "fed"),
    ("food_state", "fasted", "US Pivotal Fast_230-23", "fasted"),   # an underscore separates words (the R4 review)
    ("food_state", "fed", "US Pivotal Fed_231-23", "fed"),
    ("study", "093-26", "Study 093/26", "093-26"),            # the name as the file writes it, punctuation aside
    ("study", "93", "093-26 PK Table", None),                 # not a fragment of another number
    ("study", "230-23", "US Pivotal Fast_230-23", "230-23"),
    ("medium", "phosphate buffer", "50 mM phosphate buffer pH 6.8", "phosphate buffer"),
    ("analyte", "x", "x", None),
])
def test_code_keeps_a_value_only_when_its_quote_states_it(field, value, quote, kept):
    why, got = check_value(field, value, quote)
    assert (got if why is None else None) == kept


def _many_sheets() -> bytes:
    wb = Workbook()
    names = ["0.1N HCl", "pH 4.5", "pH 6.8", "Water", "Summary"]
    for n, name in enumerate(names):
        sheet = wb.active if n == 0 else wb.create_sheet(name)
        sheet.title = name
        sheet.append([f"Dissolution of APL 50, {name}, USP II 50 rpm, 900 mL"])
        sheet.append(["Time (min)", *[f"Vessel {v}" for v in range(1, 13)]])
        for t in (5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 360):
            sheet.append([t, *[float(v + t) for v in range(1, 13)]])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_every_sheet_is_shown_a_tab_name_is_quoted_and_one_file_holds_one_value_per_field(tmp_path):
    # the R4 review: a workbook's later sheets were cut from the overview; pH often stands only in the tab's name; a
    # comparison file holding two products must not keep the second silently over the first
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    library = DocumentLibrary(ws)
    sid = ingest(ws, library, _many_sheets(), "Dissolution Profiling_US Market.xlsx", by="u")["id"]
    model = Scripted([[
        ("propose_facts", {"sid": sid, "sheet": "pH 4.5", "facts": [
            {"fact": "ph", "value": 4.5, "source": "sheet", "quote": "pH 4.5"}]}),
        ("propose_facts", {"sid": sid, "facts": [
            {"fact": "ph", "value": 4.5, "source": "sheet", "quote": "pH 4.5"}]}),          # a file's fact: no sheet
        ("propose_facts", {"sid": sid, "facts": [
            {"fact": "product", "value": "APL 50", "source": "cell", "cell": "Water!A1", "quote": "APL 50"},
            {"fact": "product", "value": "USP II", "source": "cell", "cell": "Water!A1", "quote": "USP II 50 rpm"}]}),
        ("propose_link", {"kind": "product", "names": ["APL 50", "US Market"], "sid": sid, "source": "name",
                          "quote": "US Market"}),
        ("propose_link", {"kind": "product", "names": ["APL 50", "APL 50 tablet"], "sid": sid, "source": "cell",
                          "cell": "Water!A1", "quote": "APL 50"})]])
    ctx, _outcome = map_and_record(model, ws, library, [sid], actor="agent:t")
    assert all(f"sheet {name}:" in model.user for name in ("0.1N HCl", "pH 4.5", "pH 6.8", "Water", "Summary"))
    mapped = delivery_map(ws)["files"][sid]
    assert mapped["sheets"]["pH 4.5"]["facts"]["ph"] == {"value": 4.5, "quote": "pH 4.5", "where": "sheet name"}
    assert mapped["facts"] == {"product": {"value": "APL 50", "quote": "APL 50", "where": "Water!A1"}}
    refused = "\n".join(ctx.refused)
    assert "a sheet-name source is for a sheet's facts" in refused
    assert "already APL 50 here" in refused
    assert "a link is quoted from a page or a cell" in refused
    assert "one is part of the other" in refused


def test_a_link_question_says_where_its_quote_is_a_page_or_a_cell():
    # the R4 review: a link the map quoted from a cell was asked as "<file> (p. None) says …"
    from modeler_project.client_review import _where

    assert _where({"page": 3}) == "p. 3"
    assert _where({"page": None, "locator": "pH 6.8!A1"}) == "pH 6.8!A1"
    assert _where({"page": None}) == "the file"
