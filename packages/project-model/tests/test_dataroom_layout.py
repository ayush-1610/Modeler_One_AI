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
    assert sorted(decisions) == sorted(d.id for d in view.decisions)
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
