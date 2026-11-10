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


# --- I4b: demographics, composition, one product or batch however the files write it ---------------------------------


def _delivered(tmp_path, name):
    """A delivery of the evaluation set read into a workspace, its documents read as a perfect reader would."""
    ws = _ws(tmp_path)

    def reader(ws, library, sid, file):
        read_and_record(Scripted([list(file.reading)]), ws, library, sid, actor="agent:eval")

    score(next(d for d in DELIVERIES if d.name == name), ws, read_documents=reader)
    return ws


def test_a_documents_demographics_become_the_studys_individual_once_a_person_chooses_its_population_and_sex(tmp_path):
    from modeler_project.inputs_view import _demographics_state

    ws = _delivered(tmp_path, "a Word synopsis giving the subjects' demographics")
    group = next(g for g in review.groups(ws) if g["id"] == "study:EX-302")
    shown = {f["field"]: f["value"] for f in group["facts"]}
    assert shown["demographics.age_mean"] == "31.5" and shown["demographics.weight_mean"] == "76.2"
    assert shown["demographics.ethnicity"] == "Caucasian" and shown["demographics.females"] == "0"
    population = next(i for i in group["issues"] if i["id"].endswith("demographics:population"))
    sex = next(i for i in group["issues"] if i["id"].endswith("demographics:sex"))
    assert "says “Caucasian”" in population["text"] and "European_ICRP_2002" in [o["id"] for o in population["options"]]
    assert "0 women" in sex["text"]
    assert not any(i["id"].endswith("demographics:age_years") for i in group["issues"])     # the synopsis states the age
    with pytest.raises(review.ReviewError, match="settle 2 open items"):
        review.confirm(ws, group["id"], by="u")
    review.select(ws, group["id"], population["id"], option="European_ICRP_2002", by="u")
    review.select(ws, group["id"], sex["id"], option="MALE", by="u")
    review.confirm(ws, group["id"], by="u")
    (found,) = [d for d in datasets(ws) if d.study.get("study_id") == "EX-302"]
    assert found.study["demographics"] == {"population": "European_ICRP_2002", "sex": "MALE", "age_years": 31.5,
                                           "age_min": 24, "age_max": 41, "weight_kg": 76.2}
    assert found.demographics_choice == "entered"
    assert _demographics_state({**found.study, "demographics_choice": found.demographics_choice}) == "entered"   # D-29


def test_a_batch_a_certificate_names_by_its_lot_number_is_one_batch_once_a_person_says_so(tmp_path):
    from modeler_project.dissolution_register import profiles

    ws = _delivered(tmp_path, "a certificate naming the batch by its lot number, with the composition")
    assert len(profiles(ws)) == 2                                             # B1 and 4711: two batches until linked
    group = next(g for g in review.groups(ws) if g["id"] == "product:Test 10 mg tablet")
    link = next(i for i in group["issues"] if i["id"] == "blink|TEST10MGTABLET|4711")     # linked within its product
    assert "certificate.pdf (p. 1)" in link["text"] and "batch 4711 (B1)" in link["text"]
    assert {f["label"]: f["value"] for f in group["facts"]}["Lactose monohydrate"] == "89 mg (filler)"
    group = review.select(ws, group["id"], link["id"], option="same", by="u")
    (merged,) = profiles(ws)                                                   # one batch: one profile, two files
    assert any("kept once" in n for n in group["notes"]) and merged["files"]
    group = review.reopen(ws, group["id"], link["id"], by="u")
    assert len(profiles(ws)) == 2                                             # said otherwise: two again


def test_a_batch_linked_in_one_product_is_not_linked_in_another(tmp_path):
    from modeler_project.delivery_eval import _diss, _template
    from modeler_project.dissolution_register import identity, profiles
    from pbpk_domain.dissolution import ProfileKey

    ws = _delivered(tmp_path, "a certificate naming the batch by its lot number, with the composition")
    group = next(g for g in review.groups(ws) if g["id"] == "product:Test 10 mg tablet")
    review.select(ws, group["id"], "blink|TEST10MGTABLET|4711", option="same", by="u")
    ingest(ws, DocumentLibrary(ws), _template(dissolution=_diss(60, product="Reference 10 mg tablet", batch="4711"))(),
           "reference.xlsx", by="u")
    aliases = {"batch": review.record(ws)["batch_aliases"]}
    key = {"role": "TEST", "strength_mg": 10, "apparatus": "", "rpm": 50, "medium": "phosphate", "ph": 6.8, "volume_ml": 900}
    assert identity(ProfileKey(product="Test 10 mg tablet", batch="4711", **key), aliases)[3] == "B1"
    assert identity(ProfileKey(product="Reference 10 mg tablet", batch="4711", **key), aliases)[3] == "4711"
    assert {p["key"]["product"] for p in profiles(ws)} == {"Test 10 mg tablet", "Reference 10 mg tablet"}


def test_one_product_written_two_ways_is_one_profile_and_its_composition_alone_is_confirmed(tmp_path):
    from modeler_project.dissolution_register import profiles

    ws = _delivered(tmp_path, "one product written two ways in two workbooks, the same profile")
    (profile,) = profiles(ws)
    assert profile["files"] == ["release_v2.xlsx"]                            # the later file's data, the first file's id
    library = DocumentLibrary(ws)
    pages = [["Composition of the Reference 20 mg capsule", "Drug X 20 mg (active)"]]
    sub = ingest(ws, library, synthetic_pdf(pages), "reference.pdf", by="u", tag=("formulation", ""))
    read_and_record(Scripted([[("propose_composition", {
        "product": "Reference 20 mg capsule", "product_quote": pages[0][0], "page": 1,
        "components": [{"name": "Drug X", "amount": 20, "unit": "mg", "quote": "Drug X 20 mg (active)"}]})]]),
        ws, library, sub["id"], actor="agent:test")
    group = next(g for g in review.groups(ws) if g["id"] == "product:Reference 20 mg capsule")
    assert group["items"] == [] and group["facts"][0]["value"] == "20 mg" and group["state"] == "to_confirm"
    assert review.confirm(ws, group["id"], by="u")["state"] == "confirmed"


# ---- figures worth digitizing (plan 2026-11-10, R5; the owner's decision 3) ------------------------------------------

FIGURE_PAGES = [["Clinical Study Report: Study EX-501",
                 "Twelve healthy subjects (n = 12) received a single oral dose of 20 mg as one tablet after an overnight fast."],
                ["Figure 2. Mean plasma concentrations of drug X (ng/mL) after a 20 mg dose, Study EX-501",
                 "Figure 3. Body weight by visit",
                 "Figure 4. Dissolution profile of APL 20 in pH 6.8 phosphate buffer"]]


def test_only_an_important_figure_with_its_caption_quoted_is_suggested_and_none_is_filed(tmp_path):
    from modeler_project.evidence_register import access_requests

    ws = _ws(tmp_path)
    sub, ctx, _model = _read(ws, [[
        ("suggest_digitization", {"kind": "concentration_time", "page": 2, "study_id": "EX-501",
                                  "quote": "Figure 2. Mean plasma concentrations of drug X (ng/mL)"}),
        ("suggest_digitization", {"kind": "dissolution", "page": 2, "product": "APL 20",
                                  "quote": "Figure 4. Dissolution profile of APL 20 in pH 6.8"}),
        ("suggest_digitization", {"kind": "body_weight", "page": 2, "quote": "Figure 3. Body weight by visit"}),
        ("suggest_digitization", {"kind": "concentration_time", "page": 2, "study_id": "EX-999",
                                  "quote": "Figure 2. Mean plasma concentrations of drug X (ng/mL)"}),
        ("suggest_digitization", {"kind": "concentration_time", "page": 1, "study_id": "EX-501",
                                  "quote": "Twelve healthy subjects (n = 12) received"}),
        ("suggest_digitization", {"kind": "dissolution", "page": 2, "product": "APL 99",
                                  "quote": "Figure 4. Dissolution profile of APL 20 in pH 6.8"})]], pages=FIGURE_PAGES)
    assert [f["kind"] for f in ctx.figures] == ["concentration_time", "dissolution"]
    refused = "\n".join(ctx.refused)
    assert "only a study's concentration-time profile or a dissolution profile is suggested" in refused
    assert "name the study as this file writes it" in refused and "name the product as this file writes it" in refused
    assert "the quote must be the figure's caption or title" in refused
    assert submission(ws, sub["id"])["figure_suggestions"] == ctx.figures
    assert access_requests(ws) == []                                   # suggested, not filed for a person


def test_a_suggestion_is_open_only_while_no_table_holds_its_values(tmp_path):
    from modeler_project.figure_suggestions import open_suggestions

    ws = _ws(tmp_path)
    _sub, _ctx, _model = _read(ws, [[("suggest_digitization", {
        "kind": "concentration_time", "page": 2, "study_id": "EX-501",
        "quote": "Figure 2. Mean plasma concentrations of drug X (ng/mL)"})]], pages=FIGURE_PAGES)
    (only,) = open_suggestions(ws)
    assert (only["file"], only["page"], only["study_id"], only["digitizable"]) == ("csr.pdf", 2, "EX-501", True)
    # a table of the same study read later (here, this file read again with its table): the suggestion closes
    _read(ws, [[FACTS], [PROFILE], [("suggest_digitization", {
        "kind": "concentration_time", "page": 2, "study_id": "EX-501",
        "quote": "Figure 2. Mean plasma concentrations of drug X (ng/mL)"})]], name="csr.pdf",
        pages=[CSR[0], CSR[1] + FIGURE_PAGES[1]])
    assert open_suggestions(ws) == []


def test_a_suggestion_closes_when_a_table_arrives_under_a_linked_name_and_a_withdrawn_files_are_hidden(tmp_path):
    from modeler_project.client_data import record_delivery_map
    from modeler_project.figure_suggestions import open_suggestions

    ws = _ws(tmp_path)
    sub, _ctx, _model = _read(ws, [[("suggest_digitization", {
        "kind": "concentration_time", "page": 2, "study_id": "EX-501",
        "quote": "Figure 2. Mean plasma concentrations of drug X (ng/mL)"})]], pages=FIGURE_PAGES)
    propose_dataset(ws, ObservedDataset(       # the client's sheet names the study "093-26"
        id=new_dataset_id(), kind="profile", study={"study_id": "093-26", "route": "oral", "food_state": "fasted",
                                                    "formulation": "ir_tablet", "dose_mg": 20, "n": 12, "n_timepoints": 3,
                                                    "statistic": "mean"},
        unit="ng/ml", series=(Series(name="mean", statistic="arithmetic_mean", times=(1, 2, 24), values=(40.0, 30.0, None)),),
        origin=Origin.CLIENT, extraction="CELL", provider="CLIENT",
        source=SourceRef(doc_sha256="c" * 64, page=1, title="pk.xlsx"), quote="row"), actor="u")
    assert len(open_suggestions(ws)) == 1                                      # 093-26 is not known to be EX-501 yet
    record_delivery_map(ws, files={}, links=[{"kind": "study", "names": ["EX-501", "093-26"], "sid": sub["id"], "page": 1,
                                              "locator": "p. 1", "quote": "Study EX-501 (093-26)"}],
                        looked_at=[sub["id"]], refused=[], summary="", run_id=None, by="agent:t")
    assert open_suggestions(ws) == []                                          # the files say they are one study

    other, _c, _m = _read(ws, [[("suggest_digitization", {
        "kind": "dissolution", "page": 1, "product": "APL 20",
        "quote": "Figure 4. Dissolution profile of APL 20 in pH 6.8"})]], name="diss.pdf", pages=FIGURE_PAGES[1:])
    assert [f["product"] for f in open_suggestions(ws)] == ["APL 20"]
    DocumentLibrary(ws).withdraw(other["sha256"], by="u", reason="superseded")
    assert open_suggestions(ws) == []
