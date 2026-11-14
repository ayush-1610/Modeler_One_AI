"""Per-study routing (plan G4, contracts §6.4): the templates a study's own tags activate with the project's
applications, the schema gaps that block release, and `when` judged with the study's own route and food state."""

from __future__ import annotations

import hashlib
from typing import Any

import pytest

from modeler_intake import synthetic
from modeler_intake.anchors import anchor_text
from modeler_intake.document_reading import name_key
from modeler_project.brief import FieldRecord, FieldStatus, ProjectBrief, empty_brief, set_record
from modeler_project.intake_fixtures import write_truth
from modeler_project.intake_rules import rules
from modeler_project.intake_store import IntakeStore
from modeler_project.ledger_models import Entity, EntityRef, Fact
from modeler_project.ledger_view import LedgerView
from modeler_project.requirements import evaluate_when, load_templates
from modeler_project.store import FileProjectStore
from modeler_project.study_routing import (
    NO_ROUTE,
    route,
    study_tags,
    study_when,
    tag_match,
    tag_value,
    unread,
    unread_reason,
)
from modeler_project.workspace import Workspace

pytestmark = pytest.mark.req("T-47", "T-42")

AT = "2026-11-13T09:00:00.000Z"
SHA = hashlib.sha256(b"Exampleamide: a made-up study report for routing").hexdigest()
CORE, VBE = "req-core-small-molecule", "req-app-vbe"
SPECIAL, FOOD, FIH, DDI = "req-app-special-populations", "req-app-food-effect", "req-app-fih", "req-app-ddi"


def brief(*applications: str, modality: str = "small_molecule") -> ProjectBrief:
    made = empty_brief(synthetic.DRUG, by="u-1")
    made = set_record(made, "drug.modality", FieldRecord(value=modality, status=FieldStatus.ENTERED))
    return set_record(made, "qoi.applications", FieldRecord(value=list(applications), status=FieldStatus.ENTERED))


class Studies:
    """Studies with their facts, written through the store as the ledger writes them."""

    def __init__(self, tmp_path):
        self.ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
        self.store = IntakeStore(self.ws)
        self.cells = 0

    def _anchor(self) -> str:
        self.cells += 1
        return anchor_text(SHA, "docx", "1.0", f"d:t:1/r:{self.cells}/c:1")

    def study(self, label: str, **facts: Any) -> str:
        source = self._anchor()
        study = self.store.entities.append("entity", lambda seq: Entity(
            id=f"st-{seq}", type="study", label=label, key=name_key(label), source=source, by="code",
            at=AT).model_dump(mode="json")).body["id"]
        for field, values in facts.items():
            for value in values if isinstance(values, tuple) else (values,):
                anchor = self._anchor()
                self.store.facts.append("fact", lambda seq, field=field, value=value, anchor=anchor: Fact(
                    id=f"f-{seq}", delivery="dl-1", entity=EntityRef(study=study), field=field, value=value,
                    verbatim=str(value), anchor=anchor, method="prose", by="code", at=AT).model_dump(mode="json"))
        return study

    def routing(self, study: str, project: ProjectBrief | None):
        reader = LedgerView(self.ws)
        tags = study_tags(reader, study, brief=project)
        return route(study, tags, applications=(project.value("qoi.applications") or []) if project else ())


ADULT = {"route": "oral", "food_state": "fasted", "population": "healthy", "species": "Human"}


def test_an_adult_oral_fasted_study_in_a_vbe_project_activates_the_core_and_the_vbe_template(tmp_path):
    studies = Studies(tmp_path)
    routing = studies.routing(studies.study("230-23", **ADULT), brief("APP-14 virtual bioequivalence"))
    assert routing.templates == (CORE, VBE) and routing.gaps == ()
    assert routing.tags == {**ADULT, "modality": "small_molecule", "applications": "APP-14"}


def test_a_pediatric_study_in_the_same_project_also_activates_the_special_populations_template(tmp_path):
    studies = Studies(tmp_path)
    study = studies.study("230-29", **ADULT, special_population="paediatric patients")
    routing = studies.routing(study, brief("APP-14 virtual bioequivalence"))
    assert routing.templates == (CORE, VBE, SPECIAL) and routing.tags["special_population"] == "pediatric"


def test_a_fed_study_activates_the_food_effect_template_and_a_fasted_study_of_a_food_effect_project_is_not_fed(tmp_path):
    studies = Studies(tmp_path)
    fed = studies.routing(studies.study("231-24", **{**ADULT, "food_state": "fed"}), brief("APP-14 virtual bioequivalence"))
    assert fed.templates == (CORE, VBE, FOOD)
    project = brief("APP-12 food effect")
    fasted = studies.study("230-23", **ADULT)
    routing = studies.routing(fasted, project)
    assert routing.tags["food_state"] == "fasted" and routing.templates == (CORE, FOOD)    # the project's application
    when = {"food": ["fed"]}
    assert evaluate_when(when, project) is True                  # the brief's shortcut: APP-12 makes every scenario fed
    assert study_when(when, routing.tags, brief=project) is False   # the study's own food state decides
    assert study_when({"food": ["fed"]}, {}, brief=project) is None  # unstated: undetermined, never assumed
    assert study_when({"route": ["oral"], "application": ["APP-12"]}, routing.tags, brief=project) is True
    assert study_when({"route": ["iv_bolus"]}, routing.tags, brief=project) is False


def test_a_study_with_fasted_and_fed_arms_carries_both(tmp_path):
    studies = Studies(tmp_path)
    study = studies.study("231-25", **{**ADULT, "food_state": ("fasted", "fed after a high-fat breakfast")})
    routing = studies.routing(study, brief())
    assert routing.tags["food_state"] == "fasted; fed" and FOOD in routing.templates


@pytest.mark.parametrize(("facts", "project", "tag", "value"), [
    ({"route": "other"}, brief(), "route", "other"),
    ({"route": "other: subcutaneous"}, brief(), "route", "other"),
    ({"genotype": "CYP2D6 poor metabolizers"}, brief(), "genotype", "CYP2D6 poor metabolizers"),
    ({}, brief(modality="large_molecule"), "modality", "large_molecule"),
])
def test_route_other_a_genotype_study_and_a_large_molecule_are_schema_gaps(tmp_path, facts, project, tag, value):
    studies = Studies(tmp_path)
    routing = studies.routing(studies.study("230-30", **{**ADULT, **facts}), project)
    gaps = [(g.tag, g.value) for g in routing.gaps]
    assert (tag, value) in gaps and all(g.reason and g.study == routing.study for g in routing.gaps)
    reasons = {g.reason for g in routing.gaps}
    assert reasons <= {r.reason for r in rules().routing.gaps}          # the rules file's reasons, word for word


@pytest.mark.parametrize(("facts", "tag", "written"), [
    ({"route": "intravenous"}, "route", "intravenous"),                 # bolus or infusion: never taken for "other"
    ({"route": "subcutaneous"}, "route", "subcutaneous"),               # route other only when a person says so
    ({"food_state": "postprandial"}, "food_state", "postprandial"),
    ({"special_population": "children"}, "special_population", "children"),
])
def test_an_unread_routing_choice_is_a_gap_naming_the_text_never_a_confident_other(tmp_path, facts, tag, written):
    studies = Studies(tmp_path)
    routing = studies.routing(studies.study("230-33", **{**ADULT, **facts}), brief("APP-14 virtual bioequivalence"))
    assert routing.tags[tag] == written and unread(tag, written)                  # kept as written, not "other"
    assert [(g.tag, g.value, g.reason) for g in routing.gaps] == [(tag, written, unread_reason(tag, written))]
    assert written in routing.gaps[0].reason and "a person states it" in routing.gaps[0].reason
    # a `when` that reads an unread value is undetermined, never False
    assert study_when({"food": ["fed"]}, {"food_state": "postprandial"}, brief=None) is None
    assert study_when({"food": ["fed"]}, {"food_state": "fasted; postprandial"}, brief=None) is None
    assert study_when({"food": ["fed"]}, {"food_state": "fed; postprandial"}, brief=None) is True
    assert study_when({"route": ["oral"]}, {"route": "intravenous"}, brief=None) is None
    # stated by a person as a choice, the gap is gone and the rules route it
    fixed = studies.routing(studies.study("230-34", **ADULT), brief("APP-14 virtual bioequivalence"))
    assert fixed.gaps == ()


def test_statements_of_absence_route_as_the_rules_read_them_today(tmp_path):
    """Recorded behaviour, reported to the integrator: the rules file has no list of statements of absence and no
    species synonyms, and D5 writes none (they are the SME's). When the rules file gains them, this test changes."""
    studies = Studies(tmp_path)
    project = brief("APP-14 virtual bioequivalence")
    none = studies.routing(studies.study("231-40", **ADULT, co_medication="none"), project)
    assert DDI in none.templates                                       # "none" passes `present: true`
    genotype = studies.routing(studies.study("231-41", **ADULT, genotype="not genotyped"), project)
    assert [g.value for g in genotype.gaps] == ["not genotyped"]        # a genotype gap, from `present: true`
    humans = studies.routing(studies.study("231-42", **{**ADULT, "species": "Humans"}), project)
    assert FIH in humans.templates                                     # "Humans" is not name_key("Human")
    nobody = studies.routing(studies.study("231-43", **ADULT, special_population="none"), project)
    assert [(g.tag, g.value) for g in nobody.gaps] == [("special_population", "none")]     # unread: a person states it
    # a bool is a statement of presence or absence
    yes = studies.routing(studies.study("231-44", **ADULT, co_medication=True), project)
    no = studies.routing(studies.study("231-45", **ADULT, co_medication=False), project)
    assert yes.tags["co_medication"] == "yes" and DDI in yes.templates
    assert "co_medication" not in no.tags and DDI not in no.templates


def test_a_study_with_no_route_fact_is_a_gap(tmp_path):
    studies = Studies(tmp_path)
    routing = studies.routing(studies.study("230-31", food_state="fasted"), brief())
    assert "route" not in routing.tags and routing.templates == (CORE,)
    assert [(g.tag, g.value, g.reason) for g in routing.gaps] == [("route", "", NO_ROUTE)]


def test_a_tag_no_fact_states_is_absent_and_other_tags_route_by_the_rules(tmp_path):
    studies = Studies(tmp_path)
    rat = studies.routing(studies.study("TOX-1", **{**ADULT, "species": "Rat"}), brief())
    assert FIH in rat.templates
    ddi = studies.routing(studies.study("DDI-1", **ADULT, co_medication="itraconazole 200 mg"), brief())
    assert DDI in ddi.templates and FIH not in ddi.templates
    bare = studies.routing(studies.study("230-32", route="oral"), None)
    assert bare.tags == {"route": "oral"} and bare.templates == (CORE,)


def test_the_routing_table_is_the_rules_files():
    loaded = rules()
    templates = {t["id"] for t in load_templates()}
    named = {loaded.routing.core, *(r.template for r in loaded.routing.by_tag)}
    assert named <= templates, "the rules file names a template that is not loaded"
    # with an edited copy, a route the rules no longer list as a gap is none
    gaps = tuple(r for r in loaded.routing.gaps if r.tag != "route")
    edited = loaded.model_copy(update={"routing": loaded.routing.model_copy(update={"gaps": gaps})})
    assert route("st-1", {"route": "other"}, applications=(), rules=edited).gaps == ()
    assert route("st-1", {"route": "other"}, applications=()).gaps[0].tag == "route"
    # a by_tag template that is not loaded is a gap, never a silent skip
    missing = loaded.routing.by_tag[0].model_copy(update={"template": "req-app-not-there"})
    broken = loaded.model_copy(update={"routing": loaded.routing.model_copy(update={"by_tag": (missing,)})})
    found = route("st-1", {"route": "oral", "special_population": "pediatric"}, applications=(), rules=broken)
    assert found.templates == (CORE,) and "req-app-not-there" in found.gaps[0].reason


def test_tag_tests_and_values():
    rule = rules().routing.by_tag[1]                           # species not in [Human]
    assert tag_match(rule, {"species": "human"}) is None and tag_match(rule, {}) is None
    assert tag_match(rule, {"species": "Human; Rat"}) == "Rat"
    assert tag_value("route", "orally") == "oral" and tag_value("route", "intradermal") == "intradermal"
    assert unread("route", "intradermal") and not unread("route", "other") and not unread("genotype", "CYP2D6 PM")
    assert tag_value("food_state", "fasting") == "fasted" and tag_value("species", " Human ") == "Human"
    assert tag_value("route", None) is None and tag_value("genotype", "") is None
    assert tag_value("co_medication", True) == "yes" and tag_value("co_medication", False) is None


def test_the_truth_routes_each_study_by_its_own_facts(tmp_path):
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    write_truth(ws, (*synthetic.delivery(), synthetic.template_workbook()))
    reader = LedgerView(ws)
    project = brief("APP-14 virtual bioequivalence")
    by_label = {e.label: e.id for e in reader.entities("study")}
    template = route(by_label["EXA-101"], study_tags(reader, by_label["EXA-101"], brief=project),
                     applications=["APP-14"])
    assert template.templates == (CORE, VBE) and template.gaps == ()        # oral, fasted, healthy: no gap
    fed = route(by_label["231-24"], study_tags(reader, by_label["231-24"], brief=project), applications=["APP-14"])
    assert fed.templates == (CORE, VBE, FOOD) and [g.reason for g in fed.gaps] == [NO_ROUTE]   # no route is stated
