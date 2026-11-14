"""Requirement coverage per study and per product (plan G4, contracts §6.4): found, conflicting, missing, each
disposition; per-product ids kept; project items never a study's; the rules file cannot drift from the locked
templates; one request line per missing item."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

import pytest

from modeler_intake import synthetic
from modeler_intake.anchors import anchor_text
from modeler_intake.client_template import SHEET_FOR_CATEGORY
from modeler_intake.document_reading import name_key
from modeler_project.brief import FieldRecord, FieldStatus, ProjectBrief, empty_brief, set_record
from modeler_project.intake_fixtures import write_truth
from modeler_project.intake_records import RequirementDisposition, RequirementStatus
from modeler_project.intake_rules import rules
from modeler_project.intake_store import IntakeStore
from modeler_project.ledger_models import Conflict, Entity, EntityRef, Fact, PendingLink
from modeler_project.ledger_view import LedgerView
from modeler_project.requirements import derive, load_templates
from modeler_project.store import FileProjectStore
from modeler_project.study_requirements import product_requirements, request_lines, requirement_status
from modeler_project.workspace import Workspace

pytestmark = pytest.mark.req("T-47", "T-42")

AT = "2026-11-13T09:00:00.000Z"
SHA = hashlib.sha256(b"Exampleamide: a made-up workbook for requirements").hexdigest()
_PREFIX = {"study": "st", "arm": "arm", "product": "pr", "batch": "ba", "analyte": "an"}
BIOANALYTICAL, DEMOGRAPHICS, MEAL = "REQ-obs.bioanalytical", "REQ-sys.demographics", "REQ-fe.meal"
TABLET = "Exampleamide 50 mg tablet"


class Reader(LedgerView):
    def __init__(self, ws: Workspace, conflicts: Sequence[Conflict] = ()):
        super().__init__(ws)
        self._conflicts = list(conflicts)

    def conflicts(self, *, study: str | None = None, product: str | None = None) -> list[Conflict]:
        return [c for c in self._conflicts
                if (study is None or c.entity.study == study) and (product is None or c.entity.product == product)]

    def pending_links(self, *, study: str | None = None) -> list[PendingLink]:
        return []


class Book:
    def __init__(self, tmp_path):
        self.ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
        self.store = IntakeStore(self.ws)
        self.cells = 0

    def _anchor(self) -> str:
        self.cells += 1
        return anchor_text(SHA, "workbook", "1.0", f"s:'Data'!B{self.cells}")

    def entity(self, type: str, label: str, parent: str | None = None) -> str:
        source = self._anchor()
        return self.store.entities.append("entity", lambda seq: Entity(
            id=f"{_PREFIX[type]}-{seq}", type=type, label=label, key=name_key(label), parent=parent, source=source,  # type: ignore[arg-type]
            by="code", at=AT).model_dump(mode="json")).body["id"]

    def fact(self, field: str, value: Any, entity: dict[str, str], **kw: Any) -> str:
        anchor = self._anchor()
        return self.store.facts.append("fact", lambda seq: Fact(
            id=f"f-{seq}", delivery="dl-1", entity=EntityRef(**entity), field=field, value=value, verbatim=str(value),
            anchor=anchor, method="prose", by="code", at=AT, **kw).model_dump(mode="json")).body["id"]

    def profile(self, study: str, analyte: str, matrix: str = "plasma") -> list[str]:
        return [self.fact("concentration", value, {"study": study, "analyte": analyte, "matrix": matrix, "subject": "001"},
                          unit="ng/mL", time=time, time_unit="h", statistic="individual")
                for time, value in ((1.0, 10.0), (2.0, 20.0))]


def project(*applications: str, products: Sequence[tuple[str, str]] = ()) -> ProjectBrief:
    made = empty_brief(synthetic.DRUG, by="u-1")
    made = set_record(made, "qoi.applications", FieldRecord(value=list(applications), status=FieldStatus.ENTERED))
    for i, (name, form) in enumerate(products):
        made = set_record(made, f"products[{i}].name", FieldRecord(value=name, status=FieldStatus.ENTERED))
        made = set_record(made, f"products[{i}].dosage_form", FieldRecord(value=form, status=FieldStatus.ENTERED))
    return made


def disposition(subject: str, req_id: str, kind: str, n: int = 1) -> RequirementDisposition:
    return RequirementDisposition(id=f"dp-{n}", subject=subject, req_id=req_id, disposition=kind,  # type: ignore[arg-type]
                                  why="the scientist's call", by="u-1", at=AT)


def item(statuses: Sequence[RequirementStatus], req_id: str) -> RequirementStatus:
    (found,) = [s for s in statuses if s.req_id == req_id]
    return found


def test_found_conflicting_missing_then_each_disposition(tmp_path):
    book = Book(tmp_path)
    study = book.entity("study", "EXA-201")
    analyte = book.entity("analyte", synthetic.DRUG)
    book.fact("route", "oral", {"study": study})
    book.profile(study, analyte)
    lloq = book.fact("lloq", 0.5, {"study": study, "analyte": analyte, "matrix": "plasma"}, unit="ng/mL")
    found = item(requirement_status(Reader(book.ws), study, brief=None, matrix=None).items, BIOANALYTICAL)
    assert (found.status, found.values, found.scope, found.subject, found.applies) == ("found", (lloq,), "study", study, "yes")
    other = book.fact("lloq", 1.0, {"study": study, "analyte": analyte, "matrix": "plasma"}, unit="ng/mL")
    conflict = Conflict(id="cx-0123456789", entity=EntityRef(study=study, analyte=analyte, matrix="plasma"), field="lloq",
                        time=None, values=(lloq, other), kind="value")
    conflicting = item(requirement_status(Reader(book.ws, [conflict]), study, brief=None, matrix=None).items, BIOANALYTICAL)
    assert conflicting.status == "conflicting" and set(conflicting.values) == {lloq, other}

    bare = book.entity("study", "EXA-202")
    book.fact("route", "oral", {"study": bare})
    book.profile(bare, analyte)
    reader = Reader(book.ws)
    missing = item(requirement_status(reader, bare, brief=None, matrix=None).items, BIOANALYTICAL)
    assert (missing.status, missing.values, missing.disposition) == ("missing", (), None)
    for n, kind in enumerate(("ask_client", "literature", "not_needed"), start=1):
        given = [disposition(study, BIOANALYTICAL, "not_needed", 90), disposition(bare, BIOANALYTICAL, "literature", 91),
                 disposition(bare, BIOANALYTICAL, kind, n)]                  # the latest of the subject counts
        disposed = item(requirement_status(reader, bare, brief=None, matrix=None, dispositions=given).items, BIOANALYTICAL)
        assert (disposed.status, disposed.disposition) == (kind, f"dp-{n}")
    # a found item stays found whatever a disposition says
    kept = requirement_status(reader, study, brief=None, matrix=None, dispositions=[disposition(study, BIOANALYTICAL, "ask_client")])
    assert item(kept.items, BIOANALYTICAL).status == "found"


def test_per_analyte_and_matrix_and_any_of_the_listed_fields(tmp_path):
    book = Book(tmp_path)
    study = book.entity("study", "EXA-203")
    parent, metabolite = book.entity("analyte", synthetic.DRUG), book.entity("analyte", synthetic.METABOLITE)
    book.profile(study, parent)
    book.profile(study, metabolite)
    book.fact("lloq", 0.5, {"study": study, "analyte": parent, "matrix": "plasma"}, unit="ng/mL")
    reader = Reader(book.ws)
    assert item(requirement_status(reader, study, brief=None, matrix=None).items, BIOANALYTICAL).status == "missing"
    whole = book.fact("lloq", 0.2, {"study": study, "matrix": "plasma"}, unit="ng/mL")    # one LLOQ for every analyte
    found = item(requirement_status(Reader(book.ws), study, brief=None, matrix=None).items, BIOANALYTICAL)
    assert found.status == "found" and whole in found.values
    # demographics: population (all) and one of the listed demographic fields (any)
    book.fact("population", "healthy", {"study": study})
    assert item(requirement_status(Reader(book.ws), study, brief=None, matrix=None).items, DEMOGRAPHICS).status == "missing"
    weight = book.fact("weight_mean_kg", 72.4, {"study": study})
    demographics = item(requirement_status(Reader(book.ws), study, brief=None, matrix=None).items, DEMOGRAPHICS)
    assert demographics.status == "found" and weight in demographics.values


def test_an_lloq_written_only_on_the_blq_cells_states_the_bioanalytical_item(tmp_path):
    """The one reading of "an LLOQ is stated" the checks use too: a "<0.5" cell carries its profile's LLOQ."""
    book = Book(tmp_path)
    study = book.entity("study", "EXA-301")
    parent, metabolite = book.entity("analyte", synthetic.DRUG), book.entity("analyte", synthetic.METABOLITE)
    book.fact("route", "oral", {"study": study})
    book.profile(study, parent)
    book.profile(study, metabolite)
    blq = book.fact("concentration", None, {"study": study, "analyte": parent, "matrix": "plasma", "subject": "001"},
                    unit="ng/mL", time=24.0, time_unit="h", statistic="individual", censored=True, lloq=0.5,
                    lloq_unit="ng/mL")
    reader = Reader(book.ws)
    status = item(requirement_status(reader, study, brief=None, matrix=None).items, BIOANALYTICAL)
    assert status.status == "missing"                                  # the metabolite's profile states no LLOQ
    book.fact("concentration", None, {"study": study, "analyte": metabolite, "matrix": "plasma", "subject": "001"},
              unit="ng/mL", time=24.0, time_unit="h", statistic="individual", censored=True, lloq=0.2, lloq_unit="ng/mL")
    found = item(requirement_status(Reader(book.ws), study, brief=None, matrix=None).items, BIOANALYTICAL)
    assert found.status == "found" and blq in found.values
    # a censored cell with no LLOQ of its own states none
    bare = book.entity("study", "EXA-302")
    book.profile(bare, parent)
    book.fact("concentration", None, {"study": bare, "analyte": parent, "matrix": "plasma", "subject": "001"},
              unit="ng/mL", time=24.0, time_unit="h", statistic="individual", censored=True)
    assert item(requirement_status(Reader(book.ws), bare, brief=None, matrix=None).items, BIOANALYTICAL).status == "missing"


def test_a_per_product_item_keeps_its_at_id_and_judges_its_conditions(tmp_path):
    book = Book(tmp_path)
    tablet = book.entity("product", TABLET)
    solution = book.entity("product", "Exampleamide oral solution")
    run = {"apparatus": "USP 2 paddle", "medium": "0.1 N HCl"}
    for time, value in ((15, 61.0), (30, 88.0)):
        book.fact("percent_dissolved", value, {"product": tablet}, unit="%", time=time, time_unit="min",
                  statistic="arithmetic_mean", conditions=run)
    brief = project("APP-14 virtual bioequivalence", products=[(TABLET, "tablet")])
    matrix = derive(brief)
    reader = Reader(book.ws)
    statuses = product_requirements(reader, tablet, brief=brief, matrix=matrix)
    release = next(s for s in statuses if s.req_id.startswith("REQ-form.release@"))
    assert release.req_id in {i.req_id for i in matrix.items} and release.req_id == "REQ-form.release@exampleamide-50-mg-tablet"
    assert (release.status, release.scope, release.subject, release.label) == ("found", "product", tablet,
                                                                               f"Release model of the product (dissolution) — {TABLET}")
    vbe = item(statuses, "REQ-vbe.rld_dissolution")                          # the VBE item asks for the pH too
    assert vbe.status == "missing" and vbe.template == "req-app-vbe"
    assert product_requirements(reader, tablet, brief=None, matrix=None)[0].req_id == release.req_id   # the same slug rule
    (only,) = product_requirements(reader, solution, brief=None, matrix=None)
    assert only.req_id == "REQ-form.release@exampleamide-oral-solution" and only.status == "not_applicable"
    assert product_requirements(reader, tablet, brief=None, matrix=None,
                                dispositions=[disposition(tablet, "REQ-vbe.rld_dissolution", "ask_client")]) \
        == product_requirements(reader, tablet, brief=None, matrix=None)       # no VBE application: no VBE item


def test_project_scope_items_are_not_a_studys(tmp_path):
    book = Book(tmp_path)
    study = book.entity("study", "EXA-204")
    book.fact("route", "oral", {"study": study})
    book.fact("food_state", "fed", {"study": study})
    result = requirement_status(Reader(book.ws), study, brief=project("APP-12 food effect"), matrix=None)
    scoped = set(rules().routing.item_scope["study"])
    assert {i.req_id for i in result.items} == {DEMOGRAPHICS, BIOANALYTICAL, MEAL} <= scoped
    assert all(i.scope == "study" and i.subject == study for i in result.items)
    assert result.routing.templates == ("req-core-small-molecule", "req-app-food-effect")


def test_when_is_judged_with_the_studys_own_food_state(tmp_path):
    book = Book(tmp_path)
    fasted, fed = book.entity("study", "EXA-205"), book.entity("study", "EXA-206")
    for study, state in ((fasted, "fasted"), (fed, "fed")):
        book.fact("route", "oral", {"study": study})
        book.fact("food_state", state, {"study": study})
    loaded = rules()       # an edited copy that judges the core's fed-study item per study (it has `when: {food: [fed]}`)
    scope = {**loaded.routing.item_scope, "study": (*loaded.routing.item_scope["study"], "REQ-obs.fed")}
    edited = loaded.model_copy(update={"routing": loaded.routing.model_copy(update={"item_scope": scope})})
    brief = project("APP-12 food effect")
    reader = Reader(book.ws)
    assert item(requirement_status(reader, fasted, brief=brief, matrix=None, rules=edited).items,
                "REQ-obs.fed").status == "not_applicable"
    assert item(requirement_status(reader, fed, brief=brief, matrix=None, rules=edited).items, "REQ-obs.fed").applies == "yes"


def test_every_item_the_rules_file_names_exists_in_the_loaded_templates():
    loaded = rules()
    items = {raw["id"]: raw for template in load_templates() for raw in template["items"]}
    scoped = [req for reqs in loaded.routing.item_scope.values() for req in reqs]
    assert set(scoped) <= set(items), "intake_rules.yaml routing.item_scope names an item no template has"
    assert set(loaded.routing.item_fields) <= set(items), "routing.item_fields names an item no template has"
    assert set(loaded.routing.item_fields) <= set(scoped)
    per_product = {req for req in loaded.routing.item_scope["product"] if items[req].get("per") == "solid_product"}
    assert per_product == {"REQ-form.release"}


def test_request_lines_give_one_line_per_missing_item():
    def status(req_id: str, scope: str, subject: str, state: str, **kw: Any) -> RequirementStatus:
        return RequirementStatus(req_id=req_id, template=kw.pop("template", "req-core-small-molecule"), label=req_id,
                                 scope=scope, subject=subject, criticality="REQUIRED", applies=kw.pop("applies", "yes"),  # type: ignore[arg-type]
                                 status=state, **kw)  # type: ignore[arg-type]
    statuses = [
        status(BIOANALYTICAL, "study", "st-1", "missing"),
        status(BIOANALYTICAL, "study", "st-1", "missing"),                     # the same item twice: one line
        status(BIOANALYTICAL, "study", "st-2", "found", values=("f-1",)),
        status(MEAL, "study", "st-2", "ask_client", template="req-app-food-effect", disposition="dp-1"),
        status(DEMOGRAPHICS, "study", "st-2", "literature", disposition="dp-2"),
        status(DEMOGRAPHICS, "study", "st-3", "not_needed", disposition="dp-3"),
        status("REQ-form.release@exampleamide-50-mg-tablet", "product", "pr-4", "missing"),
        status(MEAL, "study", "st-3", "not_applicable", applies="no"),
    ]
    lines = request_lines(statuses, labels={"st-1": "230-23", "st-2": "231-24", "pr-4": TABLET})
    assert [(line.req_id, line.what) for line in lines] == [
        (BIOANALYTICAL, f"{BIOANALYTICAL} — study 230-23"), (MEAL, f"{MEAL} — study 231-24"),
        ("REQ-form.release@exampleamide-50-mg-tablet", "REQ-form.release@exampleamide-50-mg-tablet")]
    assert lines[1].why == "food effect" and lines[0].why == "the model itself"
    assert lines[2].product == TABLET and lines[0].product is None and all(line.required for line in lines)
    assert lines[2].sheet == SHEET_FOR_CATEGORY["dissolution"] and lines[1].sheet == SHEET_FOR_CATEGORY["clinical_pk_fed"]


def test_the_truth_studies_and_products(tmp_path):
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    write_truth(ws, (*synthetic.delivery(), synthetic.template_workbook()))
    reader = Reader(ws)
    by_label = {e.label: e.id for e in reader.entities("study")}
    template = requirement_status(reader, by_label["EXA-101"], brief=None, matrix=None)
    assert {i.req_id: i.status for i in template.items} == {DEMOGRAPHICS: "found", BIOANALYTICAL: "found"}
    fed = requirement_status(reader, by_label["231-24"], brief=None, matrix=None)
    assert item(fed.items, MEAL).status == "missing" and item(fed.items, BIOANALYTICAL).status == "found"
    first = item(requirement_status(reader, by_label["230-23"], brief=None, matrix=None).items, BIOANALYTICAL)
    stating = [reader.value(v) for v in first.values]
    assert first.status == "found" and len([v for v in stating if v.field == "lloq"]) == 2   # the parent's and the metabolite's
    assert all(v.field == "lloq" or (v.censored and v.lloq is not None) for v in stating)   # and the "<x" cells' own LLOQ
    products = {p.label: p.id for p in reader.entities("product")}
    vessels = product_requirements(reader, products[f"{synthetic.DRUG} IR tablet"], brief=None, matrix=None)
    assert [(s.req_id, s.status) for s in vessels] == [("REQ-form.release@exampleamide-ir-tablet", "missing")]  # no apparatus
    template_tablet = product_requirements(reader, products[f"{synthetic.DRUG} 10 mg tablet"], brief=None, matrix=None)
    assert [s.status for s in template_tablet] == ["found"]
