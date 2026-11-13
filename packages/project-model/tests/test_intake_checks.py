"""The validity checks (plan G5, contracts §6.4): one test per code of CHECKS, each code's severity from the rules file,
units kept as written and only reported, stable check ids, and every threshold read from the rules file."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence
from typing import Any

import pytest

from modeler_intake import synthetic
from modeler_intake.anchors import ID_PATTERNS, anchor_text
from modeler_intake.document_reading import name_key
from modeler_intake.mapping_spec import MappingSpec
from modeler_project.intake_checks import CHECKS, result_id, run_checks
from modeler_project.intake_fixtures import write_truth
from modeler_project.intake_records import CheckResult, MappingDecision, MappingEntry, RequirementStatus
from modeler_project.intake_rules import IntakeRules, rules
from modeler_project.intake_store import IntakeStore
from modeler_project.ledger_models import Conflict, Entity, EntityRef, Fact, MappingUse, PendingLink
from modeler_project.ledger_view import LedgerView
from modeler_project.store import FileProjectStore
from modeler_project.workspace import Workspace

pytestmark = pytest.mark.req("T-47", "T-42")

AT = "2026-11-13T09:00:00.000Z"
SHA = hashlib.sha256(b"Exampleamide: a made-up delivery for the checks").hexdigest()
APPROVED = MappingUse(mapping_id="mp-00000000000a", version=1)
_PREFIX = {"study": "st", "arm": "arm", "product": "pr", "batch": "ba", "analyte": "an"}
_TABLE = ("cell", "pdf_table", "docx_table")
RULE_KEYS = ("checks.", "ledger.", "landing.", "routing.", "datasets.NCA_TOLERANCE", "dissolution_similarity.")


class Reader(LedgerView):
    """The read side with a small fake for what D4's ledger computes: conflicts and pending links."""

    def __init__(self, ws: Workspace, conflicts: Sequence[Conflict] = (), links: Sequence[PendingLink] = ()):
        super().__init__(ws)
        self._conflicts, self._links = list(conflicts), list(links)

    def conflicts(self, *, study: str | None = None, product: str | None = None) -> list[Conflict]:
        return [c for c in self._conflicts
                if (study is None or c.entity.study == study) and (product is None or c.entity.product == product)]

    def pending_links(self, *, study: str | None = None) -> list[PendingLink]:
        return [link for link in self._links if study is None or link.study == study]


class Book:
    """A small ledger of one made-up file, written through the store as the ledger writes it."""

    def __init__(self, ws: Workspace):
        self.ws, self.store, self.cells = ws, IntakeStore(ws), 0
        self.store.mappings.append("decision", MappingDecision(mapping_id=APPROVED.mapping_id, version=1,
                                                               status="approved", by="u-1", at=AT).model_dump(mode="json"))

    def anchor(self) -> str:
        self.cells += 1
        return anchor_text(SHA, "workbook", "1.0", f"s:'Data'!A{self.cells}")

    def entity(self, type: str, label: str, parent: str | None = None) -> str:
        source = self.anchor()
        line = self.store.entities.append("entity", lambda seq: Entity(
            id=f"{_PREFIX[type]}-{seq}", type=type, label=label, key=name_key(label), parent=parent, source=source,  # type: ignore[arg-type]
            by="code", at=AT).model_dump(mode="json"))
        return line.body["id"]

    def fact(self, field: str, value: Any, *, entity: dict[str, str] | None = None, method: str = "cell",
             mapping: MappingUse | None = APPROVED, **kw: Any) -> str:
        anchor = None if method in ("derived", "person") else self.anchor()
        ref = EntityRef(**(entity or {}))
        line = self.store.facts.append("fact", lambda seq: Fact(
            id=f"f-{seq}", delivery="dl-1", entity=ref, field=field, value=value, anchor=anchor, method=method,  # type: ignore[arg-type]
            mapping=mapping if method in _TABLE else None, verbatim=kw.pop("verbatim", str(value)), by="code", at=AT,
            **kw).model_dump(mode="json"))
        return line.body["id"]

    def reader(self, **kw: Any) -> Reader:
        return Reader(self.ws, **kw)


@pytest.fixture
def book(tmp_path) -> Book:
    return Book(Workspace(FileProjectStore(tmp_path), "t1", "p1"))


# --- a study and a product that pass every check ---------------------------------------------------------------------

_INDIVIDUAL = ((0.5, 4.0), (1.0, 10.0), (2.0, 20.0), (4.0, 15.0), (8.0, 5.0))
_MEAN = ((0.5, 4.2, 1.1), (1.0, 10.4, 2.0), (2.0, 19.8, 3.1), (4.0, 14.6, 2.2), (8.0, 5.3, 0.9))


def clean(b: Book, *, skip: Sequence[str] = ()) -> dict[str, str]:
    """A study whose every check passes: its record, its LLOQ, an individual profile and a mean profile."""
    ids = {"study": b.entity("study", "EXA-201"), "analyte": b.entity("analyte", synthetic.DRUG)}
    on = {"study": ids["study"]}
    scalar: dict[str, tuple[Any, dict[str, Any]]] = {
        "dose": (50.0, {"unit": "mg"}), "n": (12, {}), "route": ("oral", {}), "formulation": ("ir_tablet", {}),
        "intended_use": ("model_building", {}), "salt_or_base": ("base", {}), "population": ("healthy", {}),
        "age_mean": (31.5, {})}
    for name, (value, kw) in scalar.items():
        if name not in skip:
            ids[name] = b.fact(name, value, entity=on, **kw)
    if "lloq" not in skip:
        ids["lloq"] = b.fact("lloq", 0.5, unit="ng/mL", entity=profile(ids))
    if "individual" not in skip:
        for time, value in _INDIVIDUAL:
            b.fact("concentration", value, unit="ng/mL", time=time, time_unit="h", statistic="individual",
                   entity={**profile(ids), "subject": "001"})
    if "mean" not in skip:
        for time, value, sd in _MEAN:
            b.fact("concentration", value, unit="ng/mL", time=time, time_unit="h", statistic="arithmetic_mean", spread=sd,
                   spread_kind="SD", n=12, entity=profile(ids))
    return ids


def profile(ids: dict[str, str], **more: str) -> dict[str, str]:
    return {"study": ids["study"], "analyte": ids["analyte"], "matrix": "plasma", **more}


_METHOD = {"apparatus": "USP 2 paddle", "medium": "0.1 N HCl", "ph": "1.2", "rpm": "50", "volume_ml": "900",
           "temperature_c": "37"}


def clean_product(b: Book, *, conditions: dict[str, str] | None = None, batch: str = "L2301",
                  values: Sequence[float] = (35.0, 62.0, 81.0, 94.0)) -> dict[str, str]:
    ids = {"product": b.entity("product", "Exampleamide 50 mg tablet")}
    ids["batch"] = b.entity("batch", batch, ids["product"])
    for time, value in zip((5, 10, 15, 30), values, strict=True):
        b.fact("percent_dissolved", value, unit="%", time=time, time_unit="min", statistic="arithmetic_mean",
               spread=2.0, spread_kind="SD", n=12, conditions=dict(_METHOD if conditions is None else conditions),
               entity={"product": ids["product"], "batch": ids["batch"]})
    return ids


def checks(reader: LedgerView, subject_type: str, subject: str, **kw: Any) -> tuple[CheckResult, ...]:
    kw.setdefault("parent_names", (synthetic.DRUG,))
    return run_checks(reader, subject_type=subject_type, subject=subject, **kw)  # type: ignore[arg-type]


def codes(results: Sequence[CheckResult]) -> set[str]:
    return {r.code for r in results}


def test_the_checks_are_exactly_the_codes_of_the_rules_file():
    severity = rules().checks.severity
    listed = [code for level in ("fail", "warn", "info") for code in severity[level]]
    assert set(CHECKS) == set(listed) and len(CHECKS) == len(listed) == len(set(CHECKS))
    assert set(CASES) == set(CHECKS), "one test case per code"


def test_a_clean_study_and_a_clean_product_pass_every_check(book):
    ids = clean(book)
    product = clean_product(book)
    reader = book.reader()
    assert checks(reader, "study", ids["study"], mol_weight=300.0) == ()
    assert checks(reader, "product", product["product"]) == ()
    assert checks(reader, "compound", "compound", mol_weight=300.0) == ()


# --- one case per code -----------------------------------------------------------------------------------------------

Case = Callable[[Book], tuple[str, str, dict[str, Any]]]


def _study(ids: dict[str, str], **kw: Any) -> tuple[str, str, dict[str, Any]]:
    return "study", ids["study"], kw


def _value(b: Book, ids: dict[str, str], value: Any, time: float = 12.0, **kw: Any) -> str:
    entity = kw.pop("entity", None) or {**profile(ids), "subject": "001"}
    kw.setdefault("unit", "ng/mL")
    kw.setdefault("statistic", "individual")
    return b.fact("concentration", value, time=time, time_unit=kw.pop("time_unit", "h"), entity=entity, **kw)


def _one_lloq(b):
    ids = clean(b)
    b.fact("lloq", 1.0, unit="ng/mL", entity=profile(ids))
    return _study(ids)


def _blq_without_lloq(b):
    ids = clean(b, skip=("lloq",))
    _value(b, ids, None, 0.0, censored=True, verbatim="BLQ")
    return _study(ids)


def _lloq_unit_differs(b):
    ids = clean(b, skip=("lloq",))
    b.fact("lloq", 0.5, unit="µg/L", entity=profile(ids))
    return _study(ids)


def _duplicate_time(b):
    ids = clean(b)
    _value(b, ids, 10.5, 60.0, time_unit="min")             # 60 min is the 1 h point of the same series
    return _study(ids)


def _unit_missing(b):
    ids = clean(b)
    _value(b, ids, 3.0, unit=None)
    return _study(ids)


def _unit_not_in_tables(b):
    ids = clean(b)
    _value(b, ids, 3.0, unit="ng/dL")
    return _study(ids)


def _matrix_not_plasma(b):
    ids = clean(b)
    _value(b, ids, 3.0, entity=profile(ids, matrix="whole blood", subject="001"))
    return _study(ids)


def _analyte_missing(b):
    ids = clean(b)
    _value(b, ids, 3.0, entity={"study": ids["study"], "matrix": "plasma", "subject": "002"})
    return _study(ids)


def _matrix_missing(b):
    ids = clean(b, skip=("lloq",))
    b.fact("lloq", 0.5, unit="ng/mL", entity={"study": ids["study"], "analyte": ids["analyte"]})
    _value(b, ids, 3.0, entity={"study": ids["study"], "analyte": ids["analyte"], "subject": "002"})
    return _study(ids)


def _dose_missing(b):
    return _study(clean(b, skip=("dose",)))


def _infusion_time_missing(b):
    ids = clean(b, skip=("route", "formulation"))
    b.fact("route", "iv_infusion", entity={"study": ids["study"]})
    return _study(ids)


def _landing_field_missing(b):
    return _study(clean(b, skip=("intended_use",)))


def _statistic_missing(b):
    ids = clean(b)
    _value(b, ids, 3.0, statistic=None, entity=profile(ids))
    return _study(ids)


def _spread_kind_missing(b):
    ids = clean(b)
    _value(b, ids, 3.2, statistic="arithmetic_mean", spread=0.4, n=12, entity=profile(ids))
    return _study(ids)


def _time_reference_unstated(b):
    ids = clean(b)
    b.fact("design", "MD", entity={"study": ids["study"]})
    return _study(ids)


def _negative_value(b):
    ids = clean(b)
    _value(b, ids, -1.0)
    return _study(ids)


def _above_range(b):
    ids = clean(b)
    _value(b, ids, None, uloq=1000.0, verbatim=">1000")
    return _study(ids)


def _dissolution_method_incomplete(b):
    ids = clean_product(b, conditions={"medium": "0.1 N HCl"})
    return "product", ids["product"], {}


def _dissolution_out_of_range(b):
    ids = clean_product(b, values=(35.0, 62.0, 81.0, 120.0))
    return "product", ids["product"], {}


def _conflict_open(b):
    ids = clean(b)
    other = b.fact("dose", 100.0, unit="mg", entity={"study": ids["study"]})
    conflict = Conflict(id="cx-0123456789", entity=EntityRef(study=ids["study"]), field="dose", time=None,
                        values=(ids["dose"], other), kind="value")
    return _study(ids, reader={"conflicts": [conflict]})


def _required_item_undisposed(b):
    ids = clean(b)
    item = RequirementStatus(req_id="REQ-fe.meal", template="req-app-food-effect", label="Meal composition of each fed study",
                             scope="study", subject=ids["study"], criticality="REQUIRED", applies="yes", status="missing")
    return _study(ids, requirements=[item])


def _mapping_not_approved(b):
    ids = clean(b)
    _value(b, ids, 3.0, mapping=MappingUse(mapping_id="mp-00000000000b", version=1))
    return _study(ids)


def _mw_inconsistent(b):
    ids = clean(b)
    b.fact("molecular_weight", 330.0, unit="g/mol", entity={"study": ids["study"], "analyte": ids["analyte"]})
    return _study(ids, mol_weight=300.0)


def _spread_not_converted(b):
    ids = clean(b, skip=("mean",))
    for time, value, se in _MEAN:                          # an SE with no n at any point: no SD can be derived
        _value(b, ids, value, time, statistic="arithmetic_mean", spread=se, spread_kind="SE", entity=profile(ids))
    return _study(ids)


def _geometric_spread_verbatim(b):
    ids = clean(b, skip=("mean",))
    for time, value, sd in _MEAN:                          # a plain "SD" beside a geometric mean is ambiguous (§11.5)
        _value(b, ids, value, time, statistic="geometric_mean", spread=sd, spread_kind="SD", n=12, entity=profile(ids))
    return _study(ids)


def _n_missing(b):
    ids = clean(b, skip=("mean", "n"))
    for time, value, sd in _MEAN:
        _value(b, ids, value, time, statistic="arithmetic_mean", spread=sd, spread_kind="SD", entity=profile(ids))
    return _study(ids)


def _nca_mismatch(b):
    ids = clean(b)
    b.fact("pk.Cmax", 100.0, unit="ng/mL", statistic="arithmetic_mean", entity=profile(ids))
    return _study(ids)


def _dose_basis_unstated(b):
    return _study(clean(b, skip=("salt_or_base",)))


def _dose_not_multiple_of_strength(b):
    ids = clean(b, skip=("dose",))
    product = b.entity("product", "Exampleamide 50 mg tablet")
    b.fact("strength_mg", 50.0, unit="mg", entity={"product": product})
    b.fact("dose", 75.0, unit="mg", entity={"study": ids["study"], "product": product})
    return _study(ids)


def _crossover_period_missing(b):
    ids = clean(b)
    b.fact("crossover", "yes", entity={"study": ids["study"]})
    return _study(ids)


def _dissolution_lot_not_clinical(b):
    ids = clean_product(b, batch="L2302")
    clinical = b.entity("batch", "L2301", ids["product"])
    study = b.entity("study", "EXA-301")
    b.fact("dose", 50.0, unit="mg", entity={"study": study, "product": ids["product"], "batch": clinical})
    return "product", ids["product"], {}


def _dissolution_runs_not_keyed(b):
    ids = clean_product(b)
    for time, value in ((5, 30.0), (10, 58.0), (15, 79.0), (30, 92.0)):
        b.fact("percent_dissolved", value, unit="%", time=time, time_unit="min", statistic="arithmetic_mean", spread=2.0,
               spread_kind="SD", n=12, conditions={**_METHOD, "temperature_c": "25"},
               entity={"product": ids["product"], "batch": ids["batch"]})
    return "product", ids["product"], {}


def _composition_sum(b):
    ids = clean_product(b)
    for component, amount in (("Exampleamide", 30.0), ("lactose", 60.0)):
        b.fact("composition.amount", amount, unit="%", conditions={"component": component}, entity={"product": ids["product"]})
    return "product", ids["product"], {}


def _times_not_increasing(b):
    ids = clean(b, skip=("individual",))
    for time, value in ((0.5, 4.0), (2.0, 20.0), (1.0, 10.0), (4.0, 15.0)):
        _value(b, ids, value, time)
    return _study(ids)


def _excretion_not_landed(b):
    ids = clean(b)
    b.fact("excretion.amount", 2.1, unit="mg", conditions={"interval_start_h": "0", "interval_end_h": "4"},
           entity={"study": ids["study"], "analyte": ids["analyte"], "matrix": "urine"})
    return _study(ids)


def _occasions_not_landed(b):
    ids = clean(b)
    for occasion in ("Day 1", "Day 14"):
        _value(b, ids, 6.0, 1.0, entity=profile(ids, subject="003", occasion=occasion))
    return _study(ids)


def _zero_after_quantifiable(b):
    ids = clean(b)
    _value(b, ids, 5.0, 1.0, entity=profile(ids, subject="002"))
    _value(b, ids, 0.0, 2.0, entity=profile(ids, subject="002"))
    return _study(ids)


def _population_covariate_missing(b):
    ids = clean(b, skip=("age_mean",))
    b.fact("special_population", "pediatric", entity={"study": ids["study"]})
    return _study(ids)


def _marked_value(b):
    ids = clean(b)
    _value(b, ids, 12.3, verbatim="12.3*")
    return _study(ids)


def _analyte_not_parent(b):
    ids = clean(b)
    metabolite = b.entity("analyte", synthetic.METABOLITE)
    b.fact("lloq", 0.2, unit="ng/mL", entity={"study": ids["study"], "analyte": metabolite, "matrix": "plasma"})
    _value(b, ids, 1.1, entity={"study": ids["study"], "analyte": metabolite, "matrix": "plasma", "subject": "001"})
    return _study(ids)


def _blq_present(b):
    ids = clean(b)
    _value(b, ids, None, 0.0, censored=True, lloq=0.5, lloq_unit="ng/mL", verbatim="<0.5")
    return _study(ids)


def _duplicate_table_and_plot(b):
    ids = clean(b)
    _value(b, ids, 10.2, 1.0, method="digitized", entity=profile(ids, subject="004"))
    return _study(ids)


def _unit_not_checked(b):
    ids = clean(b)
    b.fact("pk.AUC_last", 120.0, unit="ng*h/mL", statistic="arithmetic_mean", entity=profile(ids))
    return _study(ids)


CASES: dict[str, Case] = {
    "ONE_LLOQ_PER_PROFILE": _one_lloq, "BLQ_WITHOUT_LLOQ": _blq_without_lloq, "LLOQ_UNIT_DIFFERS": _lloq_unit_differs,
    "DUPLICATE_TIME": _duplicate_time, "UNIT_MISSING": _unit_missing, "UNIT_NOT_IN_TABLES": _unit_not_in_tables,
    "MATRIX_NOT_PLASMA": _matrix_not_plasma, "ANALYTE_MISSING": _analyte_missing, "MATRIX_MISSING": _matrix_missing,
    "DOSE_MISSING": _dose_missing, "INFUSION_TIME_MISSING": _infusion_time_missing,
    "LANDING_FIELD_MISSING": _landing_field_missing, "STATISTIC_MISSING": _statistic_missing,
    "SPREAD_KIND_MISSING": _spread_kind_missing, "TIME_REFERENCE_UNSTATED": _time_reference_unstated,
    "NEGATIVE_VALUE": _negative_value, "ABOVE_RANGE": _above_range,
    "DISSOLUTION_METHOD_INCOMPLETE": _dissolution_method_incomplete, "DISSOLUTION_OUT_OF_RANGE": _dissolution_out_of_range,
    "CONFLICT_OPEN": _conflict_open, "REQUIRED_ITEM_UNDISPOSED": _required_item_undisposed,
    "MAPPING_NOT_APPROVED": _mapping_not_approved, "MW_INCONSISTENT": _mw_inconsistent,
    "SPREAD_NOT_CONVERTED": _spread_not_converted, "GEOMETRIC_SPREAD_VERBATIM": _geometric_spread_verbatim,
    "N_MISSING": _n_missing, "NCA_MISMATCH": _nca_mismatch, "DOSE_BASIS_UNSTATED": _dose_basis_unstated,
    "DOSE_NOT_MULTIPLE_OF_STRENGTH": _dose_not_multiple_of_strength, "CROSSOVER_PERIOD_MISSING": _crossover_period_missing,
    "DISSOLUTION_LOT_NOT_CLINICAL": _dissolution_lot_not_clinical,
    "DISSOLUTION_RUNS_NOT_KEYED": _dissolution_runs_not_keyed, "COMPOSITION_SUM": _composition_sum,
    "TIMES_NOT_INCREASING": _times_not_increasing, "EXCRETION_NOT_LANDED": _excretion_not_landed,
    "OCCASIONS_NOT_LANDED": _occasions_not_landed, "ZERO_AFTER_QUANTIFIABLE": _zero_after_quantifiable,
    "POPULATION_COVARIATE_MISSING": _population_covariate_missing, "MARKED_VALUE": _marked_value,
    "ANALYTE_NOT_PARENT": _analyte_not_parent, "BLQ_PRESENT": _blq_present,
    "DUPLICATE_TABLE_AND_PLOT": _duplicate_table_and_plot, "UNIT_NOT_CHECKED": _unit_not_checked,
}
_LEVEL = {code: level for level, found in rules().checks.severity.items() for code in found}


@pytest.mark.parametrize("code", CHECKS)
def test_each_check_finds_its_case_at_the_rules_files_severity(book, code):
    subject_type, subject, kw = CASES[code](book)
    reader = book.reader(**kw.pop("reader", {}))
    head = book.store.facts.head()
    results = checks(reader, subject_type, subject, **kw)
    found = [r for r in results if r.code == code]
    assert found, (code, codes(results))
    for result in found:
        assert result.severity == _LEVEL[code] and result.subject == subject and result.subject_type == subject_type
        assert ID_PATTERNS["check"].fullmatch(result.id) and result.rule.startswith(RULE_KEYS)
        assert all(reader.value(v) is not None for v in result.values) and result.message
    assert book.store.facts.head() == head                   # a check writes nothing
    severities = [r.severity for r in results]
    assert severities == sorted(severities, key=("fail", "warn", "info").index)      # failures first


def test_blood_or_serum_fails_matrix_not_plasma(book):
    ids = clean(book)
    blood = _value(book, ids, 3.0, entity=profile(ids, matrix="whole blood", subject="001"))
    serum = _value(book, ids, 4.0, entity=profile(ids, matrix="serum", subject="001"))
    found = {r.values: r for r in checks(book.reader(), "study", ids["study"]) if r.code == "MATRIX_NOT_PLASMA"}
    assert set(found) == {(blood,), (serum,)} and {r.severity for r in found.values()} == {"fail"}


def test_only_a_matrix_fact_gives_a_study_its_matrix(book):
    """§4.5: a value with no matrix label takes its study's single active `matrix` fact. An LLOQ labelled plasma says
    which profile it is for; it does not give a matrix to concentrations that state none (the landing would find none)."""
    study, analyte = book.entity("study", "EXA-501"), book.entity("analyte", synthetic.DRUG)
    book.fact("lloq", 0.5, unit="ng/mL", entity={"study": study, "analyte": analyte, "matrix": "plasma"})
    for time, value in ((0.5, 4.0), (1.0, 10.0), (2.0, 20.0)):
        book.fact("concentration", value, unit="ng/mL", time=time, time_unit="h", statistic="individual",
                  entity={"study": study, "analyte": analyte, "subject": "001"})
    assert "MATRIX_MISSING" in codes(checks(book.reader(), "study", study))
    book.fact("matrix", "plasma", entity={"study": study})
    found = codes(checks(book.reader(), "study", study))
    assert "MATRIX_MISSING" not in found and "MATRIX_NOT_PLASMA" not in found


def test_a_concentration_unit_outside_the_tables_fails_and_the_value_is_kept_as_written(book):
    ids = clean(book)
    odd = _value(book, ids, 3.0, unit="ng/dL")
    reader = book.reader()
    (found,) = [r for r in checks(reader, "study", ids["study"]) if r.code == "UNIT_NOT_IN_TABLES"]
    assert found.values == (odd,) and found.severity == "fail" and "ng/dL" in found.message
    kept = reader.value(odd)
    assert (kept.value, kept.unit, kept.status) == (3.0, "ng/dL", "proposed")       # nothing renamed or refused


@pytest.mark.parametrize("unit", ["mg", "g", "µg", "ug", "mg/kg"])
def test_a_dose_in_mg_g_ug_or_mg_per_kg_passes_the_unit_checks(book, unit):
    ids = clean(book, skip=("dose",))
    dose = book.fact("dose", 0.5 if unit == "g" else 50.0, unit=unit, entity={"study": ids["study"]})
    results = checks(book.reader(), "study", ids["study"])
    assert not [r for r in results if dose in r.values and r.code.startswith("UNIT_")]
    assert "DOSE_MISSING" not in codes(results)


def test_an_rpm_a_particle_size_and_an_auc_unit_are_not_checked_never_failed(book):
    ids = clean(book)
    product = clean_product(book)
    rpm = book.fact("rpm", 50.0, unit="rpm", entity={"product": product["product"]})
    size = book.fact("particle_size_d50_um", 12.5, unit="µm", entity={"product": product["product"]})
    auc = book.fact("pk.AUC_last", 120.0, unit="ng*h/mL", statistic="arithmetic_mean", entity=profile(ids))
    reader = book.reader()
    results = checks(reader, "product", product["product"]) + checks(reader, "study", ids["study"])
    unchecked = {v: r for r in results if r.code == "UNIT_NOT_CHECKED" for v in r.values}
    assert {rpm, size, auc} <= set(unchecked) and {unchecked[v].severity for v in (rpm, size, auc)} == {"info"}
    assert not [r for r in results if r.severity == "fail" and {rpm, size, auc} & set(r.values)]


def test_a_check_id_is_stable_across_runs_and_changes_with_its_values(book):
    ids = clean(book)
    _value(book, ids, -1.0)
    first = {r.code: r.id for r in checks(book.reader(), "study", ids["study"])}
    again = {r.code: r.id for r in checks(book.reader(), "study", ids["study"])}
    assert first == again and first["NEGATIVE_VALUE"].startswith("ck-")
    _value(book, ids, -2.0, 24.0)
    after = {r.code: r.id for r in checks(book.reader(), "study", ids["study"])}
    assert after["NEGATIVE_VALUE"] != first["NEGATIVE_VALUE"]
    assert result_id("NEGATIVE_VALUE", "st-1", ["f-2", "f-1"], "x") == result_id("NEGATIVE_VALUE", "st-1", ["f-1", "f-2"], "x")


def test_duplicate_time_reads_the_resolution_as_at_most_from_the_first_time_of_a_cluster(book):
    """The one meaning of `ledger.time_resolution_min` the ledger's conflicts use too: at most that far apart, measured
    from the first time of the cluster, with no chaining through neighbours."""
    ids = clean(book, skip=("individual",))
    at = {t: _value(book, ids, 5.0, t, time_unit="min", entity=profile(ids, subject="002")) for t in (0.0, 1.0, 30.0)}
    (found,) = [r for r in checks(book.reader(), "study", ids["study"]) if r.code == "DUPLICATE_TIME"]
    assert set(found.values) == {at[0.0], at[1.0]}                      # exactly the resolution apart: one time
    chain = clean(book, skip=("individual",))
    times = {t: _value(book, chain, 5.0, t, time_unit="min", entity=profile(chain, subject="003")) for t in (0.0, 0.6, 1.2)}
    (found,) = [r for r in checks(book.reader(), "study", chain["study"]) if r.code == "DUPLICATE_TIME"]
    assert set(found.values) == {times[0.0], times[0.6]}                # 1.2 is more than 1 min after 0: a time of its own


def test_a_reported_pk_parameter_is_compared_with_the_one_mean_profile_it_reports(book):
    ids = clean(book, skip=("mean",))
    test = book.entity("product", "Exampleamide test tablet")
    reference = book.entity("product", "Exampleamide reference tablet")
    for product, scale in ((test, 1.0), (reference, 2.0)):              # a crossover arm: test and reference
        for time, value, sd in _MEAN:
            _value(book, ids, value * scale, time, statistic="arithmetic_mean", spread=sd, spread_kind="SD", n=12,
                   entity=profile(ids, product=product))
    book.fact("pk.Cmax", 39.6, unit="ng/mL", statistic="arithmetic_mean", entity=profile(ids, product=reference))
    book.fact("pk.Cmax", 19.8, unit="ng/mL", statistic="arithmetic_mean", entity=profile(ids, product=test))
    assert "NCA_MISMATCH" not in codes(checks(book.reader(), "study", ids["study"]))
    wrong = book.fact("pk.Cmax", 39.6, unit="ng/mL", statistic="arithmetic_mean", entity=profile(ids, product=test))
    (found,) = [r for r in checks(book.reader(), "study", ids["study"]) if r.code == "NCA_MISMATCH"]
    assert wrong in found.values and len(found.values) == 1 + len(_MEAN)      # the report and the profile it reports
    # a report that names no product fits both profiles: not compared, and said so
    loose = clean(book, skip=("mean",))
    for product, scale in ((test, 1.0), (reference, 2.0)):
        for time, value, sd in _MEAN:
            _value(book, loose, value * scale, time, statistic="arithmetic_mean", spread=sd, spread_kind="SD", n=12,
                   entity=profile(loose, product=product))
    unnamed = book.fact("pk.Cmax", 19.8, unit="ng/mL", statistic="arithmetic_mean", entity=profile(loose))
    (found,) = [r for r in checks(book.reader(), "study", loose["study"]) if r.code == "NCA_MISMATCH"]
    assert found.values == (unnamed,) and "not compared" in found.message
    # a report of another statistic is never compared with an arithmetic mean profile
    other = clean(book)
    book.fact("pk.Cmax", 100.0, unit="ng/mL", statistic="geometric_mean", entity=profile(other))
    assert "NCA_MISMATCH" not in codes(checks(book.reader(), "study", other["study"]))


def test_dissolution_runs_written_alike_share_a_key_and_only_conditions_that_differ_are_named(book):
    ids = clean_product(book)
    for time, value in zip((5, 10, 15, 30), (35.0, 62.0, 81.0, 94.0), strict=True):    # rpm "50.0", temperature "37.0"
        book.fact("percent_dissolved", value, unit="%", time=time, time_unit="min", statistic="arithmetic_mean",
                  spread=2.0, spread_kind="SD", n=12, conditions={**_METHOD, "rpm": "50.0", "temperature_c": "37.0"},
                  entity={"product": ids["product"], "batch": ids["batch"]})
    assert "DISSOLUTION_RUNS_NOT_KEYED" not in codes(checks(book.reader(), "product", ids["product"]))
    for time, value in ((5, 30.0), (10, 58.0), (15, 79.0), (30, 92.0)):
        book.fact("percent_dissolved", value, unit="%", time=time, time_unit="min", statistic="arithmetic_mean",
                  spread=2.0, spread_kind="SD", n=12, conditions={**_METHOD, "temperature_c": "25", "surfactant": "none"},
                  entity={"product": ids["product"], "batch": ids["batch"]})
    (found,) = [r for r in checks(book.reader(), "product", ids["product"]) if r.code == "DISSOLUTION_RUNS_NOT_KEYED"]
    assert "differ in surfactant, temperature_c," in found.message


def test_a_check_about_something_missing_changes_its_id_when_new_data_arrives(book):
    ids = clean(book, skip=("dose", "intended_use"))
    book.fact("design", "MD", entity={"study": ids["study"]})
    product = clean_product(book, conditions={"medium": "0.1 N HCl"})
    watched = ("DOSE_MISSING", "LANDING_FIELD_MISSING", "TIME_REFERENCE_UNSTATED")

    def found() -> dict[str, str]:
        reader = book.reader()
        study = {r.code: r.id for r in checks(reader, "study", ids["study"]) if r.code in watched}
        return {**study, **{r.code: r.id for r in checks(reader, "product", product["product"])
                            if r.code == "DISSOLUTION_METHOD_INCOMPLETE"}}

    before = found()
    assert set(before) == {*watched, "DISSOLUTION_METHOD_INCOMPLETE"} and before == found()   # stable while nothing changes
    for time, value in ((0.0, 30.0), (1.0, 45.0), (2.0, 40.0)):        # a day-7 profile of a later delivery
        _value(book, ids, value, time, entity=profile(ids, subject="001", occasion="Day 7"))
    book.fact("percent_dissolved", 99.0, unit="%", time=45, time_unit="min", statistic="arithmetic_mean", spread=2.0,
              spread_kind="SD", n=12, conditions={"medium": "0.1 N HCl"},
              entity={"product": product["product"], "batch": product["batch"]})
    after = found()
    assert set(after) == set(before) and all(after[code] != before[code] for code in before)


@pytest.mark.parametrize("code", CHECKS)
def test_no_check_message_holds_a_number_read_from_the_values(book, code):
    """A message names labels and the rule; values, LLOQs, BLQ counts and an NCA's numbers stay behind their ids, so a
    blinded study's withholding (contracts §8.10) covers its checks."""
    subject_type, subject, kw = CASES[code](book)
    reader = book.reader(**kw.pop("reader", {}))
    labels = [e.label for kind in ("study", "arm", "product", "batch", "analyte") for e in reader.entities(kind)]
    for result in checks(reader, subject_type, subject, **kw):
        names = {*labels, "Day 1", "Day 14", *_METHOD.values()}   # labels, units and conditions are names, not numbers
        for value_id in result.values:
            value = reader.value(value_id)
            names |= {value.unit or "", value.lloq_unit or "", value.entity.occasion or "", *value.conditions.values()}
        text = re.sub(r"mapping mp-[0-9a-f]{12} v\d+", "", result.message)        # a mapping's id and version
        for name in sorted((n for n in names if n), key=len, reverse=True):
            text = text.replace(name, "")
        assert not re.search(r"\d", text), (code, result.message)


def test_a_blinded_studys_numbers_never_reach_a_check_message(book):
    study, analyte = book.entity("study", "EXA-BLIND"), book.entity("analyte", synthetic.DRUG)
    tablet = book.entity("product", "Exampleamide tablet")
    on, prof = {"study": study}, {"study": study, "analyte": analyte, "matrix": "plasma"}
    for name, value, kw in (("dose", 47.0, {"unit": "mg", "entity": {**on, "product": tablet}}), ("n", 13, {}),
                            ("route", "oral", {}), ("formulation", "ir_tablet", {})):
        book.fact(name, value, **{"entity": on, **kw})
    book.fact("strength_mg", 20.0, unit="mg", entity={"product": tablet})
    book.fact("lloq", 0.37, unit="ng/mL", entity=prof)
    book.fact("lloq", 0.73, unit="ng/mL", entity=prof)                                   # two LLOQs
    for time, value in ((0.5, 4.37), (1.0, 13.7), (2.0, 27.3), (4.0, 17.9), (8.0, 6.13), (12.0, 0.0)):
        book.fact("concentration", value, unit="ng/mL", time=time, time_unit="h", statistic="individual",
                  entity={**prof, "subject": "A"})
    for time in (16.0, 24.0, 36.0):                                                      # three BLQ cells
        book.fact("concentration", None, unit="ng/mL", time=time, time_unit="h", statistic="individual", censored=True,
                  lloq=0.37, lloq_unit="ng/mL", verbatim="<0.37", entity={**prof, "subject": "A"})
    book.fact("concentration", -1.9, unit="ng/mL", time=48.0, time_unit="h", statistic="individual", entity={**prof, "subject": "B"})
    book.fact("concentration", None, unit="ng/mL", time=1.0, time_unit="h", statistic="individual", uloq=1730.0,
              verbatim=">1730", entity={**prof, "subject": "B"})
    for time, value in ((0.5, 4.1), (1.0, 12.9), (2.0, 26.7), (4.0, 18.3), (8.0, 6.2)):
        book.fact("concentration", value, unit="ng/mL", time=time, time_unit="h", statistic="arithmetic_mean", spread=1.3,
                  spread_kind="SD", n=13, entity=prof)
    book.fact("pk.Cmax", 91.7, unit="ng/mL", statistic="arithmetic_mean", entity=prof)
    found = checks(book.reader(), "study", study)
    assert {"ONE_LLOQ_PER_PROFILE", "BLQ_PRESENT", "NCA_MISMATCH", "NEGATIVE_VALUE", "ABOVE_RANGE",
            "ZERO_AFTER_QUANTIFIABLE", "DOSE_NOT_MULTIPLE_OF_STRENGTH"} <= codes(found)
    for result in found:
        assert not re.search(r"\d", result.message), (result.code, result.message)


def _edit(loaded: IntakeRules, section: str, **values: Any) -> IntakeRules:
    return loaded.model_copy(update={section: getattr(loaded, section).model_copy(update=values)})


def test_every_threshold_and_severity_is_read_from_the_rules_file(book):
    ids = clean(book, skip=("dose", "age_mean"))
    product = book.entity("product", "Exampleamide 50 mg tablet")
    book.fact("strength_mg", 50.0, unit="mg", entity={"product": product})
    book.fact("dose", 50.4, unit="mg", entity={"study": ids["study"], "product": product})       # 1.008 units
    book.fact("molecular_weight", 302.0, unit="g/mol", entity={"study": ids["study"], "analyte": ids["analyte"]})
    _value(book, ids, 9.9, 61.5, time_unit="min")                    # 1.5 min after the 1 h point of the series
    _value(book, ids, 3.0, entity=profile(ids, matrix="serum", subject="005"))
    book.fact("special_population", "elderly", entity={"study": ids["study"]})
    reader = book.reader()
    loaded = rules()

    def run(edited: IntakeRules) -> dict[str, CheckResult]:
        return {r.code: r for r in checks(reader, "study", ids["study"], mol_weight=300.0, rules=edited)}

    base = run(loaded)
    assert {"DUPLICATE_TIME", "MW_INCONSISTENT", "DOSE_NOT_MULTIPLE_OF_STRENGTH"}.isdisjoint(base)
    assert {"MATRIX_NOT_PLASMA", "POPULATION_COVARIATE_MISSING"} <= set(base)
    assert "DUPLICATE_TIME" in run(_edit(loaded, "ledger", time_resolution_min=2))
    assert "MW_INCONSISTENT" in run(_edit(loaded, "checks", mw_relative_tolerance=0.001))
    assert "DOSE_NOT_MULTIPLE_OF_STRENGTH" in run(_edit(loaded, "checks", dose_multiple_relative_tolerance=0.001))
    assert "MATRIX_NOT_PLASMA" not in run(_edit(loaded, "landing", matrix_as_plasma_with_warning=("blood",)))
    routing = loaded.routing.model_copy(update={"population_covariates": {"elderly": ("special_population",)}})
    assert "POPULATION_COVARIATE_MISSING" not in run(loaded.model_copy(update={"routing": routing}))
    severity = {**loaded.checks.severity, "fail": tuple(c for c in loaded.checks.severity["fail"] if c != "MATRIX_NOT_PLASMA"),
                "info": (*loaded.checks.severity["info"], "MATRIX_NOT_PLASMA")}
    moved = run(_edit(loaded, "checks", severity=severity))
    assert moved["MATRIX_NOT_PLASMA"].severity == "info"
    dropped = {**loaded.checks.severity, "warn": tuple(c for c in loaded.checks.severity["warn"]
                                                       if c != "POPULATION_COVARIATE_MISSING")}
    assert "POPULATION_COVARIATE_MISSING" not in run(_edit(loaded, "checks", severity=dropped))   # not listed: not run


def test_composition_dissolution_and_the_spread_rules_move_with_the_rules_file(book):
    ids = clean_product(book)
    for component, amount in (("Exampleamide", 33.2), ("lactose", 66.4)):          # 99.6 %
        book.fact("composition.amount", amount, unit="%", conditions={"component": component},
                  entity={"product": ids["product"]})
    reader = book.reader()
    loaded = rules()
    assert "COMPOSITION_SUM" not in codes(checks(reader, "product", ids["product"]))
    tight = _edit(loaded, "checks", composition_sum_tolerance_percent=0.1)
    assert "COMPOSITION_SUM" in codes(checks(reader, "product", ids["product"], rules=tight))
    study = clean(book, skip=("mean",))
    for time, value, sd in _MEAN:
        _value(book, study, value, time, statistic="geometric_mean", spread=sd, spread_kind="SD", n=12,
               entity=profile(study))
    reader = book.reader()                                   # a reader is a snapshot: a new one sees the new values
    assert "GEOMETRIC_SPREAD_VERBATIM" in codes(checks(reader, "study", study["study"]))
    landing = {**loaded.landing.spreads_landed, "geometric_mean": {"geoSD": "SD", "SD": "SD"}}
    widened = _edit(loaded, "landing", spreads_landed=landing)
    assert "GEOMETRIC_SPREAD_VERBATIM" not in codes(checks(reader, "study", study["study"], rules=widened))


def test_a_time_reference_stated_by_the_mapping_clears_the_multiple_dose_check(book):
    ids = clean(book)
    book.fact("design", "MD", entity={"study": ids["study"]})
    assert "TIME_REFERENCE_UNSTATED" in codes(checks(book.reader(), "study", ids["study"]))
    spec = MappingSpec(kind="pk_individual", layout="long", header_rows=1, first_data_row=2, time_reference="first_dose")
    entry = MappingEntry(mapping_id=APPROVED.mapping_id, version=1, fingerprint="0" * 64, spec=spec, origin="person",
                         origin_detail="u-1", first_seen=(SHA, "rg-0000000001"), by="u-1", at=AT)
    book.store.mappings.append("entry", entry.model_dump(mode="json", by_alias=True))
    assert "TIME_REFERENCE_UNSTATED" not in codes(checks(book.reader(), "study", ids["study"]))


def test_an_se_with_its_n_or_a_derived_sd_is_converted(book):
    ids = clean(book, skip=("mean",))
    values = [_value(book, ids, value, time, statistic="arithmetic_mean", spread=se, spread_kind="SE",
                     entity=profile(ids)) for time, value, se in _MEAN]
    assert "SPREAD_NOT_CONVERTED" in codes(checks(book.reader(), "study", ids["study"]))
    for value_id, (time, _value_, se) in zip(values, _MEAN, strict=True):     # what the ledger's compute stage derives
        book.fact("concentration", None, method="derived", time=time, time_unit="h", statistic="arithmetic_mean",
                  spread=se * 12 ** 0.5, spread_kind="SD", derived_from=(value_id,), compute="spread-1/sd_from_se",
                  entity=profile(ids), verbatim="")
    assert "SPREAD_NOT_CONVERTED" not in codes(checks(book.reader(), "study", ids["study"]))


def test_the_synthetic_truth_is_checked_without_error_and_finds_what_it_holds(tmp_path):
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    write_truth(ws, (*synthetic.delivery(), synthetic.template_workbook()))
    reader = Reader(ws)
    by_label = {e.label: e.id for e in reader.entities("study")}
    first = {r.code: r for r in checks(reader, "study", by_label["230-23"], mol_weight=300.0)}
    assert {"ABOVE_RANGE", "MARKED_VALUE", "BLQ_PRESENT", "EXCRETION_NOT_LANDED", "ANALYTE_NOT_PARENT"} <= set(first)
    assert "ONE_LLOQ_PER_PROFILE" not in first and "BLQ_WITHOUT_LLOQ" not in first       # each profile has its one LLOQ
    assert "UNIT_NOT_CHECKED" in first and first["UNIT_NOT_CHECKED"].severity == "info"   # PK-parameter units
    listing = {r.code for r in checks(reader, "study", by_label["230-28"])}                # the delimited file
    assert "BLQ_WITHOUT_LLOQ" in listing and "DOSE_MISSING" in listing
    template = {r.code for r in checks(reader, "study", by_label["EXA-101"])}
    assert "LANDING_FIELD_MISSING" not in template and "CROSSOVER_PERIOD_MISSING" not in template
    for product in reader.entities("product"):
        for result in checks(reader, "product", product.id):
            assert result.subject == product.id and result.rule.startswith(RULE_KEYS)
    vessels = next(p.id for p in reader.entities("product") if p.label == f"{synthetic.DRUG} IR tablet")
    assert "DISSOLUTION_METHOD_INCOMPLETE" in codes(checks(reader, "product", vessels))  # no apparatus is written
    assert all(r.rule.startswith(RULE_KEYS) for r in checks(reader, "compound", "compound", mol_weight=300.0))
