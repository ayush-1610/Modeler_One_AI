"""Client data confirmed inline (docs/plans/2026-11-03-inputs-and-client-data.md §3.3–3.5; the owner, 2026-11-03): what
the client's files gave waits, grouped, until a person confirms it; a conflict or a question blocks its group until a
selection is confirmed, with no reason asked; a settled conflict stays shown with its final value."""

from __future__ import annotations

import hashlib

import pytest

from modeler_project import client_review as review
from modeler_project.client_data import ingest
from modeler_project.client_review import _normal
from modeler_project.dataset_register import datasets, propose_dataset
from modeler_project.datasets import ObservedDataset, Origin, Series, new_dataset_id
from modeler_project.evidence import EvidenceItem, EvidenceState, SourceRef, SourceType, new_id
from modeler_project.evidence_register import items, propose
from modeler_project.inputs import usable_dataset
from modeler_project.sources import included

from .test_client_data import _project, _workbook

pytestmark = pytest.mark.req("T-47")


def _client_dataset(ws, study: dict, *, file: str = "pk.xlsx") -> ObservedDataset:
    d = ObservedDataset(id=new_dataset_id(), kind="profile", study={"n_timepoints": 3, "statistic": "mean", **study},
                        analyte="parent", matrix="plasma", time_unit="h", unit="ng/ml",
                        series=(Series(name="mean", statistic="arithmetic_mean", times=(1, 2, 6), values=(40.0, 30.0, 10.0)),),
                        origin=Origin.CLIENT, extraction="CELL", provider="CLIENT",
                        source=SourceRef(doc_sha256=hashlib.sha256(file.encode()).hexdigest(), page=1, locator="Conc!A1", title=file),
                        quote="[Conc row 2] A2=1")
    return propose_dataset(ws, d, actor="u")


def test_a_template_waits_until_its_groups_are_confirmed_and_then_loads(tmp_path):
    ws, library, brief, matrix, _ = _project(tmp_path)
    ingest(ws, library, _workbook(), "client.xlsx", by="u", matrix=matrix, brief=brief)
    groups = {g["id"]: g for g in review.groups(ws)}
    assert {"study:BE-01-TEST", "study:BE-01-RLD"} <= set(groups)
    assert any(g["kind"] == "compound" for g in groups.values()) and any(g["kind"] == "product" for g in groups.values())
    assert all(g["state"] == "to_confirm" for g in groups.values())
    assert not any(usable_dataset(d) for d in datasets(ws))            # nothing from the client loads yet
    assert not any(included(e) for e in items(ws) if e.provider == "CLIENT")

    test = review.confirm(ws, "study:BE-01-TEST", by="u")
    assert test["state"] == "confirmed" and test["confirmed_by"] == "u"
    loaded = {d.study["study_id"]: usable_dataset(d) for d in datasets(ws)}
    assert loaded == {"BE-01-TEST": True, "BE-01-RLD": False}           # per group: the other study still waits
    compound = next(g for g in review.groups(ws) if g["kind"] == "compound")
    review.confirm(ws, compound["id"], by="u")
    assert all(included(e) for e in items(ws) if e.provider == "CLIENT")
    assert review.record(ws)["confirmations"][compound["id"]]["by"] == "u"


def test_two_files_giving_one_study_two_doses_block_it_until_a_selection_is_confirmed(tmp_path):
    ws, *_ = _project(tmp_path)
    first = _client_dataset(ws, {"study_id": "EX-101", "route": "oral", "food_state": "fasted", "dose_mg": 10, "n": 14})
    second = _client_dataset(ws, {"study_id": "EX-101", "route": "oral", "food_state": "fasted", "dose_mg": 5, "n": 12}, file="b.xlsx")
    group = next(g for g in review.groups(ws) if g["id"] == "study:EX-101")
    kinds = {i["id"].split("|")[1]: i["kind"] for i in group["issues"]}
    assert kinds == {"dose_mg": "conflict", "n": "difference"}           # the same route and food state: no conflict
    assert group["open"] == 2
    with pytest.raises(review.ReviewError, match="settle 2 open items"):
        review.confirm(ws, group["id"], by="u")

    dose = next(i for i in group["issues"] if i["id"].endswith("dose_mg"))
    ten = next(o for o in dose["options"] if o["value"] == 10)
    with pytest.raises(review.ReviewError, match="choose one of the options"):
        review.select(ws, group["id"], dose["id"], option="v9", by="u")
    group = review.select(ws, group["id"], dose["id"], option=ten["id"], by="u")
    settled = next(i for i in group["issues"] if i["id"] == dose["id"])
    assert settled["selected"] == ten["id"] and len(settled["options"]) == 3   # the final value stays, with its alternatives
    group = review.reopen(ws, group["id"], dose["id"], by="u")             # changeable until the group is confirmed
    assert group["open"] == 2
    review.select(ws, group["id"], dose["id"], option=ten["id"], by="u")
    review.select(ws, group["id"], f"{group['id']}|n", option="explained", by="u")
    confirmed = review.confirm(ws, group["id"], by="u")
    assert confirmed["state"] == "confirmed"
    kept = {i["id"]: i["selected"] for i in confirmed["issues"]}           # still shown, with the final selection
    assert kept == {dose["id"]: ten["id"], f"{group['id']}|n": "explained"}
    by_id = {d.id: d for d in datasets(ws)}
    assert by_id[first.id].study["dose_mg"] == by_id[second.id].study["dose_mg"] == 10   # the selection is applied
    assert (by_id[first.id].study["n"], by_id[second.id].study["n"]) == (14, 12)            # explained: each keeps its n
    # the two files give the same profile (I3): it loads once, the other set aside as its duplicate, both files named
    states = sorted(d.state.value for d in by_id.values())
    assert states == ["ACCEPTED", "REJECTED"]
    assert "the same profile" in next(d for d in by_id.values() if d.state is EvidenceState.REJECTED).decision_reason
    assert any("gives the same profile" in n for n in confirmed["notes"])
    with pytest.raises(review.ReviewError, match="confirmed already"):
        review.reopen(ws, group["id"], dose["id"], by="u")


def test_an_oral_study_with_no_food_state_and_values_below_the_lloq_ask_their_questions(tmp_path):
    ws, *_ = _project(tmp_path)
    d = ObservedDataset(id=new_dataset_id(), kind="profile", study={"study_id": "EX-2", "route": "oral", "dose_mg": 10,
                                                                     "n": 12, "n_timepoints": 3, "statistic": "mean"},
                        analyte="parent", matrix="plasma", time_unit="h", unit="ng/ml",
                        series=(Series(name="mean", statistic="arithmetic_mean", times=(1, 2, 6), values=(40.0, 30.0, None)),),
                        origin=Origin.CLIENT, extraction="CELL", provider="CLIENT",
                        source=SourceRef(doc_sha256="c" * 64, page=1, title="pk.csv"), quote="row")
    propose_dataset(ws, d, actor="u")
    group = next(g for g in review.groups(ws) if g["id"] == "study:EX-2")
    food = next(i for i in group["issues"] if "food" in i["id"])
    lloq = next(i for i in group["issues"] if "lloq" in i["id"])
    assert food["kind"] == "question" and lloq["answer"] is True
    review.select(ws, group["id"], food["id"], option="fed", by="u")
    with pytest.raises(review.ReviewError, match="positive number"):
        review.select(ws, group["id"], lloq["id"], answer=0, by="u")
    review.select(ws, group["id"], lloq["id"], answer=0.5, by="u")
    review.confirm(ws, group["id"], by="u")
    study = datasets(ws)[0].study
    assert (study["food_state"], study["lloq"]) == ("fed", 0.5)


def test_a_client_value_twofold_off_the_literature_is_a_conflict_on_the_compound_card(tmp_path):
    ws, *_ = _project(tmp_path)
    literature = propose(ws, EvidenceItem(id=new_id(), req_id="REQ-bind.fu", target="bind.fu", value=0.30, unit=None,
                                          source_type=SourceType.PUBLICATION, quote="fu was 0.30",
                                          source=SourceRef(doi="10.1/fu", title="paper")), actor="agent:a2")
    client = propose(ws, EvidenceItem(id=new_id(), req_id="REQ-bind.fu", target="bind.fu", value=0.09, unit=None,
                                      source_type=SourceType.CLIENT_FILE, quote="[PPB row 3] C3=0.09", provider="CLIENT",
                                      extraction="CELL", source=SourceRef(doc_sha256="d" * 64, page=1, title="adme.xlsx")),
                     actor="u")
    group = next(g for g in review.groups(ws) if g["kind"] == "compound")
    conflict = group["issues"][0]
    assert conflict["kind"] == "conflict" and "3.3-fold apart" in conflict["text"]
    assert [o["id"] for o in conflict["options"]] == ["client", literature.id]
    review.select(ws, group["id"], conflict["id"], option=literature.id, by="u")
    review.confirm(ws, group["id"], by="u")
    states = {e.id: e.state for e in items(ws)}
    assert states[client.id] is EvidenceState.REJECTED and states[literature.id] is EvidenceState.PROPOSED
    assert review.groups(ws) == []                                          # the rejected value leaves no group behind


def test_the_release_model_waits_for_its_product_and_a_value_typed_by_a_person_needs_no_confirmation(tmp_path):
    ws, library, brief, matrix, _ = _project(tmp_path)
    ingest(ws, library, _workbook(), "client.xlsx", by="u", matrix=matrix, brief=brief)
    product = next(g for g in review.groups(ws) if g["kind"] == "product")
    profile = product["items"][0]["id"]
    assert not review.product_confirmed(ws, profile)
    review.confirm(ws, product["id"], by="u")
    assert review.product_confirmed(ws, profile)
    typed = EvidenceItem(id=new_id(), req_id="REQ-phys.mw", target="phys.mw", value=225.2, unit="g/mol",
                         source_type=SourceType.CLIENT_FILE, quote="MW 225.2", provider="CLIENT", extraction="MANUAL",
                         source=SourceRef(title="typed"))
    assert included(propose(ws, typed, actor="u"))


def test_categorical_facts_are_compared_after_normalising():
    assert _normal("route", " PO ") == _normal("route", "oral") == "oral"
    assert _normal("food_state", "Fasting") == "fasted" and _normal("dose_mg", 10) == _normal("dose_mg", 10.0)


# --- across files (build I3, plan §3.4) -----------------------------------------------------------------------------


def _profile(ws, study_id: str, values: tuple, *, file: str, doc: str | None = None, analyte: str = "parent",
             series: str = "mean") -> ObservedDataset:
    d = ObservedDataset(id=new_dataset_id(), kind="profile",
                        study={"study_id": study_id, "route": "oral", "food_state": "fasted", "dose_mg": 10, "n": 12,
                               "n_timepoints": 3, "statistic": "mean"},
                        analyte=analyte, matrix="plasma", time_unit="h", unit="ng/ml",
                        series=(Series(name=series, statistic="arithmetic_mean", times=(1, 2, 6), values=values),),
                        origin=Origin.CLIENT, extraction="CELL", provider="CLIENT",
                        source=SourceRef(doc_sha256=doc or hashlib.sha256(file.encode()).hexdigest(), page=1,
                                         locator="Conc!A1", title=file), quote="row")
    return propose_dataset(ws, d, actor="u")


def test_one_files_profiles_and_another_analyte_are_never_rivals(tmp_path):
    ws, *_ = _project(tmp_path)
    _profile(ws, "EX-7", (40.0, 30.0, 10.0), file="a.xlsx")
    _profile(ws, "EX-7", (90.0, 70.0, 20.0), file="a.xlsx", series="subject 1")    # the same file: individual data
    _profile(ws, "EX-7", (4.0, 3.0, 1.0), file="b.xlsx", analyte="M1")             # another file, the metabolite
    (group,) = review.groups(ws)
    assert not group["issues"] and not group["notes"]


def test_a_third_file_matching_the_second_is_its_duplicate_not_a_second_conflict(tmp_path):
    ws, *_ = _project(tmp_path)
    _profile(ws, "EX-8", (40.0, 30.0, 10.0), file="a.xlsx")
    b = _profile(ws, "EX-8", (60.0, 30.0, 10.0), file="b.xlsx")
    c = _profile(ws, "EX-8", (61.0, 30.0, 10.0), file="c.xlsx")                    # within 10 % of b
    (group,) = review.groups(ws)
    assert [i["id"] for i in group["issues"] if "profile:" in i["id"]] == [f"study:EX-8|profile:{b.id}"]
    assert next(i for i in group["items"] if i["id"] == c.id)["duplicate_of"] == b.id
    conflict = group["issues"][0]
    review.select(ws, group["id"], conflict["id"], option="second", by="u")
    review.confirm(ws, group["id"], by="u")
    kept = [d for d in datasets(ws) if d.state is EvidenceState.ACCEPTED]
    assert [d.id for d in kept] == [b.id]


def test_one_study_written_two_ways_is_one_group_and_differing_profiles_are_a_conflict(tmp_path):
    ws, *_ = _project(tmp_path)
    a = _profile(ws, "EX-101", (40.0, 30.0, 10.0), file="a.xlsx")
    b = _profile(ws, "ex 101", (52.0, 30.0, 10.0), file="b.xlsx")     # 23 % apart at 1 h: beyond the 10 %
    (group,) = review.groups(ws)
    assert group["id"] == "study:EX-101" and any("Also called ex 101" in n for n in group["notes"])
    conflict = next(i for i in group["issues"] if "profile:" in i["id"])
    assert "differ by up to 23%" in conflict["text"] and [o["id"] for o in conflict["options"]] == ["first", "second", "both"]
    with pytest.raises(review.ReviewError, match="settle 1 open item"):
        review.confirm(ws, group["id"], by="u")
    review.select(ws, group["id"], conflict["id"], option="both", by="u")      # two arms, each under its own id
    review.confirm(ws, group["id"], by="u")
    by_id = {d.id: d for d in datasets(ws)}
    assert (by_id[a.id].study["study_id"], by_id[b.id].study["study_id"]) == ("EX-101", "EX-101-2")
    assert all(d.state is EvidenceState.ACCEPTED for d in by_id.values())


def test_a_profile_kept_over_the_other_sets_the_other_aside(tmp_path):
    ws, *_ = _project(tmp_path)
    a = _profile(ws, "EX-1", (40.0, 30.0, 10.0), file="a.xlsx")
    b = _profile(ws, "EX-1", (60.0, 30.0, 10.0), file="b.xlsx")
    group = review.groups(ws)[0]
    conflict = next(i for i in group["issues"] if "profile:" in i["id"])
    review.select(ws, group["id"], conflict["id"], option="second", by="u")
    review.confirm(ws, group["id"], by="u")
    by_id = {d.id: d for d in datasets(ws)}
    assert by_id[a.id].state is EvidenceState.REJECTED and by_id[b.id].state is EvidenceState.ACCEPTED


def test_a_study_named_at_upload_links_the_sheets_other_name_once_the_person_says_so(tmp_path):
    from modeler_project.documents import DocumentLibrary

    ws, *_ = _project(tmp_path)
    library = DocumentLibrary(ws)
    sha = library.add(b"Subject,Time,Conc\n1,1,40\n", "pk_101.csv", role="client_file", by="u").content["sha256"]
    library.tag(sha, "clinical", by="u", study="EXZ-101")
    d = _profile(ws, "Study 101", (40.0, 30.0, 10.0), file="pk_101.csv", doc=sha)
    group = review.groups(ws)[0]
    assert group["id"] == "study:Study 101"
    link = next(i for i in group["issues"] if i["kind"] == "link")
    assert "tagged at upload as study EXZ-101" in link["text"] and group["open"] == 1
    moved = review.select(ws, group["id"], link["id"], option="same", by="u")
    assert moved["id"] == "study:EXZ-101" and moved["open"] == 0          # regrouped at once, the answer kept on it
    back = review.reopen(ws, moved["id"], link["id"], by="u")             # changeable until confirmed
    assert back["id"] == "study:EXZ-101" and review.groups(ws)[0]["id"] == "study:Study 101"
    review.select(ws, "study:Study 101", link["id"], option="same", by="u")
    review.confirm(ws, "study:EXZ-101", by="u")
    renamed = next(x for x in datasets(ws) if x.id == d.id)
    assert renamed.study["study_id"] == "EXZ-101" and renamed.state is EvidenceState.ACCEPTED
    answered = review.groups(ws)[0]
    assert answered["id"] == "study:EXZ-101" and answered["issues"][0]["selected"] == "same"


def test_a_dissolution_profile_two_files_give_differently_is_settled_on_its_product(tmp_path):
    import io

    from openpyxl import load_workbook

    from modeler_intake.client_template import build_template
    from modeler_project.dissolution_register import profiles

    def workbook(shift: float) -> bytes:
        wb = load_workbook(io.BytesIO(build_template()))
        for t, v in ((15, 55), (30, 85), (45, 97)):
            value = v - (shift if t == 30 else 0)
            wb["Dissolution"].append(["Test 10 mg tablet", "TEST", 10, "B1", "USP 2 paddle", 50, "phosphate", 6.8, 900, 37,
                                      None, t, "min", value, value + 1, value - 1])
        out = io.BytesIO()
        wb.save(out)
        return out.getvalue()

    ws, library, brief, matrix, _ = _project(tmp_path)
    ingest(ws, library, workbook(0), "release.xlsx", by="u", matrix=matrix, brief=brief)
    ingest(ws, library, workbook(14), "stability.xlsx", by="u", matrix=matrix, brief=brief)   # 16 % lower at 30 min
    product = next(g for g in review.groups(ws) if g["kind"] == "product")
    conflict = product["issues"][0]
    assert conflict["kind"] == "conflict" and "release.xlsx, stability.xlsx differ by up to 16%" in conflict["text"]
    release = next(o for o in conflict["options"] if o["label"].startswith("release.xlsx"))
    assert round(profiles(ws)[0]["mean"][1]) == 71                        # until settled, the later file's profile
    review.select(ws, product["id"], conflict["id"], option=release["id"], by="u")
    confirmed = review.confirm(ws, product["id"], by="u")
    assert confirmed["state"] == "confirmed" and round(profiles(ws)[0]["mean"][1]) == 85    # the file the person kept
    assert review.record(ws)["profile_sources"] == {profiles(ws)[0]["id"]: release["id"]}


def test_the_same_dissolution_profile_from_two_files_is_kept_once_with_a_note(tmp_path):
    import io

    from openpyxl import load_workbook

    from modeler_intake.client_template import build_template

    wb = load_workbook(io.BytesIO(build_template()))
    for t, v in ((15, 55), (30, 85), (45, 97)):
        wb["Dissolution"].append(["Test 10 mg tablet", "TEST", 10, "B1", "USP 2 paddle", 50, "phosphate", 6.8, 900, 37,
                                  None, t, "min", v, v + 1, v - 1])
    data = io.BytesIO()
    wb.save(data)
    second = load_workbook(io.BytesIO(data.getvalue()))
    second["README"]["A1"] = "a copy, sent again by the client"       # other bytes, the same profile
    copy = io.BytesIO()
    second.save(copy)
    ws, library, brief, matrix, _ = _project(tmp_path)
    ingest(ws, library, data.getvalue(), "diss_a.xlsx", by="u", matrix=matrix, brief=brief)
    ingest(ws, library, copy.getvalue(), "diss_b.xlsx", by="u", matrix=matrix, brief=brief)
    product = next(g for g in review.groups(ws) if g["kind"] == "product")
    assert product["issues"] == [] and any("kept once" in n for n in product["notes"])
