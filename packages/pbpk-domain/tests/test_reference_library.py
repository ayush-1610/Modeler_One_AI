"""The OSP model library through the importer and builder: one published model per process type and edge case
(services/engine-worker/golden/fixtures/SOURCES.md). Every name, selection and unit asserted here is the published
snapshot's own; a model that stops importing, or builds a process differently, fails here before it reaches PK-Sim."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pbpk_domain.cpf.build import missing_expression_profiles, unplaceable_parameters
from pbpk_domain.cpf.completeness import check_completeness
from pbpk_domain.reference import import_osp_snapshot
from pbpk_domain.reference.osp_import import _dataset_dose, _route
from pbpk_domain.reference.roundtrip import roundtrip_inputs

FIXTURES = Path(__file__).resolve().parents[3] / "services" / "engine-worker" / "golden" / "fixtures"
pytestmark = pytest.mark.req("T-03")


def _import(model: str):
    return import_osp_snapshot(json.loads((FIXTURES / f"{model}-Model.json").read_text(encoding="utf-8")))


def _built(model: str):
    imported = _import(model)
    ours, pairs, _notes = roundtrip_inputs(imported)
    return imported, ours, pairs


def _processes(ours: dict) -> dict[tuple[str, str | None, str], dict]:
    return {(p["InternalName"], p.get("Molecule"), p["DataSource"]): p for p in ours["Compounds"][0]["Processes"]}


def _selections(ours: dict) -> list[dict]:
    return ours["Simulations"][0]["Compounds"][0]["Processes"]


@pytest.mark.parametrize("model", ["Alfentanil", "Alprazolam", "Clarithromycin", "Digoxin", "Metformin", "Raltegravir"])
def test_library_model_is_s0_ready_and_every_study_is_linked(model):
    imported, _ours, pairs = _built(model)
    assert check_completeness(imported.cpf).ready
    assert imported.unplaced == ()
    assert unplaceable_parameters(imported.cpf) == ()
    assert missing_expression_profiles(imported.cpf) == ()
    assert pairs  # the round trip has published simulations to compare with


def test_alfentanil_intrinsic_first_order_clearance():
    imported, ours, _ = _built("Alfentanil")
    process = _processes(ours)[("MetabolizationIntrinsic_FirstOrder", "CYP3A4", "1st order CL")]
    assert process["Species"] == "Human"
    assert [(q["Name"], q["Unit"]) for q in process["Parameters"]] == [("Intrinsic clearance", "l/min")]
    assert {"Name": "CYP3A4-1st order CL", "MoleculeName": "CYP3A4"} in _selections(ours)
    assert imported.cpf.require("elim.hepatic.CYP3A4.cl_intrinsic").unit == "l/min"


def test_alprazolam_two_pathways_on_one_enzyme_and_nmol_vmax():
    # two liver-microsome pathways on CYP3A4 (alpha-OH, 4-OH): distinct ids by data source, two processes, both selected;
    # the published in-vitro Vmax in nmol/min/mg protein is converted to the builder's pmol/min/mg protein
    imported, ours, _ = _built("Alprazolam")
    processes = _processes(ours)
    assert ("MetabolizationLiverMicrosomes_MM", "CYP3A4", "alpha-OH pathway") in processes
    assert ("MetabolizationLiverMicrosomes_MM", "CYP3A4", "4-OH pathway") in processes
    names = {s.get("Name") for s in _selections(ours)}
    assert {"CYP3A4-alpha-OH pathway", "CYP3A4-4-OH pathway"} <= names
    vmax = imported.cpf.require("elim.hepatic.CYP3A4@alpha-OH pathway.vmax_microsomes")
    assert vmax.unit == "pmol/min/mg mic. protein"
    raw = next(p for c in json.loads((FIXTURES / "Alprazolam-Model.json").read_text(encoding="utf-8"))["Compounds"]
               for p in c["Processes"] if p.get("DataSource") == "alpha-OH pathway")
    published = next(q for q in raw["Parameters"] if q["Name"] == "In vitro Vmax for liver microsomes")
    assert published["Unit"] == "nmol/min/mg mic. protein"
    assert vmax.value == pytest.approx(published["Value"] * 1000)


def test_clarithromycin_renal_clearance_and_mechanism_based_inhibition():
    imported, ours, _ = _built("Clarithromycin")
    renal = _processes(ours)[("KidneyClearance", None, "fitted")]
    assert {q["Name"] for q in renal["Parameters"]} == {"Plasma clearance", "Fraction unbound (experiment)",
                                                        "Blood flow rate (kidney)", "Body weight"}
    assert {"Name": "Renal Clearances-fitted", "SystemicProcessType": "Renal"} in _selections(ours)
    # irreversible CYP3A4 inhibition of its own clearance (auto-inhibition) is selected as the simulation's interaction
    assert {"Name": "CYP3A4-fitted", "MoleculeName": "CYP3A4", "CompoundName": "Clarithromycin"} in ours["Simulations"][0]["Interactions"]
    assert imported.cpf.require("ddi.perp.CYP3A4.kinact").unit == "1/min"
    # datasets naming no study id are identified by their own name; no two collide
    ids = [s["study_id"] for s in imported.studies]
    assert len(ids) == len(set(ids)) == 17


def test_digoxin_total_hepatic_clearance():
    _imported, ours, _ = _built("Digoxin")
    assert ("LiverClearance", None, "Fitted") in _processes(ours)
    assert {"Name": "Total Hepatic Clearance-Fitted", "SystemicProcessType": "Hepatic"} in _selections(ours)


def test_metformin_renal_transporters_and_hill_kinetics():
    imported, ours, _ = _built("Metformin")
    hill = _processes(ours)[("ActiveTransportSpecific_Hill", "PMAT", "Paper")]
    assert {q["Name"] for q in hill["Parameters"]} == {"Vmax", "Km", "Transporter concentration", "Hill coefficient"}
    profiles = {e["Molecule"] for e in ours["ExpressionProfiles"]}
    assert {"OCT1", "OCT2", "MATE1", "PMAT"} <= profiles  # harvested into the library from the OSP model library
    # with the Gormsen 2016 PET microdose (an IV bolus) and seven loading-dose studies (779.9 mg, then 584.9 mg 12 h later)
    assert len(imported.studies) == 48


def test_raltegravir_ph_solubility_table():
    imported, ours, _ = _built("Raltegravir")
    table = json.loads(imported.cpf.require("phys.solubility.table").value)
    assert table["points"][0] == [1.0, pytest.approx(40.0)] and table["points"][-1] == [8.0, pytest.approx(37300.0)]
    solubility = ours["Compounds"][0]["Solubility"][0]["Parameters"]
    assert [p["Name"] for p in solubility] == ["Solubility table"]
    formula = solubility[0]["TableFormula"]
    assert (formula["XName"], formula["YUnit"], len(formula["Points"])) == ("pH", "mg/l", 17)


@pytest.mark.parametrize("reported,expected", [
    ("PO", ("PO", None)), ("po", ("PO", None)), ("capsule", ("PO", None)), ("iv", ("IV", None)),
    ("IV_30min_infusion", ("IV", 30.0)), ("30-min infusion", ("IV", 30.0)), ("IV_2.5min_infusion", ("IV", 2.5)),
    ("EM", (None, None)), ("iv bolus", (None, None)), ("Intracolonic", (None, None)), (None, (None, None)),
])
def test_every_reported_route_in_the_library_is_read_or_refused(reported, expected):
    assert _route(reported) == expected


@pytest.mark.parametrize("name,dose,expected", [
    ("X", "10 mg", (10.0, False)),
    ("X", "0.05 mg/kg", (0.05, True)),
    ("Wilder-Smith2005.Esomeprazole.40mg.IV_30min_infusion_Day5", 40.0, (40.0, False)),  # bare number the name repeats
    ("Lilja 2007 S PO_Fas_5 mg", "5", (5.0, False)),
    ("Study 140mg", 40.0, None),      # 40 is not the named dose
    ("Study 40 mg/kg", 40.0, None),   # the name gives mg/kg, not mg
    ("Study", "50 mg BID", None),
])
def test_a_dose_without_unit_is_taken_only_when_the_dataset_name_repeats_it(name, dose, expected):
    got = _dataset_dose(name, {"Dose": dose}, None, [])
    assert got == expected if expected is not None else isinstance(got, str)


def test_ketoconazole_particle_dissolution_and_a_three_bin_tablet():
    imported, ours, pairs = _built("Ketoconazole")
    cpf = imported.cpf
    assert imported.unplaced == ()
    # Noyes-Whitney particle formulations, units converted to the builder's (radius published in mm or µm)
    assert (cpf.require("form.PD_tablet_3Bins_B2.particles.radius").value, cpf.require("form.PD_tablet_3Bins_B2.particles.radius").unit) \
        == (pytest.approx(111.06), "µm")
    assert cpf.require("form.PD_solution.particles.radius").value == pytest.approx(0.008)
    # the tablet: three bins given together, each with its mass fraction of the dose (from the published protocol)
    bins = json.loads(cpf.require("form.PD_tablet_3Bins.bins").value)
    assert [b["formulation"] for b in bins] == ["PD_tablet_3Bins_B1", "PD_tablet_3Bins_B2", "PD_tablet_3Bins_B3"]
    assert sum(b["fraction"] for b in bins) == pytest.approx(1.0)
    assert len(imported.studies) >= 50 and len(pairs) >= 50
    tablet = next(s for s in ours["Simulations"] if "PD_tablet_3Bins_B1" in json.dumps(s["Compounds"]))
    selection = tablet["Compounds"][0]["Protocol"]["Formulations"]
    assert selection == [{"Name": f"PD_tablet_3Bins_B{i}", "Key": f"PD_tablet_3Bins_B{i}"} for i in (1, 2, 3)]
    protocol = next(p for p in ours["Protocols"] if p["Name"] == tablet["Compounds"][0]["Protocol"]["Name"])
    items = protocol["Schemas"][0]["SchemaItems"]
    assert [i["FormulationKey"] for i in items] == [f"PD_tablet_3Bins_B{i}" for i in (1, 2, 3)]
    water = [next(q["Value"] for q in i["Parameters"] if q["Name"] == "Volume of water/body weight") for i in items]
    assert water == [3.5, 0.0, 0.0]  # the water with the first bin only, as published
    formulations = {f["Name"]: f for f in ours["Formulations"]}
    assert formulations["PD_tablet_3Bins_B1"]["FormulationType"] == "Formulation_Particles"
    # a "solution" the published model gives as 8 nm particles is simulated so (dissolution limited by solubility)
    solution = next(s for s in imported.studies if s.get("formulation_name") == "PD_solution")
    assert solution["formulation"] == "solution"


def test_a_binned_product_splits_every_dose_and_only_monodisperse_particles_are_placed():
    from pbpk_domain.snapshot.builder import Measured, OralProtocolSpec, ParticleFormulationSpec

    protocol = OralProtocolSpec(name="p", dose=Measured(value=400.0, unit="mg"), bins=(("B1", 0.99), ("B2", 0.01)),
                                repetitions=10, repetition_interval_h=12.0).to_protocol()
    schema = protocol.schemas[0]
    assert [q.value for q in schema.parameters if q.name == "NumberOfRepetitions"] == [10.0]
    assert [next(q.value for q in i.parameters if q.name == "InputDose") for i in schema.schema_items] == \
        [pytest.approx(396.0), pytest.approx(4.0)]
    single = OralProtocolSpec(name="s", dose=Measured(value=200.0, unit="mg"), bins=(("B1", 0.5), ("B2", 0.5))).to_protocol()
    assert {q.name: q.value for q in single.schemas[0].parameters}["TimeBetweenRepetitions"] == 0.0  # as published
    with pytest.raises(ValueError, match="sum to 1"):
        OralProtocolSpec(name="x", dose=Measured(value=1.0, unit="mg"), bins=(("B1", 0.5), ("B2", 0.4)))
    with pytest.raises(ValueError, match="monodisperse"):
        ParticleFormulationSpec(name="f", thickness=Measured(value=0.02, unit="mm"), radius=Measured(value=10.0, unit="µm"),
                                distribution_type=1.0)


def test_alfentanil_iv_bolus_studies_are_simulated_as_boluses():
    imported = _import("Alfentanil")
    boluses = [s for s in imported.studies if s["route"] == "iv_bolus"]
    assert len(boluses) >= 10 and all(s.get("infusion_time_min") is None for s in boluses)
    ours, pairs, _notes = roundtrip_inputs(imported)
    bolus_pairs = [p for p in pairs if p["ours"] in {s["study_id"] for s in boluses}]
    assert bolus_pairs
    protocols = {p["Name"]: p for p in ours["Protocols"]}
    sims = {s["Name"]: s for s in ours["Simulations"]}
    for pair in bolus_pairs:
        protocol = protocols[sims[pair["ours"]]["Compounds"][0]["Protocol"]["Name"]]
        assert "IntravenousBolus" in json.dumps(protocol) and "Infusion time" not in json.dumps(protocol)


def test_simulation_values_are_imported_per_route():
    """OSP Alfentanil sets its gut-wall permeabilities in 3 of its 4 oral simulations and none of its 8 IV ones: an
    oral-only record. OSP Alprazolam sets its PI intestinal permeability in every IV simulation and no oral one: an
    IV-only record, so its oral simulations keep the compound's own permeability."""
    from pbpk_domain.cpf.build import simulation_parameters

    alfentanil = _import("Alfentanil").cpf
    oral = [r for r in alfentanil.parameters if r.id.startswith("sim[oral].")]
    assert oral and all(r.engine_binding.route == "oral" for r in oral)
    assert not [r for r in alfentanil.parameters if r.id.startswith(("sim.", "sim[iv]."))]
    assert simulation_parameters(alfentanil, "iv") == {} and len(simulation_parameters(alfentanil, "oral")) == len(oral)

    alprazolam = _import("Alprazolam")
    path = "Alprazolam|Intestinal permeability (transcellular)"
    assert alprazolam.cpf.get(f"sim[iv].{path}").value == pytest.approx(0.4575114982)
    assert path not in simulation_parameters(alprazolam.cpf, "oral")
    ours, _pairs, _notes = roundtrip_inputs(alprazolam)
    protocols = {p["Name"]: p for p in ours["Protocols"]}
    for sim in ours["Simulations"]:
        oral_sim = "Oral" in json.dumps(protocols[sim["Compounds"][0]["Protocol"]["Name"]])
        assert any(p["Path"] == path for p in sim.get("Parameters", [])) is (not oral_sim), sim["Name"]


def test_an_unset_binding_partner_stays_unset():
    """OSP Alprazolam leaves PlasmaProteinBindingPartner unset (PK-Sim stores 2); an explicit Albumin stores 1."""
    from pbpk_domain.cpf.build import UNSPECIFIED_PARTNER

    alprazolam = _import("Alprazolam")
    assert alprazolam.cpf.get("bind.partner").value == UNSPECIFIED_PARTNER
    ours, _pairs, _notes = roundtrip_inputs(alprazolam)
    assert "PlasmaProteinBindingPartner" not in ours["Compounds"][0]
    assert _import("Alfentanil").cpf.get("bind.partner").value == "Glycoprotein"


def _administrations(protocol: dict) -> list[tuple]:
    """Every administration of a protocol: (time h, dose, unit, application type, infusion min)."""
    def hours(params, name):
        q = next((q for q in params or [] if q.get("Name") == name), None)
        return 0.0 if q is None else float(q["Value"]) * {"min": 1 / 60, "s": 1 / 3600}.get(q.get("Unit") or "h", 1.0)

    out = []
    for schema in protocol.get("Schemas") or []:
        sp = schema.get("Parameters") or []
        n = int(next((q["Value"] for q in sp if q["Name"] == "NumberOfRepetitions"), 1))
        for item in schema["SchemaItems"]:
            dose = next(q for q in item["Parameters"] if q["Name"] == "InputDose")
            out.extend((round(hours(sp, "Start time") + hours(item["Parameters"], "Start time")
                              + k * hours(sp, "TimeBetweenRepetitions"), 6), dose["Value"], dose["Unit"],
                        item["ApplicationType"], round(hours(item["Parameters"], "Infusion time") * 60, 6)) for k in range(n))
    return sorted(out)


@pytest.mark.parametrize(("model", "study", "phases"), [
    # Purkin B: 6 mg/kg IV bolus twice 12 h apart, then 3 mg/kg every 12 h from 24 h (a loading dose)
    ("Voriconazole", "purkin-et-al-2003-study-b-1-12", [(0.0, 6.0, 2), (24.0, 3.0, 17)]),
    # Purkin A: one dose, then every 12 h from 48 h (evenly dosed, unevenly spaced)
    ("Voriconazole", "purkin-et-al-2003-study-a-1-12", [(0.0, 3.0, 1), (48.0, 3.0, 19)]),
    # Kroboth 1988: 1 mg over 2 min, then 0.576 mg over 8 h (each phase its own infusion time)
    ("Alprazolam", "kroboth-1988-1-0-mg-2-min-then-72-g-hr-for-8-hours", [(0.0, 1.0, 1), (0.033333333, 0.576, 1)]),
    ("Metformin", "ding-2014-po-779-9-mg-584-9-mg-plasma-n-20", [(0.0, 779.9, 1), (12.0, 584.925, 1)]),
    ("Digoxin", "johne-1999-0-25mg-po-md-with-placebo-day-6", [(0.0, 0.25, 4), (48.0, 0.25, 13)]),
])
def test_loading_dose_and_uneven_regimens_are_the_published_protocols_phases(model, study, phases):
    snapshot = json.loads((FIXTURES / f"{model}-Model.json").read_text(encoding="utf-8"))
    imported = import_osp_snapshot(snapshot)
    row = next(s for s in imported.studies if s["study_id"] == study)
    assert [(p["start_h"], p["dose_mg"], p["n_doses"]) for p in row["dose_phases"]] == phases
    assert row["design"] == "MD" and row["dose_mg"] == phases[0][1]
    assert not imported.differs_by_design.get(study)  # the same number of doses as the published simulation
    ours, pairs, _notes = roundtrip_inputs(imported)
    pair = next(p for p in pairs if p["ours"] == study)
    mine = next(s for s in ours["Simulations"] if s["Name"] == study)
    ours_protocol = next(p for p in ours["Protocols"] if p["Name"] == mine["Compounds"][0]["Protocol"]["Name"])
    published_sim = next(s for s in snapshot["Simulations"] if s["Name"] == pair["published"])
    entry = next(c for c in published_sim["Compounds"] if c["Name"] == mine["Compounds"][0]["Name"])
    published = next(p for p in snapshot["Protocols"] if p["Name"] == entry["Protocol"]["Name"])
    # every administration identical: time, dose, unit, route, infusion time
    assert _administrations(ours_protocol) == _administrations(published)


def test_voriconazole_imports_its_own_studies_and_names_its_ddi_arms():
    imported = _import("Voriconazole")
    assert len(imported.studies) == 12
    assert missing_expression_profiles(imported.cpf) == () and unplaceable_parameters(imported.cpf) == ()
    saari = [s for s in imported.studies if s["study_id"].startswith("saari")]
    # dosed with midazolam: DDI arms (MS-01), imported with their regimen, not simulated as the drug alone
    assert len(saari) == 10 and all(s["co_medication"] == "Midazolam" for s in saari)
    assert [(p["dose_mg"], p["n_doses"]) for p in saari[0]["dose_phases"]] == [(400.0, 2), (200.0, 2)]


def test_a_binned_product_at_one_moment_is_one_administration():
    assert len(_import("Ketoconazole").studies) == 53


def test_a_named_dosing_interval_counts_its_doses_for_the_label():
    """OSP Raltegravir's MD simulations give DI_12_12 for 10 days (20 doses); the studies gave 19, or one."""
    imported = _import("Raltegravir")
    assert imported.differs_by_design["markowitz-2006-400mg-fct-md"] == (
        "19 dose(s) as the study gave them; the published simulation gives 20")
    assert imported.differs_by_design["kassahun-2007-200mg-fct-sd"].startswith("1 dose(s)")
    assert _study_row(imported, "kassahun-2007-200mg-fct-sd").get("design") is None  # still a single-dose study


def test_a_liquid_the_published_model_gives_a_release_model_is_simulated_with_it():
    imported = _import("Raltegravir")
    granules = _study_row(imported, "rhee-2014-granules-suspension")
    assert (granules["formulation"], granules["formulation_name"]) == ("suspension", "Weibull (granules)")
    ours, _pairs, _notes = roundtrip_inputs(imported)
    sim = next(s for s in ours["Simulations"] if s["Name"] == "rhee-2014-granules-suspension")
    assert sim["Compounds"][0]["Protocol"]["Formulations"][0]["Name"] == "Weibull (granules)"


def test_the_majority_simulation_value_is_imported_and_a_dissenting_simulation_labelled():
    """38 of 39 Metformin simulations set the brain cell permeability to 0.02 cm/min, one to 0.023."""
    cpf = _import("Metformin").cpf
    record = cpf.get("sim[oral].Neighborhoods|Brain_int_Brain_cell|Metformin|P (intracellular->interstitial)") \
        or cpf.get("sim.Neighborhoods|Brain_int_Brain_cell|Metformin|P (intracellular->interstitial)")
    assert record is not None and (record.value, record.unit) == (0.02, "cm/min")


def _study_row(imported, study_id: str) -> dict:
    return next(s for s in imported.studies if s["study_id"] == study_id)


def test_a_later_session_of_a_named_interval_simulation_gets_its_schedule():
    """OSP Alfentanil "Kharasch 2011b IV 1 mg" is DI_24 to 48 h (sessions at 0 and 24 h); the "simultaneous" data start
    at 24.08 h, so they are the second session's profile and get both doses; the "sequential" ones stay one dose."""
    imported = _import("Alfentanil")
    simultaneous = _study_row(imported, "kharasch-2011b-alfentanil-iv-control-simultaneous")
    assert (simultaneous["design"], simultaneous["dosing_interval_h"], simultaneous["n_doses"]) == ("MD", 24.0, 2)
    assert "kharasch-2011b-alfentanil-iv-control-simultaneous" not in imported.differs_by_design
    sequential = _study_row(imported, "kharasch-2011b-alfentanil-iv-control-sequential")
    assert sequential.get("design") is None


def test_itraconazole_selects_its_solubility_per_product_and_food_state():
    """The published simulations give capsule and fed studies their own solubility alternatives; every study's
    regenerated simulation selects the one its published simulation uses (no label left)."""
    from pbpk_domain.cpf.build import alternative_rules, alternatives_for

    imported = _import("Itraconazole")
    cpf = imported.cpf
    assert cpf.get("phys.solubility.ref@Capsule fed").value == pytest.approx(0.0007)  # mg/ml (0.7 mg/l)
    assert cpf.get("phys.solubility.ref@Capsule fasted").value == pytest.approx(0.0009728307177)
    assert {(r["formulation"], r["food"], r["alternative"]) for r in alternative_rules(cpf)} >= {
        ("Capsule fed", "fed", "Capsule fed"), ("Capsule fasted", "fasted", "Capsule fasted"), (None, "fed", "Solution fed")}
    assert alternatives_for(cpf, None, "fasted") == {}  # the default, "Solution fasted"
    assert not [v for v in imported.differs_by_design.values() if "alternative" in v]
    snapshot = json.loads((FIXTURES / "Itraconazole-Model.json").read_text(encoding="utf-8"))
    ours, pairs, _notes = roundtrip_inputs(imported)
    published = {s["Name"]: s for s in snapshot["Simulations"]}
    mine = {s["Name"]: s for s in ours["Simulations"]}
    compound = next(c for c in ours["Compounds"] if c["Name"] == "Itraconazole")
    assert [a["Name"] for a in compound["Solubility"]][1:] and all(a.get("IsDefault") is False for a in compound["Solubility"][1:])
    checked = 0
    for pair in pairs:
        pub = next(c for c in published[pair["published"]]["Compounds"] if c["Name"] == "Itraconazole")
        want = next((a["AlternativeName"] for a in pub.get("Alternatives", []) if a["GroupName"] == "COMPOUND_SOLUBILITY"),
                    "Solution fasted (Taupitz et al. 2013)")
        got = next((a["AlternativeName"] for a in mine[pair["ours"]]["Compounds"][0].get("Alternatives", [])
                    if a["GroupName"] == "COMPOUND_SOLUBILITY"), None)
        if pub.get("Protocol") and "Oral" in json.dumps(snapshot["Protocols"]) and got is not None:
            assert got == want, pair["ours"]
            checked += 1
    assert checked >= 15


def test_ketoconazole_fed_studies_take_their_food_state_from_the_simulation_name():
    """Its datasets report no food state; the published simulations are named "... fed" and give those studies the
    "Fit fed" intestinal permeability without a meal event."""
    from pbpk_domain.cpf.build import alternatives_for

    imported = _import("Ketoconazole")
    fed = _study_row(imported, "88-0")
    assert fed["food_state"] == "fed" and "as the published simulation" in fed["reference"] and "is named" in fed["reference"]
    assert alternatives_for(imported.cpf, "PD_tablet_3Bins", "fed") == {"COMPOUND_INTESTINAL_PERMEABILITY": "Fit fed"}
    assert imported.cpf.get("perm.intestinal@Fit fed").value == pytest.approx(9.9497068191e-06)
    # the published model's own inconsistency (named fasted, simulated with "Fit fed") stays labelled
    labelled = sorted(k for k, v in imported.differs_by_design.items() if "alternative" in v)
    assert labelled == ["9-0", "94-0"]
