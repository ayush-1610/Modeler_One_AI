"""What the question needs (plan 2026-11-24 §6, phase 2): the requirement drafts per context of use wired to the Data
room, labelled draft and UNVERIFIED. The loader (core merged, overrides applied), the applications read from the
question card by whole words, the properties and triggers (met, not met, not known; an SME cut-off never invented),
the coverage ledger (found, missing with the files searched, not needed, context only, room gap), and the data
requests with their alternatives, never duplicated and never for an item the question does not need. Synthetic rooms
(Exampleamide); no client data, no AI model.
"""

from __future__ import annotations

from importlib import resources

import pytest
import yaml

from modeler_intake.room_specs import (
    ChecklistItem,
    ColumnSpec,
    Extraction,
    Fact,
    FileTriage,
    ProductRef,
    QuestionCard,
    TableDescription,
)
from modeler_intake.source import parse_document
from modeler_project.dataroom import checklist
from modeler_project.dataroom.assemble import Inputs, assemble, pka_type
from modeler_project.dataroom.checklist import Evidence, Prop
from modeler_project.dataroom.drafts import LABEL, DraftError, _item, _trigger, load_drafts
from modeler_project.dataroom.model import CheckedFact, Chip, FileView, ReadCell, ReadRow, ReadTable, SolubilityRow, Value

pytestmark = pytest.mark.req("T-47")

DRAFTS = load_drafts()


def _app(*ids: str) -> tuple[checklist.Application, ...]:
    by_id = {a.id: a for a in checklist.APPLICATIONS}
    return tuple(by_id[i] for i in ids)


def _chip(file: str = "D/notes.md", line: int = 1) -> Chip:
    return Chip(file=file, part="body", line=line)


def _fact(field: str, value: str, quote: str = "", subject: str = "", file: str = "D/notes.md", line: int = 1) -> CheckedFact:
    return CheckedFact(fact=Fact(field=field, value=value, quote=quote or value, subject=subject, file=file), ok=True,
                       chip=_chip(file, line))


def _table(kind: str, roles: tuple[str, ...] = ("value",), file: str = "D/table.csv") -> ReadTable:
    desc = TableDescription(file=file, kind=kind, part="body", first_line=2, last_line=2,  # type: ignore[arg-type]
                            columns=[ColumnSpec(index=i + 1, role=r) for i, r in enumerate(roles)])
    cells = tuple(ReadCell(role=r, text="1", chip=_chip(file, 2)) for r in roles)
    return ReadTable(id=f"{file}-{kind}", description=desc, rows=(ReadRow(line=2, cells=cells),))


def _file(path: str, topics: list[str], purpose: str = "used") -> FileView:
    return FileView(path=path, name=path.rsplit("/", 1)[-1], sha256=path, kind="delimited",
                    triage=FileTriage(path=path, purpose=purpose, topics=topics, reason="synthetic"))  # type: ignore[arg-type]


def _card(question: str, **more: object) -> QuestionCard:
    return QuestionCard(question=question, **more)  # type: ignore[arg-type]


def _ev(facts: list[CheckedFact] = (), tables: list[ReadTable] = (), files: list[FileView] = (), **more: object) -> Evidence:
    facts = list(facts)
    return Evidence(facts=facts, tables=list(tables), files=list(files) or [_file("D/notes.md", ["drug_substance", "adme"])],
                    pkas=checklist.pka_values(facts, pka_type), **more)  # type: ignore[arg-type]


def _items(apps: tuple[str, ...], ev: Evidence, card: QuestionCard | None = None) -> dict[str, object]:
    props = checklist.properties(card or _card("q"), ev)
    return {i.id: i for i in checklist.ledger(DRAFTS, _app(*apps), props, ev)}


# --- 1. the loader ---------------------------------------------------------------------------------------------------


def test_the_loader_reads_every_draft_once_labelled_unverified():
    assert load_drafts() is DRAFTS                                   # read once
    assert set(DRAFTS.files) == {a.file for a in checklist.APPLICATIONS}
    assert "UNVERIFIED" in LABEL and "owner's and the SME's review" in LABEL
    assert "0.1-draft" in DRAFTS.version() and "DRAFT_UNVERIFIED" in DRAFTS.version()
    assert len(DRAFTS.context_only.items) == 4 and all(i.kept_as == "context" for i in DRAFTS.context_only.items)


def test_a_context_of_use_merges_the_core_and_applies_its_overrides():
    ids = [i.id for i in DRAFTS.items_for("food_effect")]
    assert "core.molecular_weight" in ids and "fe.permeability" in ids
    # fe.iv_pk and fe.fasted_clinical_pk replace the core's IV and fasted oral PK
    assert "core.iv_pk" not in ids and "fe.iv_pk" in ids
    assert "core.fasted_oral_pk" not in ids and "fe.fasted_clinical_pk" in ids
    # one item may replace several core items (first in human: no clinical data yet)
    fih = [i.id for i in DRAFTS.items_for("fih_dose_prediction")]
    assert not {"core.fasted_oral_pk", "core.iv_pk", "core.mass_balance", "core.sponsor_nca"} & set(fih)
    # a sub-context keeps its own items only, and its own overrides
    renal = [i.id for i in DRAFTS.items_for("organ_impairment", "renal_impairment")]
    assert "ri.mass_balance" in renal and "core.mass_balance" not in renal and not [i for i in renal if i.startswith("hi.")]
    with pytest.raises(KeyError):
        DRAFTS.items_for("no_such_application")
    with pytest.raises(KeyError):
        DRAFTS.items_for("organ_impairment", "no_such_subcontext")


@pytest.mark.parametrize("node", [
    {"property": "highest_basic_pka", "above": 5},                                  # a number without its source
    {"any": [{"property": "salt_form", "equals": True}]},                           # any of one
    {"property": "fraction_excreted_unchanged", "direction": "above", "threshold": "SME", "threshold_source": "x"},
    {"property": "salt_form", "equals": True, "in": ["x"]},                         # two tests
])
def test_the_loader_refuses_a_trigger_outside_the_grammar(node):
    with pytest.raises(DraftError):
        _trigger(node, "test")


def test_the_loader_refuses_an_item_that_breaks_the_documented_shape():
    core = resources.files("pbpk_domain.requirement_drafts.context_of_use").joinpath("core.yaml").read_text(encoding="utf-8")
    documented = set(yaml.safe_load(core)["item_keys"])
    good = {"id": "core.x", "label": "x", "group": "Phys-chem", "kind": "parameter", "cou_status": "REQUIRED", "why": "w",
            "alternatives": [], "room_fields": ["field:substance.mw"], "data_category": "physchem",
            "default_provider": "CLIENT", "sources": ["s"], "note": "UNVERIFIED: x"}
    assert _item(good, "core", documented).status == "REQUIRED"
    for bad in ({**good, "pksim": "x"}, {**good, "cou_status": "CONDITIONAL"}, {**good, "room_fields": ["field:no.such"]},
                {**good, "cou_status": "USUALLY_NEEDED"}):
        with pytest.raises(DraftError):
            _item(bad, "core", documented)


# --- 2. which applications --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("text", "expected"), [
    ("Predict the food effect for the label", {"food_effect"}),
    ("Simulate the fed state exposure", {"food_effect"}),
    ("Predict the DDI with itraconazole", {"ddi_victim", "ddi_perpetrator"}),
    ("Effect of a strong CYP3A4 inhibitor on the victim drug", {"ddi_victim"}),
    ("Does Exampleamide inhibit others? It inhibits CYP2C8 as a perpetrator", {"ddi_perpetrator"}),
    ("Is it an OATP1B1 or P-gp substrate? A transporter question", {"transporter_ddi"}),
    ("A transporter DDI with rifampicin", {"transporter_ddi", "ddi_victim", "ddi_perpetrator"}),
    ("Dose children and infants", {"pediatric"}),
    ("Paediatric extrapolation", {"pediatric"}),
    ("Dose in renal impairment", {"organ_impairment.renal_impairment"}),
    ("Dose in hepatic impairment", {"organ_impairment.hepatic_impairment"}),
    ("Dose in organ impairment", {"organ_impairment.renal_impairment", "organ_impairment.hepatic_impairment"}),
    ("Virtual bioequivalence for a site change", {"pbbm_bridging_vbe"}),
    ("A PBBM to set the dissolution specification (safe space) and support a biowaiver", {"pbbm_bridging_vbe"}),
    ("Bridging after scale-up and a formulation change", {"pbbm_bridging_vbe"}),
    ("Co-administration with a PPI or an H2 blocker; pH-dependent solubility", {"acid_reducing_agents"}),
    ("Choose the first-in-human starting dose", {"fih_dose_prediction"}),
    ("Exposure in pregnant women", {"special_populations.pregnancy"}),
    ("Exposure in the elderly (geriatric patients)", {"special_populations.geriatrics"}),
    ("Exposure in an ethnic subgroup", {"special_populations.ethnicity"}),
    # whole words only: federal is not fed, fasted is not fed, a name containing "bridge" letters is not bridging
    ("A federal submission for fasted subjects", set()),
    ("Describe the absorption of Exampleamide", set()),
])
def test_each_phrase_family_reads_its_application(text, expected):
    assert set(checklist.read_applications(_card(text))) == expected


def test_the_words_that_matched_are_kept_with_the_field_they_came_from():
    card = _card("Support a biowaiver and describe the food effect", approach="PBBM", regulator="FDA")
    read = checklist.read_applications(card)
    assert list(read) == ["pbbm_bridging_vbe", "food_effect"]          # in the table's order
    assert read["pbbm_bridging_vbe"] == ("'biowaiver' (question)", "'PBBM' (approach)")
    assert read["food_effect"] == ("'food effect' (question)",)


def test_the_applications_decision_offers_the_combination_each_alone_and_none():
    card = _card("Support a biowaiver and describe the food effect", approach="PBBM")
    d = checklist.applications_decision(card, {})
    assert [o.id for o in d.options] == ["pbbm_bridging_vbe+food_effect", "pbbm_bridging_vbe", "food_effect", "none"]
    assert d.suggested == "pbbm_bridging_vbe+food_effect" and d.chosen is None
    assert "'biowaiver' (question)" in d.options[0].detail and "as read from the question card" in d.why
    assert [a.id for a in checklist.chosen_applications(d)] == ["pbbm_bridging_vbe", "food_effect"]
    # a person's choice drives the checklist; a stale one (no longer offered) is ignored
    chose = checklist.applications_decision(card, {"applications": {"chosen": "food_effect", "by": "u"}})
    assert [a.id for a in checklist.chosen_applications(chose)] == ["food_effect"] and chose.chosen == "food_effect"
    none = checklist.applications_decision(card, {"applications": {"chosen": "none", "by": "u"}})
    assert checklist.chosen_applications(none) == ()
    stale = checklist.applications_decision(card, {"applications": {"chosen": "pediatric", "by": "u"}})
    assert stale.chosen is None
    # nothing read: the core items only
    plain = checklist.applications_decision(_card("Describe the absorption"), {})
    assert [o.id for o in plain.options] == ["none"] and checklist.chosen_applications(plain) == ()
    assert checklist.applications_decision(None, {}) is None


# --- 3. properties and triggers --------------------------------------------------------------------------------------


def _trig(item_id: str):
    return DRAFTS.item(item_id).trigger


def test_a_trigger_is_met_not_met_or_not_known():
    trigger = _trig("ara.salt_form_surface_ph")                      # {salt_form: true}
    assert checklist.evaluate(trigger, {"salt_form": Prop(True, True)})[0] == "yes"
    assert checklist.evaluate(trigger, {"salt_form": Prop(True, False)})[0] == "no"
    assert checklist.evaluate(trigger, {})[0] == "unknown"
    families = _trig("hi.hepatic_uptake")                            # any_of [OATP]: a family matches its members
    assert checklist.evaluate(families, {"transporter_families": Prop(True, frozenset({"OATP1B1"}))})[0] == "yes"
    assert checklist.evaluate(families, {"transporter_families": Prop(True, frozenset({"P-GP"}))})[0] == "no"
    bcs = _trig("ped.mechanistic_absorption_inputs")                 # bcs_class in [II, III, IV]
    assert checklist.evaluate(bcs, {"bcs_class": Prop(True, "I")})[0] == "no"


def test_an_sme_cut_off_stays_not_known_unless_the_rest_decides():
    renal = _trig("ped.renal")                                       # fraction excreted unchanged above an SME cut-off
    state, words = checklist.evaluate(renal, {"fraction_excreted_unchanged": Prop(True, 0.9)})
    assert state == "unknown" and "SME" in words[0] and "0.9" in words[0]      # even at 90 %, no cut-off is invented
    precipitation = _trig("fe.precipitation")      # any(all(weak base, pKa > 5 (sourced), ratio > SME), salt)
    weak = {"weak_base": Prop(True, True), "highest_basic_pka": Prop(True, 9.6),
            "solubility_ratio_gastric_to_intestinal": Prop(True, 500.0)}
    assert checklist.evaluate(precipitation, weak)[0] == "unknown"
    assert checklist.evaluate(precipitation, {**weak, "salt_form": Prop(True, True)})[0] == "yes"   # holds regardless
    acid = {"weak_base": Prop(True, False), "salt_form": Prop(True, False)}
    assert checklist.evaluate(precipitation, acid)[0] == "no"                                       # fails regardless
    low = {"weak_base": Prop(True, True), "highest_basic_pka": Prop(True, 4.1), "salt_form": Prop(True, False)}
    assert checklist.evaluate(precipitation, low)[0] == "no"         # the sourced cut-off (pKa above 5) is applied


def test_code_reads_the_compound_and_question_properties_from_the_room():
    facts = [_fact("substance.pka", "pKa1 (basic, pyridine N) = 4.1; pKa2 (acidic, benzimidazole N-H) = 9.3"),
             _fact("substance.salt", "hydrochloride"),
             _fact("adme.metabolism", "CYP3A4 (about 80 %), not a substrate of CYP2D6"),
             _fact("adme.excretion", "12 % of the dose excreted unchanged in urine"),
             _fact("adme.transporters", "substrate of P-gp; not a substrate of OATP1B1"),
             _fact("study.fed", "high-fat breakfast 30 min before dosing")]
    solubility = [SolubilityRow(medium="HCl", ph=1.2, solubility_mg_ml=5.0, as_written="5 mg/mL"),
                  SolubilityRow(medium="FaSSIF", ph=6.5, solubility_mg_ml=0.05, as_written="0.05 mg/mL")]
    perm = Value(key="substance.permeability", label="p", value=20.0, unit="10^-6 cm/s", as_written="Caco-2 Papp 20")
    card = _card("q", products=[ProductRef(name="R", role="reference")])
    ev = _ev(facts, [_table("concentrations", ("subject", "time", "value"))], solubility=solubility,
             cell_permeability=[perm])
    p = checklist.properties(card, ev)
    assert (p["weak_base"].value, p["highest_basic_pka"].value) == (True, 4.1)     # each pKa typed by its own words
    assert p["salt_form"].value is True
    assert p["solubility_ratio_gastric_to_intestinal"].value == pytest.approx(100.0)
    assert p["metabolised"].value is True and p["metabolising_enzymes"].value == frozenset({"CYP3A4"})
    assert p["fraction_excreted_unchanged"].value == pytest.approx(0.12)
    assert p["transporter_families"].value == frozenset({"P-GP"})                  # the negated OATP1B1 is not named
    assert p["in_vitro_permeability_supplied"].value is True
    assert p["individual_data_available"].value is True
    assert p["fed_dosing_in_scope"].value is True and p["reference_product_in_question"].value is True
    assert "adult_food_effect" not in p and "hepatic_extraction" not in p           # an SME cut-off; a person answers


def test_a_fasted_study_with_a_meal_after_the_dose_is_not_fed_dosing():
    facts = [_fact("study.fasting", "after an overnight fast"), _fact("study.fed", "breakfast was served 2 h after dosing"),
             _fact("substance.pka", "4.2", quote="pKa | 4.2 | acidic (carboxylic acid)")]
    p = checklist.properties(_card("Predict exposure"), _ev(facts))
    assert p["fed_dosing_in_scope"].value is False
    assert p["weak_base"].value is False and p["in_vitro_permeability_supplied"].value is False
    assert p["individual_data_available"].value is False
    assert "salt_form" not in p and "metabolised" not in p                           # nothing said: not known
    assert checklist.properties(_card("Predict the food effect"), _ev(facts))["fed_dosing_in_scope"].value is True


# --- 4. the ledger ---------------------------------------------------------------------------------------------------


def test_coverage_found_names_what_satisfies_the_item_with_its_sources():
    ev = _ev([_fact("substance.mw", "412.5", line=3)], [_table("solubility", ("medium", "ph", "solubility"))])
    items = _items(("food_effect",), ev)
    mw = items["core.molecular_weight"]
    assert mw.coverage == "found" and mw.found == ("molecular weight: 1 fact",) and mw.chips[0].line == 3
    assert items["fe.solubility_vs_ph"].coverage == "found" and "solubility table" in items["fe.solubility_vs_ph"].coverage_text


def test_coverage_missing_says_which_files_were_searched():
    files = [_file("D/adme report.pdf", ["adme"]), _file("D/dissolution.xlsx", ["dissolution"]),
             _file("D/timesheet.xlsx", ["adme"], purpose="not_needed")]
    fu = _items(("food_effect",), _ev(files=files))["core.fu_plasma"]
    assert fu.coverage == "missing" and fu.searched == ("D/adme report.pdf",)      # the files about ADME, never a not-needed one
    assert "1 file searched: adme report.pdf" in fu.coverage_text
    # no file about the item's topics: every used file was searched
    lone = _items(("food_effect",), _ev(files=[_file("D/dissolution.xlsx", ["dissolution"])]))["core.fu_plasma"]
    assert lone.searched == ("D/dissolution.xlsx",)


def test_not_needed_inapplicable_and_context_only_items_are_never_missing():
    items = _items(("food_effect",), _ev())
    fm = items["fe.fm_ddi_ontogeny"]
    assert (fm.level, fm.coverage) == ("not_needed", "not_needed") and fm.why in fm.coverage_text
    calibration = items["core.permeability_calibration"]            # no in vitro permeability: its condition fails
    assert (calibration.level, calibration.applies, calibration.coverage) == ("not_needed", "no", "not_needed")
    assert "its condition does not hold" in calibration.coverage_text
    for ctx in ("ctx.manufacturing_process", "ctx.tablet_hardness", "ctx.full_excipient_list", "ctx.f2"):
        assert (items[ctx].level, items[ctx].coverage) == ("context", "context") and "never asked for" in items[ctx].coverage_text
    assert not [i for i in items.values() if i.coverage == "missing" and i.level in ("not_needed", "context", "optional")]


def test_a_room_gap_or_an_activity_is_for_a_person_never_missing():
    ev = _ev([_fact("substance.solubility", "0.2 mg/mL at pH 6.8")])
    items = _items(("food_effect", "pbbm_bridging_vbe"), ev)
    assert items["fe.disintegration"].coverage == "person_checks"
    assert items["fe.disintegration"].coverage_text == "the room cannot read this yet: a person checks it"
    surface = items["vbe.surface_solubility"]                        # the room has a solubility, not a surface one
    assert surface.coverage == "found_in_part" and "a person checks it" in surface.coverage_text and surface.room_gap
    assert items["core.sensitivity_analysis"].coverage == "not_from_delivery"


def test_an_unknown_trigger_shows_applies_if_never_missing():
    precipitation = _items(("food_effect",), _ev())["fe.precipitation"]   # no pKa, no salt fact
    assert (precipitation.level, precipitation.applies, precipitation.coverage) == ("to_ask", "unknown", "to_ask")
    assert precipitation.coverage_text.startswith("applies if: ") and "not known from the delivery" in precipitation.coverage_text


def test_the_strictest_status_wins_across_applications_and_says_which_requires_it():
    items = _items(("food_effect", "pbbm_bridging_vbe"), _ev())
    # IV PK: optional for a food effect (fe.iv_pk), required as disposition data for bridging (vbe.disposition_data)
    assert "fe.iv_pk" not in items and "core.iv_pk" not in items
    disposition = items["vbe.disposition_data"]
    assert disposition.level == "required" and disposition.by == ("PBBM, bridging and virtual BE",)
    assert disposition.others == ("Food effect: optional (fe.iv_pk)",)
    assert items["core.molecular_weight"].by == ("every application (core)",)
    # the core items alone when no application is chosen
    core = _items((), _ev())
    assert all(i.startswith(("core.", "ctx.")) for i in core) and core["core.pka"].by == ("the core items (every context of use)",)


# --- 5. data requests ------------------------------------------------------------------------------------------------


def test_asks_are_worded_with_why_alternatives_and_the_draft_label_and_lettered_by_category():
    items = _items(("ddi_victim",), _ev(files=[_file("D/a.pdf", ["clinical_concentrations"])]))
    asks = {a.item: a for a in checklist.asks(list(items.values()))}
    iv = asks["ddiv.iv_pk"]
    assert iv.area == "D" and iv.title == "Intravenous PK"
    assert iv.why.startswith("Usually needed for DDI, the drug as victim: It separates gut-wall extraction")
    assert "If it is not available: oral solution PK; single and multiple ascending dose studies;" in iv.why
    assert iv.why.endswith("(draft requirement, UNVERIFIED)")
    assert asks["core.fu_plasma"].area == "C" and asks["core.fu_plasma"].why.startswith("Required for DDI, the drug as victim")
    # never asked: not needed, inapplicable, not known, optional, context, a person's or the platform's
    never = {i for i, x in items.items() if x.level in ("not_needed", "context", "optional", "to_ask")
             or x.coverage in ("person_checks", "not_from_delivery", "found", "found_in_part")}
    assert not never & set(asks)
    assert {checklist.area_of(i) for i in (items["ddiv.fm_phenotyping"], items["ddiv.clinical_ddi_index"])} == {"C", "D"}


def test_the_same_ask_names_draft_items_that_exist():
    every = {i.id for f in (DRAFTS.core, DRAFTS.context_only, *DRAFTS.files.values()) for i in f.items}
    assert {i for ids in checklist.SAME_ASK.values() for i in ids} <= every


SYNOPSIS = ("# Study DX-01 synopsis\n\n"
            "Exampleamide has a molecular weight of 412.5 g/mol.\n"
            "pKa 8.2 (basic, piperidine).\n"
            "Exampleamide is metabolised mainly by CYP3A4.\n"
            "Each subject received 100 mg after an overnight fast of 10 h.\n")
FACTS = [Fact(field="substance.mw", value="412.5", unit="g/mol", quote="a molecular weight of 412.5 g/mol."),
         Fact(field="substance.pka", value="8.2", quote="pKa 8.2 (basic, piperidine)."),
         Fact(field="adme.metabolism", value="CYP3A4", quote="Exampleamide is metabolised mainly by CYP3A4."),
         Fact(field="study.fasting", subject="DX-01", value="overnight fast of 10 h", quote="after an overnight fast of 10 h.")]
A6 = [ChecklistItem(id="A-manufacturing", label="Manufacturing process and its changes", area="A",
                    topics=["manufacturing", "quality_paperwork"]),
      ChecklistItem(id="D-iv", label="Intravenous PK", area="D", topics=["clinical_concentrations"])]


def _room(question: str, *, confirmed: bool = True, decisions: dict | None = None):
    doc = parse_document(SYNOPSIS.encode(), "synopsis.md")
    file = FileView(path="D/synopsis.md", name="synopsis.md", sha256=doc.file_sha256, kind="text",
                    triage=FileTriage(path="D/synopsis.md", purpose="used", topics=["drug_substance", "adme", "clinical_design"],
                                      reason="the study synopsis"))
    card = _card(question, checklist=A6)
    return assemble(Inputs(files=[file], docs={file.sha256: doc}, question=card, question_confirmed=confirmed,
                           extractions=[Extraction(file="D/synopsis.md", facts=FACTS)], decisions=decisions or {}))


VICTIM = "Predict how itraconazole, a strong CYP3A inhibitor, changes the exposure of Exampleamide, the victim, given fasted."


def test_the_room_asks_for_what_is_missing_after_its_own_requests_and_never_twice():
    view = _room(VICTIM)
    req = view.requirements
    assert req.label == LABEL and req.applications == ("DDI, the drug as victim",) and not req.chosen
    assert view.decisions[0].id == "applications" and view.decisions[0].suggested == "ddi_victim"
    items = {i.id: i for i in req.items}
    by_id = {r.id: r for r in view.requests}
    drafted = [r for r in view.requests if r.why.endswith(checklist.DRAFT_WORDS) and r.checklist.startswith(("core.", "ddiv."))]
    assert drafted and list(view.requests[-len(drafted):]) == drafted  # after the room's own: their codes stay
    # the question card's "Intravenous PK" is the same ask as ddiv.iv_pk (same title): asked once
    assert [r.title for r in view.requests].count("Intravenous PK") == 1
    assert by_id[items["ddiv.iv_pk"].request].checklist == "D-iv"
    # the room's own compound request for the fraction unbound stands for core.fu_plasma
    fu = by_id[items["core.fu_plasma"].request]
    assert fu.checklist == "adme.fu" and fu.input == "bind.fu" and not [r for r in view.requests if r.checklist == "core.fu_plasma"]
    # a missing item worded with its alternatives
    index = next(r for r in drafted if r.checklist == "ddiv.clinical_ddi_index")
    assert index.area == "D" and index.why.startswith("Usually needed for DDI, the drug as victim")
    assert items["ddiv.clinical_ddi_index"].request == index.id and items["ddiv.clinical_ddi_index"].coverage == "missing"


def test_fed_data_for_a_fasted_ddi_question_is_never_asked_for_anywhere():
    view = _room("Predict the DDI of Exampleamide with itraconazole in fasted subjects")   # both sides of the DDI
    items = {i.id: i for i in view.requirements.items}
    assert {"ddiv.fed_dosing_data", "ddip.fed_pk_dissolution", "ddiv.ontogeny", "ddip.own_fm"} <= set(items)
    for not_needed in ("ddiv.fed_dosing_data", "ddip.fed_pk_dissolution", "ddiv.ontogeny"):
        assert (items[not_needed].level, items[not_needed].coverage, items[not_needed].request) == ("not_needed", "not_needed", "")
    assert items["ddiv.fed_dosing_data"].applies == "no"            # fed dosing is not in scope: the study is fasted
    asked = {r.checklist for r in view.requests}
    folded = {i.id for i in items.values() if i.level in ("not_needed", "context")}
    assert not asked & folded
    # nor in what the writer (A10) is given: it reads the room's open requests and the sections' lines
    open_titles = {r.title for r in view.requests if r.status == "open"}
    assert not {items[i].label for i in folded} & open_titles
    section = next(s for s in view.sections if s.id == "requirements")
    assert "not needed (draft requirements, UNVERIFIED)" in section.finding


def test_the_manufacturing_process_is_kept_as_context_not_asked_for():
    view = _room(VICTIM)
    manufacturing = next(r for r in view.requests if r.checklist == "A-manufacturing")
    assert manufacturing.id == "A-01" and manufacturing.status == "not_needed"      # kept, a person may open it again
    assert manufacturing.why.startswith("Kept as context, not asked for") and manufacturing.why.endswith(checklist.DRAFT_WORDS)
    ctx = next(i for i in view.requirements.items if i.id == "ctx.manufacturing_process")
    assert ctx.request == "A-01" and "is kept as context, not asked for" in ctx.coverage_text


def test_no_draft_request_before_the_question_card_is_confirmed_and_the_choice_drives_the_list():
    unconfirmed = _room(VICTIM, confirmed=False)
    assert unconfirmed.requirements.items and not [r for r in unconfirmed.requests if r.why.endswith(checklist.DRAFT_WORDS)]
    chosen = _room(VICTIM, decisions={"applications": {"chosen": "none", "by": "u", "reason": "core first"}})
    assert chosen.requirements.chosen and chosen.requirements.applications == ()
    assert not [i for i in chosen.requirements.items if i.id.startswith("ddiv.")]
    section = next(s for s in chosen.sections if s.id == "requirements")
    assert section.finding.startswith("the core items only:")


def test_no_question_card_no_checklist():
    view = assemble(Inputs(files=[], docs={}))
    assert view.requirements is None and not [d for d in view.decisions if d.id == "applications"]
    assert next(s for s in view.sections if s.id == "requirements").status == "empty"
