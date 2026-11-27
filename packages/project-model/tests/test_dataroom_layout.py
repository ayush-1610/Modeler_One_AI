"""The page in its groups, as the API gives it (plan 2026-11-26 §9, slice 5a): code places every part of a room in one
section of the layers map, so the page draws what it is told. The delivery is the made-up Exampleamide one."""

from __future__ import annotations

import pytest

from modeler_project.dataroom import DataRoomStore, room_inputs
from modeler_project.dataroom.assemble import assemble
from modeler_project.dataroom.layers import load_layers
from modeler_project.dataroom.layout import OLD_ADDRESSES, build_layout
from modeler_project.dataroom.reading import read_uploads
from modeler_project.dataroom.synthetic import delivery, seed
from modeler_project.store import FileProjectStore
from modeler_project.workspace import Workspace

pytestmark = pytest.mark.req("T-47")


@pytest.fixture(scope="module")
def view(tmp_path_factory):
    root = tmp_path_factory.mktemp("layout")
    store = DataRoomStore(Workspace(FileProjectStore(root), "t1", "p1"))
    for name, data in delivery().items():
        store.add_upload(name, data, by="user:m")
    read_uploads(store, use_ocr=False, workers=1)
    seed(store, confirmed=True)
    return assemble(room_inputs(store))


def _sections(view):
    return [s for g in view.layout for s in g.sections]


def test_the_layout_is_the_maps_groups_and_sections_in_page_order(view):
    layers = load_layers()
    assert [g.id for g in view.layout] == [g.id for g in layers.groups]
    assert [s.id for s in _sections(view)] == [s.id for g in layers.groups for s in g.sections]


def test_every_value_and_decision_is_placed_once_and_every_profile_once(view):
    placed = [k for s in _sections(view) for k in s.values]
    keys = [v.key for v in (*view.substance, *view.adme, *view.products)] + [v.key for st in view.studies for v in st.facts]
    assert sorted(placed) == sorted(keys)           # one place each (a key may repeat: one field, several values)
    homes: dict[str, set[str]] = {}
    for sec in _sections(view):
        for k in sec.values:
            homes.setdefault(k, set()).add(sec.id)
    assert all(len(v) == 1 for v in homes.values())  # a field's values all in one section
    decisions = [d for s in _sections(view) for d in s.decisions]
    assert sorted(decisions) == sorted(d.id for d in view.decisions if not d.on_inputs)   # D1's are Inputs'
    profiles = [p for s in _sections(view) for p in s.dissolution]
    assert sorted(profiles) == sorted(d.id for d in view.dissolution) and len(profiles) == len(set(profiles))


def test_the_release_inputs_are_model_input_and_the_other_profiles_supporting_evidence(view):
    by = {s.id: s for s in _sections(view)}
    chosen = {d.chosen or d.suggested for d in view.decisions if d.id.startswith("release:")}
    assert set(by["release"].dissolution) == chosen and not chosen & set(by["other_dissolution"].dissolution)
    assert all(d.startswith(("release:", "release-model:")) for d in by["release"].decisions)
    assert "analysis-set:EX-01" in by["observed"].decisions and "be" in by["observed"].parts
    assert by["observed"].status != "empty" and by["other_analytes"].status == "empty"   # one analyte here


def test_a_value_the_question_requires_is_placed_in_model_input_data(view):
    fu = next(v.key for v in view.adme if v.key.startswith("adme.fu"))
    plain = {s.id: s for g in build_layout(view) for s in g.sections}
    assert fu in plain["literature"].values
    needed = {s.id: s for g in build_layout(view, required={"field:adme.fu"}) for s in g.sections}
    assert fu in needed["substance"].values and fu not in needed["literature"].values


def test_every_old_address_opens_a_section_that_exists(view):
    ids = {s.id for s in _sections(view)}
    assert set(OLD_ADDRESSES.values()) <= ids
    assert {s.id for s in view.sections} <= set(OLD_ADDRESSES)        # every section of today has a new home


def test_an_empty_room_shows_every_group_and_section_with_what_it_will_hold():
    """Slice 5c: before a file arrives, the page still shows each group and section, each saying what it will hold."""
    from modeler_project.dataroom.assemble import Inputs

    empty = assemble(Inputs(files=[], docs={}))
    sections = _sections(empty)
    assert [s.id for s in sections] == [s.id for g in load_layers().groups for s in g.sections]
    assert all(s.status == "empty" and s.count == 0 and s.holds for s in sections)
    assert {g.status for g in empty.layout} == {"empty"}


def test_each_check_is_placed_on_what_it_concerns_and_the_rest_with_the_files(view):
    """Slice 5d: the dose card's checks on Drug Substance Properties, a lot's on the products, simulated-looking
    concentrations on Observed PK; a check about reading the files stays with the files."""
    from modeler_project.dataroom.model import Chip, Problem

    listing = Chip(file="Clinical/subjects.csv", part="sheet:subjects", line=1)
    checks = (Problem(code="DOSE_BASIS_UNKNOWN", message="m"), Problem(code="LOT_CONFLICT", message="m"),
              Problem(code="LOOKS_SIMULATED", message="m"), Problem(code="FACT_REFUSED", message="m"),
              Problem(code="PERSONAL_DATA", message="m", where=listing))
    room = view.model_copy(update={"problems": checks})
    placed = {s.id: [room.problems[i].code for i in s.checks] for g in build_layout(room) for s in g.sections if s.checks}
    assert placed == {"substance": ["DOSE_BASIS_UNKNOWN"], "products": ["LOT_CONFLICT"], "observed": ["LOOKS_SIMULATED"],
                      "files": ["FACT_REFUSED", "PERSONAL_DATA"]}


def test_needs_you_lists_what_a_person_must_do_each_with_the_one_section_where_it_is_done(view):
    """Slice 5d: the question to confirm first, then what disagrees, the checks to settle (one line per kind of check
    on one item), and the decisions waiting (never Inputs' D1 choices); a reading check is not there."""
    from modeler_project.dataroom.layout import needs_you
    from modeler_project.dataroom.model import Problem

    waiting = tuple(d.model_copy(update={"chosen": None}) for d in view.decisions)
    differs = tuple(Problem(code="NCA_DIFFERS", message=f"subject {i}: AUC differs") for i in (1, 2, 3))
    studies = (view.studies[0].model_copy(update={"problems": (*view.studies[0].problems, *differs)}), *view.studies[1:])
    room = view.model_copy(update={"question_confirmed": False, "decisions": waiting, "studies": studies,
                                   "problems": (Problem(code="DOSE_BASIS_UNKNOWN", message="ask which"),
                                                Problem(code="FACT_REFUSED", message="not in its quote"))})
    items = needs_you(room, build_layout(room))
    assert items[0].id == "question" and items[0].section == "question"
    decided = {i.id.split(":", 1)[1]: i.section for i in items if i.kind == "decision"}
    assert set(decided) == {d.id for d in waiting if not d.on_inputs} and not any(":EX-01" in k and k.startswith(
        ("population", "sex", "meal")) for k in decided)
    assert decided["analysis-set:EX-01"] == "observed" and decided["solubility-ref"] == "substance"
    nca = next(i for i in items if i.id == "check:NCA_DIFFERS:EX-01")
    assert (nca.kind, nca.section, nca.title) == ("conflict", "observed", "EX-01: The client's NCA is not reproduced")
    assert nca.count >= 3                                     # every NCA difference of the study, said once
    dose = next(i for i in items if i.id == "check:DOSE_BASIS_UNKNOWN:")
    assert (dose.kind, dose.section, dose.detail) == ("check", "substance", "ask which")
    assert not any("FACT_REFUSED" in i.id for i in items)    # shown with the files, not asked of a person
    kinds = [i.kind for i in items]
    assert kinds == sorted(kinds, key=["question", "conflict", "check", "decision"].index)
