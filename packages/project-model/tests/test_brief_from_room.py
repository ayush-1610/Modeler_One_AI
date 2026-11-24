"""Plan 2026-11-24 §7, phase 4: what the Data room already said is not typed again at Start or on Review & sign.

A live room on the synthetic delivery (the made-up Exampleamide, `dataroom.synthetic`; never client data), its agents'
answers written straight into the store as A6-A8 would submit them, every decision taken as suggested. Read through the
one reader (`room_basis`), it drafts the brief (B4), advises Start where a person's word differs (B5), reaches the model
plan's food-effect rule and warns where the plan departs from it (R2, B7), names its decisions, open requests, NCA
findings and BLQ convention among the MAP's limitations (B6), and offers the VBE panel its formulations and observed BE
summary (B8).
"""

from __future__ import annotations

import pytest

from modeler_intake.room_specs import Fact, ProductRef, QuestionCard
from modeler_project.artifacts import ArtifactKind
from modeler_project.brief import APPLICATIONS, FieldStatus, ProjectBrief, empty_brief
from modeler_project.brief_from_room import CODE, RoomError, agencies, draft_brief_from_room, draft_from_room, route_of
from modeler_project.brief_ops import BRIEF_ID, agent_set, edit_field, save_brief
from modeler_project.dataroom import DataRoomStore, room_view
from modeler_project.dataroom.checklist import APPLICATIONS as ROOM_APPLICATIONS
from modeler_project.dataroom.checklist import NONE
from modeler_project.dataroom.model import NcaReproduction, NcaSettings
from modeler_project.dataroom.reading import read_uploads
from modeler_project.dataroom.synthetic import QUESTION, delivery_zip, seed
from modeler_project.plan import (
    Structure,
    blocking,
    build_default,
    effective_applications,
    map_from_plan,
    map_limitations,
    room_limitations,
    structure_from_brief,
    validate,
)
from modeler_project.review import applications as review_applications
from modeler_project.review import vbe_suggestion
from modeler_project.room_basis import (
    ROOM_TO_BRIEF,
    DecisionLine,
    RequestLine,
    RoomBasis,
    RoomCite,
    basis_from_view,
    room_basis,
)
from modeler_project.steps import room_advice, start_problems
from modeler_project.store import FileProjectStore
from modeler_project.workspace import Workspace
from pbpk_domain.campaign.split import StudyClass

pytestmark = pytest.mark.req("T-41", "T-47")


def _room(tmp_path, *, confirmed: bool = True, decide: bool = True) -> Workspace:
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    store = DataRoomStore(ws)
    store.add_upload("delivery.zip", delivery_zip(), by="u1")
    read_uploads(store, use_ocr=False, workers=1)
    seed(store, confirmed=confirmed)
    if decide:
        for d in room_view(store).decisions:
            store.decide(d.id, d.suggested, by="Dr Modeller", reason="as suggested")
    return ws


@pytest.fixture
def ws(tmp_path) -> Workspace:
    return _room(tmp_path)


def _person(brief: ProjectBrief, path: str, value) -> ProjectBrief:
    return edit_field(brief, path, value=value, status=FieldStatus.EDITED, by="u1")


# --- the mapping table and the reader --------------------------------------------------------------------------------


def test_every_room_application_maps_to_brief_codes_that_exist_with_the_meaning_checked():
    codes = {label.split(" ", 1)[0]: label for label in APPLICATIONS}
    assert set(ROOM_TO_BRIEF) == {a.id for a in ROOM_APPLICATIONS} | {NONE}
    assert all(code in codes for mapped in ROOM_TO_BRIEF.values() for code in mapped)
    named = {room: [codes[c] for c in mapped] for room, mapped in ROOM_TO_BRIEF.items()}
    assert named["pbbm_bridging_vbe"] == ["APP-11 absorption and formulation", "APP-14 virtual bioequivalence"]
    assert named["food_effect"] == ["APP-12 food effect"] and named["acid_reducing_agents"] == ["APP-13 pH-dependent DDI"]
    assert named["ddi_victim"] == named["ddi_perpetrator"] == ["APP-03 enzyme DDI"]
    assert named["transporter_ddi"] == ["APP-04 transporter DDI"] and named["pediatric"] == ["APP-06 pediatric extrapolation"]
    assert named["organ_impairment.renal_impairment"] == ["APP-08 renal impairment"]
    assert named["organ_impairment.hepatic_impairment"] == ["APP-07 hepatic impairment"]
    assert named["fih_dose_prediction"] == ["APP-02 FIH translation"]
    assert named["special_populations.pregnancy"] == ["APP-09 pregnancy and lactation"]
    assert named["special_populations.geriatrics"] == named["special_populations.ethnicity"] == [
        "APP-10 geriatrics, obesity, ethnicity"]
    assert named[NONE] == ["APP-01 model build and verification"]


def test_the_reader_gives_what_the_send_rests_on(ws):
    basis = room_basis(ws)
    assert basis.source == "live" and basis.confirmed and basis.full
    assert basis.applications == ("pbbm_bridging_vbe",) and basis.codes == ("APP-11", "APP-14") and basis.applications_chosen
    assert [(p.name, p.role, p.formulation, p.sent) for p in basis.products] == [
        ("Refamide 100 mg", "reference", "Refamide_100_mg", True), ("Exampleamide 100 mg", "test", "Exampleamide_100_mg", True),
        ("Exampleamide 100 mg reformulated", "reformulated", "Exampleamide_100_mg_reformulated", True)]
    a, b = basis.arms
    assert (a.study_id, a.product, a.plan_role, b.study_id, b.plan_role) == (
        "EX-01-A", "Refamide 100 mg", "calibration", "EX-01-B", "verification")
    assert (a.route.text, a.dose.value, a.dose.unit, a.food.value, a.population_db) == ("oral", 100.0, "mg", "fasted",
                                                                                       "Asian_Tanaka_1996")
    assert a.dose.cites[0].quote == "Each subject received 100 mg" and a.dose.cites[0].citation().page == 1
    assert all(not d.waiting and d.reason == "as suggested" for d in basis.decisions)
    assert {r.id for r in basis.open_requests if not r.required} == {"C-05"}             # a draft's "usually needed"
    assert basis.blq == (("EX-01: the observed arithmetic mean profiles sent to the model count a concentration below "
                          "the LLOQ (0.5 ng/mL) as 0 (3 such values in the proposed modeling set); the geometric means "
                          "leave them out"),)
    # the card and its applications only, with no assembly of the room: what Start and the Inputs check read
    light = room_basis(ws, full=False)
    assert not light.full and light.codes == basis.codes and light.arms == () and room_limitations(light) == ()


def test_no_room_or_no_card_reads_as_none(tmp_path):
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    assert room_basis(ws) is None and room_basis(ws, full=False) is None


# --- B4: the brief drafted from the room -------------------------------------------------------------------------------


def test_start_is_drafted_from_the_rooms_card_and_studies_each_a_draft_with_its_quotes(ws):
    brief, drafted, kept = draft_from_room(empty_brief("Exampleamide", by="u1"), room_basis(ws))
    assert kept == []
    record = brief.get("qoi.text")
    assert (record.status, record.by, record.value) == (FieldStatus.DRAFTED, CODE, QUESTION.question)
    assert brief.value("qoi.text") is None                     # a draft is not a value until a person confirms it
    assert brief.get("qoi.context_of_use").value == QUESTION.context_of_use
    assert brief.get("qoi.applications").value == ["APP-11 absorption and formulation", "APP-14 virtual bioequivalence"]
    assert "chosen in the Data room" in brief.get("qoi.applications").note
    assert brief.get("proj.agencies").value == ["Health Canada"]
    assert [(brief.get(f"products[{i}].name").value, brief.get(f"products[{i}].role").value) for i in range(3)] == [
        ("Refamide 100 mg", "REFERENCE"), ("Exampleamide 100 mg", "TEST"), ("Exampleamide 100 mg reformulated", "TEST")]
    scenarios = [{f: brief.get(f"scenarios[{i}].{f}").value for f in ("route", "dose", "food_state", "product")}
                 for i in range(len(brief.groups["scenarios"]))]
    assert scenarios == [{"route": "oral", "dose": 100.0, "food_state": "fasted", "product": "Refamide 100 mg"},
                         {"route": "oral", "dose": 100.0, "food_state": "fasted", "product": "Exampleamide 100 mg"}]
    dose = brief.get("scenarios[0].dose")
    assert dose.citations[0].quote == "Each subject received 100 mg" and dose.citations[0].source.startswith("Data room: ")
    assert brief.get("scope.formulation_types").value == ["ir_tablet"]
    assert (brief.get("populations[0].kind").value, brief.get("populations[0].ethnicity").value) == ("healthy",
                                                                                                  "Asian_Tanaka_1996")
    # then the ICH M15 ratings by the rule, as Start drafts them
    assert {"m15.influence_suggested", "m15.consequence_suggested", "m15.influence", "m15.consequence"} <= set(drafted)
    assert all(brief.get(p).status is FieldStatus.DRAFTED for p in drafted)
    # the human-only fields are never touched
    assert brief.get("acceptance.tier").status is FieldStatus.MISSING
    assert brief.get("m15.influence_rating").status is FieldStatus.MISSING


def test_a_card_quote_becomes_the_drafts_citation():
    card = QUESTION.model_copy(update={"regulator": "US FDA and EMA", "quotes": [
        Fact(field="question.text", value="perform like", quote="perform like the reference product in vivo",
             file="Exampleamide delivery/Cover letter.txt", part="body")]})
    basis = RoomBasis(card=card, confirmed=True, applications=("food_effect",),
                      card_cites={"question.text": (RoomCite(file="Exampleamide delivery/Cover letter.txt", sha256="a" * 64,
                                                             part="body", quote="perform like the reference"),)})
    brief, _drafted, _kept = draft_from_room(empty_brief("Exampleamide", by="u1"), basis)
    (cite,) = brief.get("qoi.text").citations
    assert (cite.doc_sha256, cite.page, cite.quote, cite.source) == ("a" * 64, 1, "perform like the reference",
                                                                      "Data room: Cover letter.txt")
    assert brief.get("qoi.applications").value == ["APP-12 food effect"]
    assert brief.get("proj.agencies").value == ["FDA", "EMA"]
    assert "as read from the question card" in brief.get("qoi.applications").note


def test_words_the_brief_reads_by_name_and_nothing_else():
    assert agencies("Health Canada") == ["Health Canada"] and agencies("US FDA, then EMA") == ["FDA", "EMA"]
    assert agencies("the Swiss agency") == []                           # never guessed: left for a person
    assert [route_of(t) for t in ("oral", "intravenous infusion over 1 h", "IV bolus", "subcutaneous")] == [
        "oral", "iv_infusion", "iv_bolus", None]


def test_a_persons_value_and_a_documents_are_never_overwritten_and_start_advises(ws):
    basis = room_basis(ws)
    brief = _person(empty_brief("Exampleamide", by="u1"), "qoi.text", "Predict exposure of the 50 mg tablet")
    brief = _person(brief, "qoi.applications", ["APP-01"])
    brief = agent_set(brief, "proj.agencies", value=["FDA"], unit=None, citations=(), status=FieldStatus.EXTRACTED,
                      confidence="A", by="agent:A1")
    brief = edit_field(brief, "qoi.context_of_use", status=FieldStatus.NOT_APPLICABLE, by="u1")
    drafted_brief, drafted, kept = draft_from_room(brief, basis)
    for path in ("qoi.text", "qoi.applications", "proj.agencies", "qoi.context_of_use"):
        assert drafted_brief.get(path) == brief.get(path) and path not in drafted
    assert kept == ["qoi.text", "qoi.applications", "proj.agencies"]   # "not applicable" holds no value to differ from
    advice = {a.path: a.message for a in room_advice(drafted_brief, basis)}
    assert set(advice) == {"qoi.text", "qoi.applications"}
    assert advice["qoi.text"].startswith("Question of interest: the Data room's confirmed question card asks “Does the "
                                         "reformulated Exampleamide tablet")
    assert "APP-11, APP-14" in advice["qoi.applications"] and "Start says APP-01" in advice["qoi.applications"]
    # advice, never a block: Start's own list does not carry it
    assert not any("Data room" in p for p in start_problems(drafted_brief))
    # an unconfirmed card advises nothing, and drafts nothing
    unconfirmed = basis.model_copy(update={"confirmed": False})
    assert room_advice(drafted_brief, unconfirmed) == []
    with pytest.raises(RoomError, match="not confirmed"):
        draft_from_room(brief, unconfirmed)


def test_an_earlier_draft_gives_way_to_the_room_and_a_scenario_is_completed_not_duplicated(ws):
    brief = empty_brief("Exampleamide", by="u1")
    brief = agent_set(brief, "qoi.text", value="Objective: predict exposure.", unit=None, citations=(),
                      status=FieldStatus.DRAFTED, confidence=None, by="code:start-reading")
    for field, value in (("route", "oral"), ("dose", 100.0)):              # code read one strength from the proposal
        brief = agent_set(brief, f"scenarios[0].{field}", value=value, unit=None, citations=(), status=FieldStatus.DRAFTED,
                          confidence=None, by="code:start-reading")
    brief = _person(brief, "scenarios[1].route", "oral")                     # a person's fed scenario
    brief = _person(brief, "scenarios[1].food_state", "fed")
    drafted_brief, drafted, _kept = draft_from_room(brief, room_basis(ws))
    assert drafted_brief.get("qoi.text").value == QUESTION.question and drafted_brief.get("qoi.text").by == CODE
    assert "scenarios[0].food_state" in drafted and not [p for p in drafted if p.startswith("scenarios[1].")]
    items = drafted_brief.groups["scenarios"]
    assert len(items) == 3
    assert (drafted_brief.get("scenarios[0].food_state").value, drafted_brief.get("scenarios[0].product").value) == (
        "fasted", "Refamide 100 mg")                                         # completed, its drafts kept
    assert drafted_brief.get("scenarios[1]" + ".food_state") == brief.get("scenarios[1].food_state")   # the person's, untouched
    assert drafted_brief.get("scenarios[2].product").value == "Exampleamide 100 mg"
    # drafting again changes nothing: no new draft, no new version
    again, more, _ = draft_from_room(drafted_brief, room_basis(ws))
    assert [p for p in more if not p.startswith("m15.")] == [] and again.groups["scenarios"] == items


def test_the_brief_is_saved_once_and_the_data_plan_follows(ws):
    save_brief(ws, empty_brief("Exampleamide", by="u1"), actor="u1", reason="project started")
    first = draft_brief_from_room(ws, by="u1")
    assert "qoi.text" in first["drafted"] and first["kept"] == [] and first["advice"] == []
    version = ws.latest(ArtifactKind.BRIEF, BRIEF_ID)
    assert version.version == 2 and version.created_by == "u1" and version.reason.startswith("drafted from the Data room: ")
    assert ws.latest(ArtifactKind.REQUIREMENTS, "main") is not None
    second = draft_brief_from_room(ws, by="u1")
    assert second["drafted"] == [] and ws.latest(ArtifactKind.BRIEF, BRIEF_ID).version == 2


def test_no_confirmed_card_no_draft(tmp_path):
    ws = _room(tmp_path, confirmed=False, decide=False)
    save_brief(ws, empty_brief("Exampleamide", by="u1"), actor="u1", reason="project started")
    with pytest.raises(RoomError, match="not confirmed"):
        draft_brief_from_room(ws, by="u1")
    bare = Workspace(FileProjectStore(tmp_path / "other"), "t1", "p2")
    with pytest.raises(RoomError, match="no question card"):
        draft_brief_from_room(bare, by="u1")


# --- R2 and B7: the model plan ---------------------------------------------------------------------------------------


def _food_room(**more) -> RoomBasis:
    card = QuestionCard(question="What is the food effect on Exampleamide exposure?",
                        products=[ProductRef(name="Exampleamide 100 mg", role="test")])
    return RoomBasis(card=card, confirmed=True, applications=("food_effect",), **more)


def _row(sid, route="oral", dose=10.0, food="fasted"):
    return {"study_id": sid, "n": 12, "route": route, "dose_mg": dose, "formulation": "solution", "food_state": food,
            "n_timepoints": 6, "origin": "LITERATURE", "evaluable": True, "design": "SD",
            **({"infusion_time_min": 60} if route == "iv_infusion" else {}),
            "profile": {"times": [0.5, 1, 2, 4, 8, 12], "values": [5, 9, 7, 4, 1, 0.3], "time_unit": "h", "unit": "µmol/l"}}


ROWS = [_row("iv-1", "iv_infusion", 250), _row("po-10"), _row("po-50", dose=50), _row("fed-50", food="fed", dose=50),
        _row("fed-100", food="fed", dose=100)]


def _cpf():
    from pbpk_domain.cpf.models import CPF, ParameterRecord, ParameterStatus, Provenance

    prov = Provenance(source_type="Publication", reference="review")
    return CPF(compound="Exampleamide", parameters=tuple(
        ParameterRecord(id=pid, value=v, unit=u, status=ParameterStatus.FIXED, provenance=prov)
        for pid, v, u in (("phys.mw", 412.5, "g/mol"), ("phys.logp", 2.4, "Log Units"), ("bind.fu", 0.03, None),
                          ("phys.solubility.ref", 0.2, "mg/ml"), ("phys.pka.base.0", 8.9, None))))


@pytest.mark.req("T-50")
def test_the_rooms_food_effect_keeps_fed_studies_out_of_the_fit_when_the_brief_has_none_a_person_set():
    brief = empty_brief("Exampleamide", by="u1")
    brief = agent_set(brief, "qoi.applications", value=["APP-11"], unit=None, citations=(), status=FieldStatus.DRAFTED,
                      confidence=None, by="code:start-reading")                # a draft no person confirmed
    without = structure_from_brief(brief)
    assert not without.food_effect_in_question and without.application_codes == ()
    room = _food_room()
    structure = structure_from_brief(brief, room=room)
    assert structure.food_effect_in_question and structure.applications_from_room
    assert structure.application_codes == ("APP-12",) and structure.room_applications == ("APP-12",)
    assert effective_applications(brief, room) == ({"APP-12"}, True)
    cpf = _cpf()
    fed = {s.study_id for s in build_default(cpf, ROWS, without).studies if s.study_class == StudyClass.PO_FED.value}
    plan_without = build_default(cpf, ROWS, without.model_copy(update={"model_risk": "medium"}))
    plan_with = build_default(cpf, ROWS, structure.model_copy(update={"model_risk": "medium"}))
    assert fed == {"fed-50", "fed-100"}
    assert any(plan_without.placements[s].role in ("S1", "S2", "S3") for s in fed)    # without it, a fed study trains
    assert all(plan_with.placements[s].role not in ("S1", "S2", "S3") for s in fed)    # MS-01 rule 5 with the room's
    assert not [v for v in validate(plan_with, cpf, ROWS) if v.rule == "room-applications"]


@pytest.mark.req("T-50")
def test_a_persons_applications_win_and_the_plan_warns_where_the_room_differs():
    brief = _person(empty_brief("Exampleamide", by="u1"), "qoi.applications", ["APP-14"])
    room = _food_room(arms=())
    structure = structure_from_brief(brief, room=room).model_copy(update={"model_risk": "medium"})
    assert not structure.food_effect_in_question and not structure.applications_from_room
    assert structure.application_codes == ("APP-14",) and structure.room_applications == ("APP-12",)
    cpf = _cpf()
    plan = build_default(cpf, ROWS, structure)
    (warning,) = [v for v in validate(plan, cpf, ROWS) if v.rule == "room-applications"]
    assert warning.severity == "warning" and warning.message == (
        "The Data room's question is for APP-12; the plan's applications are APP-14 (the brief's, set by a person on "
        "Start)")
    assert warning in blocking(validate(plan, cpf, ROWS))                  # acknowledged, it is a limitation


@pytest.mark.req("T-50")
def test_the_plan_warns_where_ms01_places_a_study_the_room_plans_otherwise():
    structure = Structure(model_risk="medium", room_roles={"po-10": "verification", "po-50": "calibration"})
    cpf = _cpf()
    plan = build_default(cpf, ROWS, structure)
    roles = {s: p.role for s, p in plan.placements.items()}
    warned = {v.target: v.message for v in validate(plan, cpf, ROWS) if v.rule == "room-roles"}
    expected = {sid for sid, room in (("po-10", "verification"), ("po-50", "calibration"))
                if (room == "calibration") != (roles[sid] in ("S1", "S2", "S3"))}
    assert set(warned) == expected and expected
    sid = next(iter(expected))
    assert warned[sid].startswith(f"{sid}: the Data room's plan uses it for ") and "MS-01 §3.3" in warned[sid]


# --- B6: the MAP's limitations -----------------------------------------------------------------------------------------


@pytest.mark.req("T-50")
def test_the_maps_limitations_name_the_rooms_decisions_requests_nca_findings_and_blq_convention():
    room = _food_room(decisions=(
        DecisionLine(id="population:EX-01", title="Population for EX-01", chosen="Asian (Tanaka 1996)", suggested=True,
                     waiting=False, reason="", why="the study's subjects are Asian", by="Dr Modeller"),
        DecisionLine(id="analysis-set:EX-01", title="Analysis set for EX-01", chosen="Completed: 7 subjects",
                     suggested=False, waiting=False, reason="the client's statistical set", by="Dr Modeller")),
        open_requests=(RequestLine(id="D-01", area="D", title="Subject 3: every concentration below the LLOQ",
                                   why="confirm the dose was taken", required=True),
                       RequestLine(id="C-05", area="C", title="Solid form", why="Usually needed for …", required=False)),
        nca_differ=("EX-01: 2 of the client's 30 NCA values are not reproduced",),
        blq=("EX-01: the observed arithmetic mean profiles sent to the model count a concentration below the LLOQ as 0",))
    lines = room_limitations(room)
    assert lines == (
        ("Data room decision, Population for EX-01: Asian (Tanaka 1996) (by Dr Modeller); the room's suggestion: the "
         "study's subjects are Asian"),
        "Data room decision, Analysis set for EX-01: Completed: 7 subjects (by Dr Modeller); the client's statistical set",
        "Open data request D-01 (Data room): Subject 3: every concentration below the LLOQ. confirm the dose was taken",
        "Usually-needed data requests still open in the Data room: C-05",
        "The client's NCA (Data room), EX-01: 2 of the client's 30 NCA values are not reproduced",
        ("Observed mean profiles (Data room), EX-01: the observed arithmetic mean profiles sent to the model count a "
         "concentration below the LLOQ as 0"))
    cpf = _cpf()
    plan = build_default(cpf, ROWS, structure_from_brief(None, room=room).model_copy(update={"model_risk": "medium"}))
    assert plan.structure.room_limitations == lines
    violations = validate(plan, cpf, ROWS)
    assert all(line in map_limitations(plan, violations) for line in lines)
    acknowledged = plan.model_copy(update={"acknowledged": {v.id: "accepted (u1)" for v in violations if v.severity == "warning"}})
    assert all(line in map_from_plan(acknowledged, cpf, ROWS).split_limitations for line in lines)


def test_the_live_rooms_nca_findings_reach_the_basis(ws):
    view = room_view(DataRoomStore(ws))
    (study,) = view.studies
    nca = tuple(n.model_copy(update={"tiers": {**n.tiers, "auc_t": "differ"}}) if n.subject == "2" else n for n in study.nca)
    rep = NcaReproduction(settings=NcaSettings(integration="linear", time_basis="nominal", blq="0", lambda_z="best"),
                          compared=30, differ=2, tiers="≤ 1 % pass; > 5 % differ")
    changed = view.model_copy(update={"studies": (study.model_copy(update={"nca": nca, "nca_reproduction": rep}),)})
    (line,) = basis_from_view(changed).nca_differ
    assert line.startswith("EX-01: 2 of the client's 30 NCA values are not reproduced by the Data room's NCA under any "
                           "setting tried (subject 2 period ") and "auc_t" in line and line.endswith("(tiers: ≤ 1 % pass; > 5 % differ)")


# --- B8: the VBE panel -------------------------------------------------------------------------------------------------


def test_the_vbe_panel_is_offered_the_rooms_formulations_and_observed_be_never_saved(ws):
    from pbpk_domain.bioequivalence import paired_crossover_ci
    from pbpk_domain.vbe import between_subject_cv

    room = room_basis(ws)
    offered = vbe_suggestion(room, {"Refamide_100_mg", "Exampleamide_100_mg"})
    assert offered["test_formulation"]["value"] == "Exampleamide_100_mg" and offered["test_formulation"]["available"]
    assert "also Exampleamide 100 mg reformulated (reformulated)" in offered["test_formulation"]["source"]
    assert offered["reference_formulation"] == {"value": "Refamide_100_mg", "available": True, "source": (
        "the Data room's question card: Refamide 100 mg (reference), the CPF formulation Refamide_100_mg once sent")}
    # once the reformulated tablet is in the CPF it is the arm the VBE predicts (the question asks about it); the tested
    # product stays named beside it
    sent = vbe_suggestion(room, {"Refamide_100_mg", "Exampleamide_100_mg", "Exampleamide_100_mg_reformulated"})
    assert sent["test_formulation"]["value"] == "Exampleamide_100_mg_reformulated" and sent["test_formulation"]["available"]
    assert sent["test_formulation"]["source"].endswith("; also Exampleamide 100 mg (test)")
    # the observed BE summary, from the room's own NCA paired by subject in the analysis set sent
    view = room_view(DataRoomStore(ws))
    (study,) = view.studies
    members = set(next(s.subjects for s in study.sets if s.name == "modeling"))
    pairs = {n.subject: {} for n in study.nca if n.subject in members}
    for n in study.nca:
        if n.subject in members:
            pairs[n.subject][n.treatment] = n.auc_inf
    t = [v["B"] for v in pairs.values() if v.get("A") and v.get("B")]
    r = [v["A"] for v in pairs.values() if v.get("A") and v.get("B")]
    auc = offered["observed_be"]["metrics"]["AUC_inf"]
    assert auc["n"] == len(t) == 6 and auc["gmr"] == round(paired_crossover_ci(t, r).geometric_mean_ratio, 4)
    assert auc["between_subject_cv_percent"] == round(between_subject_cv(r), 1)
    assert "paired by subject in the proposed modeling set" in offered["observed_be"]["source"]
    # a formulation the CPF does not hold yet is offered, said so; nothing without a confirmed room
    assert not vbe_suggestion(room, set())["test_formulation"]["available"]
    assert vbe_suggestion(None, set()) is None and vbe_suggestion(room.model_copy(update={"confirmed": False}), set()) is None


@pytest.mark.req("T-50")
def test_the_review_pins_the_suggestion_on_the_vbe_application_only(ws):
    room = room_basis(ws)
    cpf = _cpf()
    structure = structure_from_brief(None, room=room).model_copy(update={"model_risk": "medium"})
    assert structure.application_codes == ("APP-11", "APP-14") and [a.template for a in structure.applications] == [
        "vbe-crossover"]
    plan = build_default(cpf, ROWS, structure)
    [vbe] = review_applications(plan, cpf, validate(plan, cpf, ROWS), room=room)["pinned"]
    values = {i["id"]: i["value"] for i in vbe["inputs"]}
    assert values["test_formulation"] is None and values["observed_be"] is None           # suggested, never saved
    assert vbe["suggested"]["test_formulation"]["value"] == "Exampleamide_100_mg_reformulated"   # the arm the question asks about
    [plain] = review_applications(plan, cpf, validate(plan, cpf, ROWS))["pinned"]
    assert plain["suggested"] is None
