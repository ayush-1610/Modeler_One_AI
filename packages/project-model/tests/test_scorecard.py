"""The scorecard (plan §7.7, contracts §6.4): one per study, product and the compound, with its blockers (silent loss,
outside numbers, unassigned values, a schema gap, a failed check, an unconfirmed link); an override clears its check
and leaves it listed, and never clears a gap, a conflict or a missing required item."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

import pytest

from modeler_intake import synthetic
from modeler_intake.anchors import anchor_text
from modeler_intake.document_reading import name_key
from modeler_project.intake_checks import result_id, run_checks
from modeler_project.intake_fixtures import write_truth
from modeler_project.intake_records import CoverageSummary, Override, RequirementDisposition, SchemaGap
from modeler_project.intake_store import IntakeStore
from modeler_project.ledger_models import Conflict, Entity, EntityRef, Fact, MappingUse, PendingLink
from modeler_project.ledger_view import LedgerView
from modeler_project.scorecard import COMPOUND, scorecard
from modeler_project.store import FileProjectStore
from modeler_project.study_requirements import product_requirements, requirement_status
from modeler_project.workspace import Workspace

pytestmark = pytest.mark.req("T-47", "T-42")

AT = "2026-11-13T09:00:00.000Z"
SHA = hashlib.sha256(b"Exampleamide: a made-up delivery for the scorecard").hexdigest()
_PREFIX = {"study": "st", "arm": "arm", "product": "pr", "batch": "ba", "analyte": "an"}
NEW = MappingUse(mapping_id="mp-00000000000c", version=1)            # never approved: its values are new_mapping


class Reader(LedgerView):
    def __init__(self, ws: Workspace, conflicts: Sequence[Conflict] = (), links: Sequence[PendingLink] = ()):
        super().__init__(ws)
        self._conflicts, self._links = list(conflicts), list(links)

    def conflicts(self, *, study: str | None = None, product: str | None = None) -> list[Conflict]:
        return [c for c in self._conflicts
                if (study is None or c.entity.study == study) and (product is None or c.entity.product == product)]

    def pending_links(self, *, study: str | None = None) -> list[PendingLink]:
        return [link for link in self._links if study is None or link.study == study]


class Book:
    def __init__(self, tmp_path):
        self.ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
        self.store = IntakeStore(self.ws)
        self.cells = 0

    def _anchor(self) -> str:
        self.cells += 1
        return anchor_text(SHA, "workbook", "1.0", f"s:'Data'!C{self.cells}")

    def entity(self, type: str, label: str) -> str:
        source = self._anchor()
        return self.store.entities.append("entity", lambda seq: Entity(
            id=f"{_PREFIX[type]}-{seq}", type=type, label=label, key=name_key(label), source=source,  # type: ignore[arg-type]
            by="code", at=AT).model_dump(mode="json")).body["id"]

    def fact(self, field: str, value: Any, entity: dict[str, str], method: str = "prose", **kw: Any) -> str:
        anchor = None if method == "derived" else self._anchor()
        return self.store.facts.append("fact", lambda seq: Fact(
            id=f"f-{seq}", delivery="dl-1", entity=EntityRef(**entity), field=field, value=value, verbatim=str(value),
            anchor=anchor, method=method, by="code", at=AT, **kw).model_dump(mode="json")).body["id"]


def summary(**counts: int) -> CoverageSummary:
    base = dict(state="read", regions=1, regions_mapped=1, regions_excluded=0, regions_unread=0, numeric_cells=10,
                cells_used=10, cells_excluded=0, cells_silent=0, silent_loss=0, outside_items=0)
    return CoverageSummary(**{**base, **counts})  # type: ignore[arg-type]


def study_book(tmp_path) -> tuple[Book, dict[str, str]]:
    """A study that passes every check and has every study item found."""
    book = Book(tmp_path)
    study, analyte = book.entity("study", "EXA-401"), book.entity("analyte", synthetic.DRUG)
    on = {"study": study}
    ids = {"study": study, "analyte": analyte}
    for field, value, kw in (("dose", 50.0, {"unit": "mg"}), ("n", 12, {}), ("route", "oral", {}),
                             ("formulation", "ir_tablet", {}), ("intended_use", "model_building", {}),
                             ("salt_or_base", "base", {}), ("population", "healthy", {}), ("age_mean", 33.0, {})):
        ids[field] = book.fact(field, value, on, **kw)
    profile = {"study": study, "analyte": analyte, "matrix": "plasma"}
    ids["lloq"] = book.fact("lloq", 0.5, profile, unit="ng/mL")
    for time, value in ((1.0, 10.0), (2.0, 20.0), (4.0, 12.0)):
        ids[f"c{time:g}"] = book.fact("concentration", value, {**profile, "subject": "001"}, unit="ng/mL", time=time,
                                      time_unit="h", statistic="individual")
    return book, ids


def card(reader: LedgerView, study: str, *, coverage: Sequence[CoverageSummary] = (summary(),), overrides=(),
         dispositions=(), gaps: Sequence[SchemaGap] | None = None):
    requirements = requirement_status(reader, study, brief=None, matrix=None, dispositions=dispositions)
    checks = run_checks(reader, subject_type="study", subject=study, requirements=requirements.items,
                        parent_names=(synthetic.DRUG,))
    return scorecard(reader, subject_type="study", subject=study, coverage=coverage, requirements=requirements.items,
                     gaps=requirements.routing.gaps if gaps is None else gaps, checks=checks, overrides=overrides,
                     dispositions=dispositions)


def blockers(found) -> dict[str, Any]:
    return {b.code: b for b in found.blockers}


def test_a_clean_study_has_no_blocker_and_counts_its_values(tmp_path):
    book, ids = study_book(tmp_path)
    found = card(Reader(book.ws), ids["study"])
    assert found.blockers == () and found.label == "EXA-401" and found.silent_loss == 0
    assert found.values == 12 and found.by_level == {"prose": 12} and found.by_method == {"prose": 12}
    assert {i.req_id: i.status for i in found.requirements} == {"REQ-sys.demographics": "found",
                                                               "REQ-obs.bioanalytical": "found"}
    # a derived spread fact qualifies a value and is not one of its own
    book.fact("concentration", None, {"study": ids["study"], "analyte": ids["analyte"], "matrix": "plasma"},
              method="derived", spread=1.0, spread_kind="SD", derived_from=(ids["c1"],), compute="spread-1/sd_from_se")
    assert card(Reader(book.ws), ids["study"]).values == 12


@pytest.mark.parametrize(("coverage", "code"), [
    (summary(cells_silent=2, silent_loss=2), "SILENT_LOSS"),
    (summary(silent_loss=7, regions_unread=1), "SILENT_LOSS"),
    (summary(outside_items=3, outside_numeric=1), "OUTSIDE_NUMBERS"),
    (summary(values_unassigned=4), "UNASSIGNED_VALUES"),
])
def test_coverage_blockers(tmp_path, coverage, code):
    book, ids = study_book(tmp_path)
    found = card(Reader(book.ws), ids["study"], coverage=[summary(), coverage])
    assert set(blockers(found)) == {code} and found.coverage == (summary(), coverage)
    assert found.silent_loss == coverage.silent_loss


def test_a_schema_gap_blocks_and_no_override_clears_it(tmp_path):
    book, ids = study_book(tmp_path)
    book.fact("genotype", "CYP2D6 poor metabolizers", {"study": ids["study"]})
    reader = Reader(book.ws)
    found = card(reader, ids["study"])
    assert set(blockers(found)) == {"SCHEMA_GAP"} and "genotype" in blockers(found)["SCHEMA_GAP"].detail
    every = [Override(id=f"ov-{i}", subject=ids["study"], check_id=c.id, why="accepted", by="u-1", at=AT)
             for i, c in enumerate(found.checks, start=1)]
    gap_id = Override(id="ov-99", subject=ids["study"], check_id="genotype", why="no template, accepted", by="u-1", at=AT)
    assert "SCHEMA_GAP" in blockers(card(reader, ids["study"], overrides=[*every, gap_id]))


def test_a_failed_check_blocks_and_an_override_clears_it_and_leaves_it_listed(tmp_path):
    book, ids = study_book(tmp_path)
    negative = book.fact("concentration", -1.0, {"study": ids["study"], "analyte": ids["analyte"], "matrix": "plasma",
                                                 "subject": "001"}, unit="ng/mL", time=8.0, time_unit="h",
                         statistic="individual")
    reader = Reader(book.ws)
    found = card(reader, ids["study"])
    (failed,) = [c for c in found.checks if c.severity == "fail"]
    assert failed.code == "NEGATIVE_VALUE" and failed.values == (negative,)
    assert blockers(found)["CHECK_FAILED"].ids == (failed.id,) and found.overridden == ()
    elsewhere = Override(id="ov-1", subject="st-99", check_id=failed.id, why="another study's", by="u-1", at=AT)
    assert "CHECK_FAILED" in blockers(card(reader, ids["study"], overrides=[elsewhere]))
    override = Override(id="ov-2", subject=ids["study"], check_id=failed.id, why="a typo in the report; the SME accepts",
                        by="u-1", at=AT)
    cleared = card(reader, ids["study"], overrides=[override])
    assert cleared.blockers == () and cleared.overridden == (failed.id,) and failed in cleared.checks


def test_an_open_conflict_blocks_until_a_choice_and_an_override_does_not_clear_it(tmp_path):
    book, ids = study_book(tmp_path)
    other = book.fact("dose", 100.0, {"study": ids["study"]}, unit="mg")
    conflict = Conflict(id="cx-0123456789", entity=EntityRef(study=ids["study"]), field="dose", time=None,
                        values=(ids["dose"], other), kind="value")
    reader = Reader(book.ws, conflicts=[conflict])
    found = card(reader, ids["study"])
    (open_,) = [c for c in found.checks if c.code == "CONFLICT_OPEN"]
    assert found.conflicts == (conflict,) and blockers(found)["CHECK_FAILED"].ids == (open_.id,)
    override = Override(id="ov-1", subject=ids["study"], check_id=open_.id, why="either", by="u-1", at=AT)
    assert "CHECK_FAILED" in blockers(card(reader, ids["study"], overrides=[override]))     # a choice settles it
    assert card(Reader(book.ws), ids["study"]).blockers == ()       # once a choice leaves one value, no conflict is left


def test_a_missing_required_item_is_settled_by_a_disposition_not_an_override(tmp_path):
    plain = Book(tmp_path)
    study = plain.entity("study", "EXA-402")
    for field, value in (("route", "oral"), ("population", "healthy"), ("age_mean", 41.0)):
        plain.fact(field, value, {"study": study})
    reader = Reader(plain.ws)
    found = card(reader, study)
    undisposed = [c for c in found.checks if c.code == "REQUIRED_ITEM_UNDISPOSED"]
    assert [c.id for c in undisposed] == [result_id("REQUIRED_ITEM_UNDISPOSED", study, (), "REQ-obs.bioanalytical")]
    override = Override(id="ov-1", subject=study, check_id=undisposed[0].id, why="later", by="u-1", at=AT)
    assert undisposed[0].id in blockers(card(reader, study, overrides=[override]))["CHECK_FAILED"].ids
    disposition = RequirementDisposition(id="dp-1", subject=study, req_id="REQ-obs.bioanalytical",
                                         disposition="ask_client", why="asked in the request of 2026-11-13", by="u-1", at=AT)
    # the checks of a card computed before the disposition: the disposition clears the item's check
    before = card(reader, study)
    after = scorecard(reader, subject_type="study", subject=study, coverage=[summary()], requirements=before.requirements,
                      gaps=(), checks=before.checks, dispositions=[disposition])
    assert undisposed[0].id in after.overridden and "CHECK_FAILED" not in blockers(after)
    # recomputed with the disposition, the item is asked of the client and the check is gone
    settled = card(reader, study, dispositions=[disposition])
    assert {i.req_id: i.status for i in settled.requirements}["REQ-obs.bioanalytical"] == "ask_client"
    assert "REQUIRED_ITEM_UNDISPOSED" not in {c.code for c in settled.checks}


def test_a_missing_required_item_blocks_even_when_the_checks_ran_without_the_requirements(tmp_path):
    plain = Book(tmp_path)
    study = plain.entity("study", "EXA-403")
    for field, value in (("route", "oral"), ("population", "healthy")):
        plain.fact(field, value, {"study": study})
    reader = Reader(plain.ws)
    requirements = requirement_status(reader, study, brief=None, matrix=None).items
    missing = {i.req_id for i in requirements if i.status == "missing" and i.criticality == "REQUIRED"}
    assert missing == {"REQ-sys.demographics", "REQ-obs.bioanalytical"}
    bare = run_checks(reader, subject_type="study", subject=study, parent_names=(synthetic.DRUG,))   # no requirements
    assert "REQUIRED_ITEM_UNDISPOSED" not in {c.code for c in bare}
    found = scorecard(reader, subject_type="study", subject=study, coverage=[summary()], requirements=requirements,
                      gaps=(), checks=bare)
    added = {c.id for c in found.checks if c.code == "REQUIRED_ITEM_UNDISPOSED"}
    assert added == {result_id("REQUIRED_ITEM_UNDISPOSED", study, (), r) for r in missing}
    assert added <= set(blockers(found)["CHECK_FAILED"].ids)
    # the same ids as run_checks gives with the requirements, so a disposition settles them alike
    full = run_checks(reader, subject_type="study", subject=study, requirements=requirements, parent_names=(synthetic.DRUG,))
    assert {c.id for c in full if c.code == "REQUIRED_ITEM_UNDISPOSED"} == added
    assert [c.severity for c in found.checks] == sorted((c.severity for c in found.checks), key=("fail", "warn", "info").index)
    disposed = [RequirementDisposition(id=f"dp-{n}", subject=study, req_id=r, disposition="ask_client", why="asked",
                                       by="u-1", at=AT) for n, r in enumerate(sorted(missing), start=1)]
    settled = scorecard(reader, subject_type="study", subject=study, coverage=[summary()], requirements=requirements,
                        gaps=(), checks=bare, dispositions=disposed)
    assert added <= set(settled.overridden) and "CHECK_FAILED" not in blockers(settled)


def test_an_override_of_a_missing_dose_does_not_carry_to_new_data(tmp_path):
    plain = Book(tmp_path)
    study, analyte = plain.entity("study", "EXA-404"), plain.entity("analyte", synthetic.DRUG)
    for field, value in (("n", 12), ("route", "oral"), ("formulation", "ir_tablet"), ("intended_use", "model_building"),
                         ("population", "healthy"), ("age_mean", 30.0)):
        plain.fact(field, value, {"study": study})
    on = {"study": study, "analyte": analyte, "matrix": "plasma", "subject": "001"}
    plain.fact("lloq", 0.5, {"study": study, "analyte": analyte, "matrix": "plasma"}, unit="ng/mL")
    for time, value in ((1.0, 10.0), (2.0, 20.0)):
        plain.fact("concentration", value, on, unit="ng/mL", time=time, time_unit="h", statistic="individual")
    first = card(Reader(plain.ws), study)
    failed = [c for c in first.checks if c.severity == "fail"]
    assert {c.code for c in failed} == {"DOSE_MISSING", "LANDING_FIELD_MISSING"} and all(c.values == () for c in failed)
    overrides = [Override(id=f"ov-{n}", subject=study, check_id=c.id, why="the dose is in the protocol", by="u-1", at=AT)
                 for n, c in enumerate(failed, start=1)]
    assert "CHECK_FAILED" not in blockers(card(Reader(plain.ws), study, overrides=overrides))
    plain.fact("concentration", 12.0, {**on, "subject": "002"}, unit="ng/mL", time=1.0, time_unit="h", statistic="individual")
    later = card(Reader(plain.ws), study, overrides=overrides)         # a later delivery adds a subject
    again = [c for c in later.checks if c.severity == "fail"]
    assert {c.code for c in again} == {c.code for c in failed} and not {c.id for c in again} & {c.id for c in failed}
    assert set(blockers(later)["CHECK_FAILED"].ids) == {c.id for c in again}       # the override made for other values


def test_an_unconfirmed_or_ambiguous_link_blocks(tmp_path):
    book, ids = study_book(tmp_path)
    links = [PendingLink(id="pl-1", link_fact="f-1", study=ids["study"], file_sha256="a" * 64, values=4, candidates=(),
                         state="unconfirmed"),
             PendingLink(id="pl-2", link_fact=None, study=ids["study"], file_sha256="b" * 64, values=2,
                         candidates=(ids["study"], "st-77"), state="ambiguous"),
             PendingLink(id="pl-3", link_fact="f-2", study=ids["study"], file_sha256="c" * 64, values=1, candidates=(),
                         state="refused")]
    found = card(Reader(book.ws, links=links), ids["study"])
    assert found.links == tuple(links) and blockers(found)["LINK_UNCONFIRMED"].ids == ("pl-1", "pl-2")


def test_a_product_and_the_compound_get_scorecards_like_a_study(tmp_path):
    book = Book(tmp_path)
    product = book.entity("product", "Exampleamide 50 mg tablet")
    for time, value in ((15, 61.0), (30, 88.0)):
        book.fact("percent_dissolved", value, {"product": product}, method="cell", mapping=NEW, unit="%", time=time,
                  time_unit="min", statistic="arithmetic_mean", n=12, conditions={"apparatus": "USP 2", "medium": "0.1 N HCl"})
    logp = book.fact("phys.logp", 2.1, {}, method="cell", mapping=NEW)
    reader = Reader(book.ws)
    items = product_requirements(reader, product, brief=None, matrix=None)
    checks = run_checks(reader, subject_type="product", subject=product, requirements=items)
    found = scorecard(reader, subject_type="product", subject=product, coverage=[summary(silent_loss=1, cells_silent=1)],
                      requirements=items, gaps=(), checks=checks)
    assert found.label == "Exampleamide 50 mg tablet" and found.values == 2 and found.by_level == {"new_mapping": 2}
    assert {"SILENT_LOSS", "CHECK_FAILED"} == set(blockers(found)) and found.links == ()
    assert "MAPPING_NOT_APPROVED" in {c.code for c in checks if c.id in blockers(found)["CHECK_FAILED"].ids}
    compound_checks = run_checks(reader, subject_type="compound", subject=COMPOUND)
    compound = scorecard(reader, subject_type="compound", subject=COMPOUND, coverage=[summary()], requirements=(), gaps=(),
                         checks=compound_checks)
    assert (compound.subject, compound.label, compound.values) == (COMPOUND, COMPOUND, 1)
    assert [c.values for c in compound.checks if c.code == "MAPPING_NOT_APPROVED"] == [(logp,)]
    override = Override(id="ov-1", subject=COMPOUND, check_id=compound_checks[0].id, why="approved on paper", by="u-1", at=AT)
    assert scorecard(reader, subject_type="compound", subject=COMPOUND, coverage=[summary()], requirements=(), gaps=(),
                     checks=compound_checks, overrides=[override]).blockers == ()


def test_the_truth_gives_a_scorecard_for_every_subject(tmp_path):
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    write_truth(ws, synthetic.delivery())
    reader = Reader(ws)
    for study in reader.entities("study"):
        requirements = requirement_status(reader, study.id, brief=None, matrix=None)
        checks = run_checks(reader, subject_type="study", subject=study.id, requirements=requirements.items)
        found = scorecard(reader, subject_type="study", subject=study.id, coverage=[summary()],
                          requirements=requirements.items, gaps=requirements.routing.gaps, checks=checks)
        assert found.label == study.label and found.values == len(reader.values(study=study.id))
        assert "SCHEMA_GAP" in blockers(found)                 # no file of the delivery states a route
    for product in reader.entities("product"):
        found = scorecard(reader, subject_type="product", subject=product.id, coverage=[], requirements=(), gaps=(),
                          checks=())
        assert found.blockers == () and found.values > 0
