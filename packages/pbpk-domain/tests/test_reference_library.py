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


def _built(model: str):
    imported = import_osp_snapshot(json.loads((FIXTURES / f"{model}-Model.json").read_text(encoding="utf-8")))
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
    assert len(imported.studies) == 40


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
