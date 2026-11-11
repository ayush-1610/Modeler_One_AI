"""R6 (plan 2026-11-10): the delivery report says what the agents made of a client's files, and scores it against a
person's answer key. A scripted model stands in for the configured one (software test data)."""

from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from modeler_agents.delivery_pass import map_and_record
from modeler_agents.llm import ChatResult, ToolCall
from modeler_project import FileProjectStore, Workspace
from modeler_project.client_data import ingest
from modeler_project.dataset_register import propose_dataset
from modeler_project.datasets import ObservedDataset, Origin, Series, new_dataset_id
from modeler_project.delivery_eval import synthetic_pdf
from modeler_project.delivery_report import main, render, report, score
from modeler_project.documents import DocumentLibrary
from modeler_project.evidence import SourceRef

pytestmark = pytest.mark.req("T-47")

SYNOPSIS = [[("Study 093-26 synopsis: a single dose of the test product APL 50 (Desvenlafaxine ER 50 mg) was given "
              "after an overnight fast.")]]


class Scripted:
    provider, model = "test", "scripted"

    def __init__(self, turns):
        self.turns = list(turns)

    def complete(self, messages, tools):
        calls = self.turns.pop(0) if self.turns else []
        return ChatResult(content="mapped", finish_reason="", model="s", usage={"input_tokens": 1, "output_tokens": 1},
                          tool_calls=tuple(ToolCall(id=f"c{i}", name=n, arguments=a) for i, (n, a) in enumerate(calls)))


def _dissolution() -> bytes:
    wb = Workbook()
    for n, name in enumerate(("pH 1.2", "pH 6.8")):
        sheet = wb.active if n == 0 else wb.create_sheet(name)
        sheet.title = name
        sheet.append([f"Dissolution of APL 50, batch B123, {name}"])
        sheet.append(["Time (h)", "% dissolved"])
        sheet.append([1, 22.0])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _project(tmp_path):
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    library = DocumentLibrary(ws)
    pdf = ingest(ws, library, synthetic_pdf(SYNOPSIS), "093-26 synopsis.pdf", by="u")["id"]
    xlsx = ingest(ws, library, _dissolution(), "APL 50 dissolution.xlsx", by="u")["id"]
    map_and_record(Scripted([[
        ("propose_facts", {"sid": pdf, "facts": [
            {"fact": "study", "value": "093-26", "source": "name", "quote": "093-26"},
            {"fact": "food_state", "value": "fasted", "source": "page", "page": 1, "quote": "after an overnight fast"}]}),
        ("propose_facts", {"sid": xlsx, "sheet": "pH 1.2", "facts": [
            {"fact": "ph", "value": 1.2, "source": "sheet", "quote": "pH 1.2"}]})]]),
        ws, library, [pdf, xlsx], actor="agent:t")
    propose_dataset(ws, ObservedDataset(
        id=new_dataset_id(), kind="profile", study={"study_id": "093-26", "route": "oral", "food_state": "fasted",
                                                    "formulation": "ir_tablet", "dose_mg": 50, "n": 12, "n_timepoints": 3,
                                                    "statistic": "mean"},
        unit="ng/ml", series=(Series(name="mean", statistic="arithmetic_mean", times=(1, 2, 24), values=(40.0, 30.0, None)),),
        origin=Origin.CLIENT, extraction="CELL", provider="CLIENT",
        source=SourceRef(doc_sha256="c" * 64, page=1, title="093-26 PK Table.xlsx"), quote="row"), actor="u")
    return ws


KEY = {"files": [
    {"name": "093-26 synopsis.pdf", "study": "093-26", "food_state": "fed", "strength_mg": 50},   # fed: the key's mistake
    {"name": "APL 50 dissolution.xlsx", "sheets": {"pH 1.2": {"ph": 1.2}, "pH 6.8": {"ph": 6.8}}},
    {"name": "094-26 PK Table.xlsx", "study": "094-26"}],
    "studies": [{"id": "093-26"}, {"id": "094-26"}],
    "dissolution": [{"product": "APL 50", "ph": [1.2, 6.8]}]}


def test_the_report_says_per_file_what_was_found_and_the_score_names_each_difference(tmp_path):
    ws = _project(tmp_path)
    data = report(ws)
    assert data["counts"]["files"] == 2 and data["counts"]["mapped"] == 2
    synopsis = next(f for f in data["files"] if f["file"] == "093-26 synopsis.pdf")
    assert synopsis["map_line"] == "study 093-26 · fasted"
    assert [s["study"] for s in data["studies"]] == ["093-26"] and data["studies"][0]["points"] == 3

    scored = score(ws, data, KEY)
    verdicts = {(f["file"], f["sheet"], f["field"]): f["verdict"] for f in scored["fields"]}
    assert verdicts[("093-26 synopsis.pdf", None, "study")] == "found"
    assert verdicts[("093-26 synopsis.pdf", None, "food_state")] == "wrong"           # the map says fasted
    assert verdicts[("093-26 synopsis.pdf", None, "strength_mg")] == "missing"
    assert verdicts[("APL 50 dissolution.xlsx", "pH 1.2", "ph")] == "found"
    assert verdicts[("APL 50 dissolution.xlsx", "pH 6.8", "ph")] == "missing"
    assert scored["files_missing"] == ["094-26 PK Table.xlsx"]
    assert [(s["study"], s["found"]) for s in scored["studies"]] == [("093-26", True), ("094-26", False)]
    assert scored["summary"] == {"map_fields_found": "2/5", "map_fields_wrong": 1, "files_read": "0/3",
                                 "studies_found": "1/2", "dissolution_found": "0/2", "key_entries_not_used": 0}
    text = render(data, scored)
    assert "| 093-26 synopsis.pdf |  | food_state | fed | fasted (wrong) | after an overnight fast |" in text
    assert "- 094-26: **missing**" in text and "- 093-26: found as 093-26 (3 points)" in text


def test_the_command_reads_the_store_and_writes_the_report(tmp_path, capsys):
    import yaml

    _project(tmp_path)
    key = tmp_path / "key.yaml"
    key.write_text(yaml.safe_dump(KEY), encoding="utf-8")
    out = tmp_path / "report.md"
    assert main(["--root", str(tmp_path), "--project", "p1", "--key", str(key), "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("# Delivery report: project p1")
    assert main(["--root", str(tmp_path / "nowhere"), "--project", "p1"]) == 2
    assert main(["--root", str(tmp_path), "--project", "p9"]) == 2
    assert "not in this store" in capsys.readouterr().err


# ---- the R6 review: the report must not mislead -------------------------------------------------------------------

@pytest.mark.parametrize(("field", "key", "found", "same"), [
    ("product", "APL 50", "APL 500", False),             # never a part of a name
    ("batch", "B12", "B123", False),
    ("study", "26", "093-26", False),
    ("study", "093-26", "093-26-IV", False),
    ("study", "", "093-26", False),                      # an empty key entry matches nothing
    ("study", "Study 093/26", "093-26", False),
    ("study", "093/26", "093-26", True),                 # punctuation aside
    ("product", ["APL 50", "APL 50 mg tablet"], "APL 50 mg tablet", True),   # several spellings
    ("ph", 6.8, 6.8, True),
    ("food_state", "Fasted", "fasted", True),
])
def test_a_name_is_found_only_when_it_is_the_same_name(field, key, found, same):
    from modeler_project.delivery_report import _same

    assert _same(field, key, found) is same


def test_a_key_s_ph_may_be_one_number_or_none_and_unknown_entries_are_listed_not_dropped(tmp_path):
    ws = _project(tmp_path)
    data = report(ws)
    scored = score(ws, data, {
        "files": [{"name": "APL 50 dissolution.xlsx", "sheets": {"pH 1.2": {"pH": 1.2}, "pH 9": {"ph": 9}},
                   "strength": 50, "colour": "white"},
                  {"name": "093-26  Synopsis.PDF", "study": "093-26"}],     # spacing and case as a person types it
        "dissolution": [{"product": "APL 50", "ph": 6.8}, {"product": "APL 50"}, {"product": "APL 99", "ph": []}],
        "study": [{"id": "093-26"}]})
    verdicts = {(f["file"], f["sheet"], f["field"]): f["verdict"] for f in scored["fields"]}
    assert verdicts[("APL 50 dissolution.xlsx", "pH 1.2", "ph")] == "found"          # "pH" is the ph field
    assert verdicts[("APL 50 dissolution.xlsx", "pH 9", "ph")] == "no such sheet"
    assert verdicts[("APL 50 dissolution.xlsx", None, "strength_mg")] == "missing"
    assert verdicts[("093-26  Synopsis.PDF", None, "study")] == "found"
    assert [(d["product"], d["ph"]) for d in scored["dissolution"]] == [("APL 50", 6.8), ("APL 50", None), ("APL 99", None)]
    assert scored["unused"] == ["study: not a section of the key (files, studies, dissolution)",
                                ("APL 50 dissolution.xlsx: 'colour' is not a field (study, product, role, strength_mg, "
                                 "batch, food_state, medium, ph)")]
    assert "### Key entries not used (check their spelling)" in render(data, scored)


def test_a_malformed_key_is_refused_with_the_entry_named(tmp_path, capsys):
    import yaml

    _project(tmp_path)
    key = tmp_path / "key.yaml"
    key.write_text(yaml.safe_dump({"dissolution": [{"product": "APL 50", "ph": ["acid"]}]}), encoding="utf-8")
    assert main(["--root", str(tmp_path), "--project", "p1", "--key", str(key)]) == 2
    assert "dissolution[0] (APL 50): each pH is a number, not 'acid'" in capsys.readouterr().err


def test_a_sheet_read_and_waiting_for_a_person_counts_as_found_and_says_so(tmp_path):
    # the R6 review: a profile sheet always waits for a person's answers (n, purpose); the report saw only saved data
    from openpyxl import Workbook

    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    wb = Workbook()
    sheet = wb.active
    sheet.title = "Mean"
    sheet.append(["Study EX-101: mean plasma concentrations (ng/mL), 10 mg, fasted"])
    sheet.append(["Time (h)", "Mean"])
    for t, c in ((0.5, 12.0), (1, 30.0), (2, 25.0), (4, 14.0), (8, 6.0), (24, 1.0)):
        sheet.append([t, c])
    buf = io.BytesIO()
    wb.save(buf)
    ingest(ws, DocumentLibrary(ws), buf.getvalue(), "EX-101 PK Table.xlsx", by="u")
    data = report(ws)
    (f,) = data["files"]
    assert f["sheets_waiting"] and f["sheets_waiting"][0]["study_id"] == "EX-101"
    scored = score(ws, data, {"studies": [{"id": "EX-101"}]})
    assert scored["studies"][0]["found"] and scored["studies"][0]["waiting"]
    assert "found as EX-101 (6 points), read and waiting for a person's answers" in render(data, scored)


def test_a_study_only_linked_by_a_proposal_is_shown_not_counted_and_a_refused_link_not_at_all(tmp_path):
    from modeler_project.client_data import record_delivery_map, update_review

    ws = _project(tmp_path)
    sid = next(f["sid"] for f in report(ws)["files"] if f["file"] == "093-26 synopsis.pdf")
    record_delivery_map(ws, files={}, links=[{"kind": "study", "names": ["EX-9", "093-26"], "sid": sid, "page": 1,
                                              "locator": "p. 1", "quote": "Study EX-9 (093-26)"}],
                        looked_at=[sid], refused=[], summary="", run_id=None, by="agent:t")
    (study,) = score(ws, report(ws), {"studies": [{"id": "EX-9"}]})["studies"]
    assert not study["found"] and study["via_proposed_link"] == ["093-26"]
    update_review(ws, lambda c: ({**c, "selections": {"link|093-26": {"option": "different"}}}, "No"), by="u")
    (study,) = score(ws, report(ws), {"studies": [{"id": "EX-9"}]})["studies"]
    assert not study["found"] and study["via_proposed_link"] == []
    update_review(ws, lambda c: ({**c, "selections": {}, "aliases": {"093-26": "EX-9"}}, "the same study"), by="u")
    (study,) = score(ws, report(ws), {"studies": [{"id": "EX-9"}]})["studies"]
    assert study["found"] and study["as"] == ["093-26"]


def test_a_withdrawn_file_is_not_counted_as_failed_and_a_pipe_does_not_break_a_row(tmp_path):
    ws = _project(tmp_path)
    data = report(ws)
    from modeler_project.client_data import submissions

    sha = next(s for s in submissions(ws) if s["file"] == "093-26 synopsis.pdf")["sha256"]
    DocumentLibrary(ws).withdraw(sha, by="u", reason="wrong | study")
    data = report(ws)
    assert data["counts"]["withdrawn"] == 1 and data["counts"]["failed"] == 0
    from modeler_project.delivery_report import _cell

    assert _cell("a | b\nc") == "a / b c"
