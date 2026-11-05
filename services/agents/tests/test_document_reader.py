"""I4: the reading agent reads a client's PDF or Word file; code checks every proposal against its page, and what it
accepts waits on Inputs until a person confirms it. A scripted model stands in for the configured one (software test
data, not a model's judgement)."""

from __future__ import annotations

import pytest

from modeler_agents.document_reader import read_and_record
from modeler_agents.llm import ChatResult, ToolCall
from modeler_project import FileProjectStore, Workspace
from modeler_project import client_review as review
from modeler_project.client_data import ingest, submission
from modeler_project.dataset_register import dataset, datasets, propose_dataset
from modeler_project.datasets import ObservedDataset, Origin, Series, new_dataset_id
from modeler_project.delivery_eval import DELIVERIES, score, synthetic_pdf
from modeler_project.documents import DocumentLibrary
from modeler_project.evidence import EvidenceState, SourceRef

pytestmark = pytest.mark.req("T-47", "T-21")


class Scripted:
    """Answers each turn with the next list of tool calls; an empty list ends the run. It keeps what code answered."""

    provider, model = "test", "scripted"

    def __init__(self, turns):
        self.turns = list(turns)
        self.answers: list[str] = []

    def complete(self, messages, tools):
        self.answers += [m["content"] for m in messages if m["role"] == "tool"][len(self.answers):]
        calls = self.turns.pop(0) if self.turns else []
        return ChatResult(content="read", finish_reason="", model="s", usage={"input_tokens": 1, "output_tokens": 1},
                          tool_calls=tuple(ToolCall(id=f"c{i}", name=n, arguments=a) for i, (n, a) in enumerate(calls)))


def _ws(tmp_path) -> Workspace:
    return Workspace(FileProjectStore(tmp_path), "t1", "p1")


CSR = [["Clinical Study Report: Study EX-501",
        "Twelve healthy subjects (n = 12) received a single oral dose of 20 mg as one tablet after an overnight fast.",
        "The LLOQ was 0.5 ng/mL."],
       ["Table 4: Mean (SD) plasma concentrations (ng/mL) of drug X by time (h)",
        "0.5 18.0 (4.1) 12", "1.0 42.0 (9.0) 12", "4.0 13.0 (3.0) 12", "24.0 BLQ (-) 12"]]
FACTS = ("propose_study_facts", {"study_id": "EX-501", "facts": [
    {"fact": "dose", "value": 20, "unit": "mg", "page": 1, "quote": "a single oral dose of 20 mg"},
    {"fact": "n", "value": 12, "page": 1, "quote": "Twelve healthy subjects (n = 12)"},
    {"fact": "route", "value": "oral", "page": 1, "quote": "a single oral dose of 20 mg"},
    {"fact": "formulation", "value": "ir_tablet", "page": 1, "quote": "as one tablet after an overnight fast"},
    {"fact": "food_state", "value": "fasted", "page": 1, "quote": "as one tablet after an overnight fast"},
    {"fact": "lloq", "value": 0.5, "unit": "ng/mL", "page": 1, "quote": "The LLOQ was 0.5 ng/mL."}]})
PROFILE = ("propose_profile", {
    "study_id": "EX-501", "time_unit": "h", "unit": "ng/mL", "page": 2, "statistic": "arithmetic_mean", "n": 12,
    "error_kind": "SD", "header_quote": "Table 4: Mean (SD) plasma concentrations (ng/mL) of drug X by time (h)",
    "rows": [{"time": 0.5, "value": 18.0, "error": 4.1, "quote": "0.5 18.0 (4.1) 12"},
             {"time": 1.0, "value": 42.0, "error": 9.0, "quote": "1.0 42.0 (9.0) 12"},
             {"time": 4.0, "value": 13.0, "error": 3.0, "quote": "4.0 13.0 (3.0) 12"},
             {"time": 24, "value": None, "quote": "24.0 BLQ (-) 12"}]})


def _read(ws, turns, *, name="csr.pdf", pages=CSR, tag=("clinical", "")):
    library = DocumentLibrary(ws)
    sub = ingest(ws, library, synthetic_pdf(pages), name, by="u", tag=tag)
    model = Scripted(turns)
    ctx, _outcome = read_and_record(model, ws, library, sub["id"], actor="agent:test")
    return sub, ctx, model


@pytest.mark.parametrize("delivery", [d for d in DELIVERIES if d.needs_reader], ids=lambda d: d.name)
def test_each_document_delivery_read_as_a_perfect_reader_would_is_found_whole(tmp_path, delivery):
    """The evaluation set's answer is reachable: the reading a perfect reader makes passes code's checks, and the
    client's data then form the groups and flags the answer holds. The server's model is scored the same way."""
    answers: list[str] = []

    def reader(ws, library, sid, file):
        model = Scripted([list(file.reading)])
        read_and_record(model, ws, library, sid, actor="agent:eval")
        answers.extend(model.answers)

    result = score(delivery, _ws(tmp_path), read_documents=reader)
    assert all(a.startswith("ACCEPTED") for a in answers), answers
    assert result.perfect, (result.missed, result.unexpected)


def test_a_csr_table_becomes_a_dataset_to_confirm_with_its_facts_and_quotes(tmp_path):
    ws = _ws(tmp_path)
    sub, ctx, model = _read(ws, [[PROFILE], [FACTS], [PROFILE]])
    assert model.answers[0].startswith("REFUSED") and "dose_mg, n, route first" in model.answers[0]   # facts before data
    assert all(a.startswith("ACCEPTED") for a in model.answers[1:]), model.answers
    (found,) = [d for d in datasets(ws) if d.state is EvidenceState.PROPOSED]
    assert found.origin is Origin.CLIENT and found.extraction == "TABLE" and found.awaits_client_confirmation()
    assert (found.source.page, found.source.title) == (2, "csr.pdf") and found.quote == "0.5 18.0 (4.1) 12"
    assert found.study["dose_mg"] == 20 and found.study["lloq"] == 0.5 and found.study["food_state"] == "fasted"
    assert found.series[0].values[-1] is None                                  # BLQ, with the LLOQ the CSR states
    record = submission(ws, sub["id"])
    assert record["inventory"][0]["page"] == 1 and len(record["study_facts"]) == 6
    assert record["document_reads"][-1]["refused"] == [ctx.refused[0]]          # what code refused is kept
    (group,) = review.groups(ws)
    assert group["id"] == "study:EX-501" and group["state"] == "to_confirm" and not group["issues"]
    dose = next(f for f in group["facts"] if f["field"] == "dose_mg")
    assert dose["source"]["page"] == 1 and "20 mg" in dose["source"]["quote"]
    review.confirm(ws, group["id"], by="u")
    assert dataset(ws, found.id).state is EvidenceState.ACCEPTED


@pytest.mark.parametrize(("call", "reason"), [
    (("propose_study_facts", {"study_id": "EX-999", "facts": [FACTS[1]["facts"][0]]}), "never writes this name"),
    (("propose_study_facts", {"study_id": "EX-501", "facts": [
        {"fact": "dose", "value": 20, "unit": "mg", "page": 2, "quote": "a single oral dose of 20 mg"}]}),
     "not on that page verbatim"),
    (("propose_study_facts", {"study_id": "EX-501", "facts": [
        {"fact": "dose", "value": 25, "unit": "mg", "page": 1, "quote": "a single oral dose of 20 mg"}]}),
     "must state the dose 25 mg"),
    (("propose_study_facts", {"study_id": "EX-501", "facts": [
        {"fact": "food_state", "value": "fed", "page": 1, "quote": "as one tablet after an overnight fast"}]}),
     "does not say food_state is fed"),
    (("propose_profile", {**PROFILE[1], "header_quote": "Table 4: Mean (SD) plasma concentrations"}), "header_quote"),
    (("propose_profile", {**PROFILE[1], "rows": [{"time": 0.5, "value": 19.0, "quote": "0.5 18.0 (4.1) 12"}]}),
     "must contain the time 0.5 and the value"),
    (("propose_link", {"names": ["EX-501", "Study 9"], "page": 1, "quote": "Clinical Study Report: Study EX-501"}),
     "must write both names"),
])
def test_what_a_page_does_not_state_is_refused_with_the_reason(tmp_path, call, reason):
    ws = _ws(tmp_path)
    turns = [[FACTS], [call]] if call[0] == "propose_profile" else [[call]]
    sub, _ctx, model = _read(ws, turns)
    assert model.answers[-1].startswith("REFUSED") and reason in model.answers[-1], model.answers[-1]
    assert reason in submission(ws, sub["id"])["document_reads"][-1]["refused"][-1]


def test_a_documents_fact_fills_a_sheet_dataset_that_lacks_it_once_the_study_is_confirmed(tmp_path):
    """A PK sheet with values below the LLOQ and no LLOQ asks for it, unless a client document states it: then the
    card shows the document's LLOQ with its page and quote, and confirming sets it on the sheet's dataset."""
    ws = _ws(tmp_path)
    sheet = propose_dataset(ws, ObservedDataset(
        id=new_dataset_id(), kind="profile", study={"study_id": "EX-501", "route": "oral", "food_state": "fasted",
                                                    "formulation": "ir_tablet", "dose_mg": 20, "n": 12, "n_timepoints": 3,
                                                    "statistic": "mean"},
        unit="ng/ml", series=(Series(name="mean", statistic="arithmetic_mean", times=(1, 2, 24), values=(40.0, 30.0, None)),),
        origin=Origin.CLIENT, extraction="CELL", provider="CLIENT",
        source=SourceRef(doc_sha256="c" * 64, page=1, title="pk.xlsx"), quote="row"), actor="u")
    before = next(g for g in review.groups(ws) if g["id"] == "study:EX-501")
    assert any(i["id"].endswith(f"lloq:{sheet.id}") for i in before["issues"])
    _read(ws, [[("propose_study_facts", {"study_id": "EX-501", "facts": [FACTS[1]["facts"][5]]})]])
    group = next(g for g in review.groups(ws) if g["id"] == "study:EX-501")
    assert not group["issues"]
    lloq = next(f for f in group["facts"] if f["field"] == "lloq")
    assert lloq["fills"] == [sheet.id] and lloq["source"]["title"] == "csr.pdf" and lloq["source"]["page"] == 1
    review.confirm(ws, group["id"], by="u")
    assert dataset(ws, sheet.id).study["lloq"] == 0.5


def test_a_later_reading_of_the_file_replaces_the_earlier(tmp_path):
    ws = _ws(tmp_path)
    sub, _ctx, _m = _read(ws, [[FACTS, PROFILE]])
    (first,) = submission(ws, sub["id"])["document_reads"][0]["datasets"]
    library = DocumentLibrary(ws)
    read_and_record(Scripted([[FACTS, PROFILE]]), ws, library, sub["id"], actor="agent:again")
    record = submission(ws, sub["id"])
    assert len(record["document_reads"]) == 2 and len(record["study_facts"]) == 6       # replaced, not added
    assert dataset(ws, first).state is EvidenceState.REJECTED and "later reading" in dataset(ws, first).decision_reason
    assert [d.id for d in datasets(ws) if d.state is EvidenceState.PROPOSED] == record["document_reads"][1]["datasets"]


def test_a_study_only_a_document_describes_is_confirmed_as_its_facts_stand(tmp_path):
    """A study with no data from the client yet is a group of the facts a document gives; confirming it records them,
    and a later reading that changes them returns it to "to confirm"."""
    ws = _ws(tmp_path)
    sub, _ctx, _m = _read(ws, [[("propose_study_facts", {"study_id": "EX-501", "facts": FACTS[1]["facts"][:2]})]])
    (group,) = review.groups(ws)
    assert group["items"] == [] and group["state"] == "to_confirm" and "No concentration data" in group["notes"][-1]
    assert review.confirm(ws, group["id"], by="u")["state"] == "confirmed"
    read_and_record(Scripted([[("propose_study_facts", {"study_id": "EX-501", "facts": FACTS[1]["facts"][:1]})]]), ws,
                    DocumentLibrary(ws), sub["id"], actor="agent:again")
    assert review.groups(ws)[0]["state"] == "to_confirm"
