"""The Data room's groups and sections (`dataroom_layers.yaml`, plan 2026-11-26 §3): every vocabulary entry has a
place, the names are the owner's, and the question decides what moves to Model Input Data."""

from __future__ import annotations

from typing import get_args

import pytest

from modeler_intake.room_specs import FIELDS, TableKind
from modeler_project.dataroom.drafts import load_drafts
from modeler_project.dataroom.layers import Layers, load_layers, required_keys

pytestmark = pytest.mark.req("T-47")


def test_every_fact_field_and_table_kind_has_its_own_placement():
    """A field added to the vocabulary must be placed here too, or this fails naming it."""
    layers = load_layers()
    vocabulary = {f"field:{f}" for f in FIELDS} | {f"table:{k}" for k in get_args(TableKind)}
    assert sorted(vocabulary - set(layers.placements)) == []
    assert sorted(set(layers.placements) - vocabulary) == []          # no entry for a name the vocabulary lacks


def test_the_groups_carry_the_owners_names_in_page_order():
    layers = load_layers()
    assert [g.title for g in layers.groups] == ["Question and Context of Use", "Model Input Data", "Supporting Evidence",
                                                "Source Records", "Data Requests"]
    assert [s.title for s in layers.group("model_input").sections] == [
        "Test and Reference Products", "Drug Substance Properties", "In Vitro Release Input", "Clinical Study Design",
        "Observed PK and BE Outcome", "Simulation Scenarios"]


def test_population_sex_meal_and_release_model_are_chosen_on_inputs_and_their_facts_support_the_choice():
    """The owner's decision 1 (2026-11-26): the Data room records the facts, Inputs makes the choice. The demographic
    values themselves build the study's individual, so they are model inputs."""
    layers = load_layers()
    assert layers.place("field:study.population").ref == "supporting/conduct"
    assert layers.place("field:study.ethnicity").ref == "supporting/conduct"
    assert layers.place("field:study.meal_composition").ref == "supporting/conduct"
    assert layers.place("field:study.meal_times").ref == "model_input/design"
    assert layers.place("field:study.sex").ref == layers.place("table:demographics").ref == "model_input/design"


def test_a_value_the_question_requires_moves_to_model_input_data_only_where_the_map_allows_it():
    layers = load_layers()
    food = required_keys(load_drafts().items_for("food_effect"))
    vbe = required_keys(load_drafts().items_for("pbbm_bridging_vbe"))
    meal = layers.place("field:study.meal_composition", required=food)
    assert (meal.ref, meal.promoted) == ("model_input/design", True)              # it defines the simulated meal
    assert layers.place("table:particle_size", required=food).ref == "model_input/substance"
    assert layers.place("field:study.meal_composition", required=vbe).ref == "supporting/conduct"
    # the composition is required for a bridging question (Q1/Q2 sameness) yet never a model input: it stays evidence
    assert "table:composition" in vbe and layers.place("table:composition", required=vbe).ref == \
        "supporting/formulation_differences"


def test_a_dissolution_profile_not_selected_as_the_release_input_is_shown_as_evidence():
    layers = load_layers()
    assert layers.place("table:dissolution").ref == "model_input/release"
    other = layers.place("table:dissolution", selected=False)
    assert (other.ref, other.unselected) == ("supporting/other_dissolution", True)
    assert layers.place("field:dissolution.f2").ref == "supporting/other_dissolution"


def test_a_field_the_vocabulary_does_not_know_is_kept_as_other_delivered_facts():
    placed = load_layers().place("field:study.hematocrit_at_screening")
    assert (placed.ref, placed.default) == ("supporting/other_context", True)
    assert load_layers().title(placed.ref) == "Other Delivered Facts"


def test_a_map_that_names_an_undeclared_section_or_promotes_out_of_model_input_data_is_refused():
    raw = load_layers().model_dump(exclude={"sha256"})
    with pytest.raises(ValueError, match="not a declared group/section"):
        Layers(**{**raw, "placements": {"field:study.id": {"at": "model_input/nowhere"}}})
    with pytest.raises(ValueError, match="promote_to must name a Model Input Data section"):
        Layers(**{**raw, "placements": {"field:study.id": {"at": "model_input/design",
                                                          "promote_to": "supporting/conduct"}}})
