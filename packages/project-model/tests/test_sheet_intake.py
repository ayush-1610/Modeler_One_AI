"""Build C2 (plan 2026-11-05 §3.1): each data sheet of a client's workbook read by code on arrival; a reading that needs
nothing more is saved at once, one that needs the study's facts waits on its card and asks for them. The workbooks are
laid out the way CROs send them (software test data, made-up numbers)."""

from __future__ import annotations

import io
import math

import pytest
from openpyxl import Workbook

from modeler_intake.grid import read_workbook_bytes
from modeler_intake.sheet_form import SheetForm
from modeler_project import FileProjectStore, Workspace
from modeler_project import client_review as review
from modeler_project.client_data import ingest, submission
from modeler_project.dataset_register import dataset, datasets
from modeler_project.dissolution_register import profiles
from modeler_project.documents import DocumentLibrary
from modeler_project.evidence import EvidenceState
from modeler_project.sheet_intake import SheetIntakeError, finish, needs, read_on_arrival

pytestmark = pytest.mark.req("T-47")
TIMES = ["Pre-dose", "1.00", "2.00", "4.00", "8.00", "24.00"]


def _save(wb: Workbook) -> bytes:
    raw = io.BytesIO()
    wb.save(raw)
    return raw.getvalue()


def _be_arm() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["Study 230-23: plasma concentrations of desvenlafaxine (ng/mL), Reference, 50 mg, fasting"])
    ws.append([])
    ws.append(["Time (hr)"])
    ws.append(["Subject No.", "Period", *TIMES])
    for i in range(1, 5):
        ws.append([f"{i:03d}", "I", "BLQ", *(round(150 * (math.exp(-0.06 * float(t)) - math.exp(-0.35 * float(t))) * (0.9 + 0.05 * i), 2)
                                           for t in TIMES[1:])])
    ws.append([])
    ws.append(["BLQ = below the lower limit of quantification (0.50 ng/mL)"])
    return _save(wb)


def _dissolution() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "pH 6.8"
    ws.append([("Dissolution of Exampleamide ER Tablets 50 mg (Test), Batch No. B501, USP II (paddle), 50 rpm, 900 mL "
                "phosphate buffer pH 6.8")])
    ws.append(["Time (hr)", *(f"Vessel {i}" for i in range(1, 7))])
    for t in (1, 2, 4, 8, 12):
        base = 100 * (1 - math.exp(-math.log(2) * (t / 5.0) ** 1.2))
        ws.append([t, *(round(base + d, 2) for d in (-1, -0.5, 0, 0, 0.5, 1))])
    return _save(wb)


@pytest.fixture
def ws(tmp_path) -> Workspace:
    return Workspace(FileProjectStore(tmp_path), "t1", "p1")


def test_a_be_arm_is_read_on_arrival_and_waits_on_its_study_for_what_the_sheet_does_not_say(ws):
    library = DocumentLibrary(ws)
    sub = ingest(ws, library, _be_arm(), "230-23 Fasting Reference.xlsx", by="u")
    draft = submission(ws, sub["id"])["readings"]["Sheet1"]
    assert draft["by"] == "code" and set(draft["needs"]) == {"n", "formulation", "purpose"}     # dose, route, food read
    assert datasets(ws) == []                                                                   # nothing saved yet
    (group,) = [g for g in review.groups(ws) if g["id"] == "study:230-23-REF"]
    (item,) = group["items"]
    assert item["kind"] == "draft" and item["draft"]["labels"]["n"] == "the number of subjects"
    assert len(item["draft"]["points"]["series"]) == 4 and group["open"] == 1 and group["state"] == "to_confirm"
    with pytest.raises(review.ReviewError, match="open item"):
        review.confirm(ws, group["id"], by="u")

    # answered in part: kept, the rest still asked
    assert finish(ws, library, sub["id"], "Sheet1", {"n": "4"}, by="u") == []
    assert submission(ws, sub["id"])["readings"]["Sheet1"]["needs"] == ["formulation", "purpose"]
    ids = finish(ws, library, sub["id"], "Sheet1", {"formulation": "mr", "purpose": "external_validation"}, by="u")
    (made,) = [dataset(ws, i) for i in ids]
    assert made.state is EvidenceState.PROPOSED and made.awaits_client_confirmation() and made.study["n"] == 4
    assert (made.study["dose_mg"], made.study["formulation"], made.study["food_state"]) == (50.0, "mr", "fasted")
    assert made.purpose == "external_validation" and made.study["lloq"] == 0.5
    (group,) = [g for g in review.groups(ws) if g["id"] == "study:230-23-REF"]
    assert [i["kind"] for i in group["items"]] == ["dataset"] and group["open"] == 0
    review.confirm(ws, group["id"], by="u")
    assert dataset(ws, made.id).state is EvidenceState.ACCEPTED


def test_a_dissolution_sheet_that_needs_nothing_is_saved_at_once_else_it_asks_on_products(ws):
    library = DocumentLibrary(ws)
    sub = ingest(ws, library, _dissolution(), "Dissolution Test pH 6.8.xlsx", by="u")
    assert submission(ws, sub["id"])["readings"]["pH 6.8"]["needs"] == ["product"]             # no product in the brief
    (card,) = [g for g in review.groups(ws) if g["kind"] == "sheet"]
    assert card["tab"] == "formulations" and card["items"][0]["draft"]["needs"] == ["product"] and card["open"] == 1
    # the brief's product named by the sheet: read again, nothing left to give, saved at once
    workbook = read_workbook_bytes(_dissolution(), "Dissolution Test pH 6.8.xlsx")
    done = read_on_arrival(ws, library, sub["id"], workbook, by="u", drug="exampleamide",
                           products=[{"name": "Exampleamide ER Tablets 50 mg", "role": "TEST"}], sheets=["pH 6.8"])
    assert "pH 6.8" in done["saved"] and not done["waiting"]
    assert not [g for g in review.groups(ws) if g["kind"] == "sheet"]
    (profile,) = profiles(ws)
    assert profile["times_min"] == [60, 120, 240, 480, 720] and profile["n"] == 6
    product = next(g for g in review.groups(ws) if g["kind"] == "product")
    assert product["state"] == "to_confirm"                                       # loads once a person confirms it


def test_answers_are_checked_against_their_choices(ws):
    library = DocumentLibrary(ws)
    sub = ingest(ws, library, _be_arm(), "230-23 Fasting Reference.xlsx", by="u")
    for answers, problem in (({"purpose": "fitting"}, "what the study is for"), ({"n": "4.5"}, "whole number"),
                             ({"formulation": "pill"}, "dosage form"), ({"n": "0"}, "above 0"), ({"colour": "red"}, "unknown")):
        with pytest.raises(SheetIntakeError, match=problem):
            finish(ws, library, sub["id"], "Sheet1", answers, by="u")


@pytest.mark.parametrize(("constants", "study", "kind", "expected"), [
    ({"study_id": "S1", "dose": "10", "route": "oral", "formulation": "ir_tablet", "food_state": "fed"},
     {"n": "12", "purpose": "model_building"}, "concentration_time", []),
    ({"study_id": "S1", "dose": "10", "route": "iv_infusion"}, {"n": "12", "purpose": "model_building"},
     "concentration_time", ["infusion_time_min"]),
    ({"dose": "0", "route": "oral"}, {}, "concentration_time", ["study_id", "dose", "n", "formulation", "food_state", "purpose"]),
    ({"product": "Tab", "role": "TEST", "medium": "water"}, {}, "dissolution", ["batch"]),
])
def test_what_a_reading_needs_is_what_the_study_record_or_the_product_needs(constants, study, kind, expected):
    form = SheetForm(sheet="S", kind=kind, value_columns=["B"], time_column="A", constants=constants, study=study)
    assert needs(form) == expected


def test_a_problem_the_card_asks_about_is_not_repeated_and_each_is_said_once(ws):
    library = DocumentLibrary(ws)
    sub = ingest(ws, library, _be_arm(), "230-23 Fasting Reference.xlsx", by="u")
    problems = submission(ws, sub["id"])["readings"]["Sheet1"]["problems"]
    assert not any("number of subjects" in p for p in problems) and len(problems) == len(set(problems))


def test_the_reading_agents_clean_and_complete_reading_is_saved_at_once(ws):
    # build F: a reading the agent proposes replaces code's when its check is clean, and is saved when it needs nothing
    from modeler_intake.sheet_form import SheetForm
    from modeler_project.sheet_intake import adopt_agent_reading

    library = DocumentLibrary(ws)
    sub = ingest(ws, library, _dissolution(), "Dissolution Test pH 6.8.xlsx", by="u")
    code = submission(ws, sub["id"])["readings"]["pH 6.8"]
    form = SheetForm.model_validate(code["form"])
    named = form.model_copy(update={"constants": {**form.constants, "product": "Exampleamide ER Tablets 50 mg", "role": "TEST"}})
    workbook = read_workbook_bytes(_dissolution(), "Dissolution Test pH 6.8.xlsx")
    done = adopt_agent_reading(ws, library, sub["id"], workbook, "pH 6.8", named, ["the product is named in the title"],
                               by="agent:ar_1", run_id="ar_1")
    assert done == {"adopted": True, "saved": []} and len(profiles(ws)) == 1          # a dissolution sheet makes no dataset
    kept = submission(ws, sub["id"])["readings"]["pH 6.8"]
    assert kept["by"] == "agent:ar_1" and kept["needs"] == [] and kept["cleaning"][0]["text"].startswith("Above the table")
    assert not [g for g in review.groups(ws) if g["kind"] == "sheet"]                  # on its product's card, to confirm
