"""Model systems: parent, enantiomers and metabolites simulated together (docs/plans/2026-09-24-multi-compound.md).

The published OSP models (fixtures/SOURCES.md) define every link asserted here; nothing is composed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pbpk_domain.campaign.split import StudyRecord
from pbpk_domain.cpf.completeness import check_completeness
from pbpk_domain.cpf.models import CPF
from pbpk_domain.reference.osp_import import import_osp_system
from pbpk_domain.system import Analyte, Formation, ModelSystem

FIXTURES = Path(__file__).resolve().parents[3] / "services" / "engine-worker" / "golden" / "fixtures"
pytestmark = pytest.mark.req("T-03")


def _snapshot(model: str) -> dict:
    return json.loads((FIXTURES / f"{model}-Model.json").read_text(encoding="utf-8"))


def _system(model: str):
    return import_osp_system(_snapshot(model))


def test_a_single_compound_is_a_system_of_one():
    system = ModelSystem.single(CPF(compound="X"))
    assert system.parents == ("X",)
    assert system.products == {"X": {"X": 1.0}}
    assert system.analytes["X"].output_path == "Organism|PeripheralVenousBlood|X|Plasma (Peripheral Venous Blood)"


def test_dose_fractions_are_required_never_defaulted():
    a, b = CPF(compound="R"), CPF(compound="S")
    with pytest.raises(ValueError, match="every parent must be dosed"):
        ModelSystem(name="rac", compounds=(a, b), roles={"R": "parent", "S": "parent"}, products={"R": {"R": 0.5}})
    with pytest.raises(ValueError, match="must be > 0"):
        ModelSystem(name="rac", compounds=(a, b), roles={"R": "parent", "S": "parent"},
                    products={"rac": {"R": 0.5, "S": 0.0}})
    with pytest.raises(ValueError, match="only a parent compound is dosed"):
        ModelSystem(name="m", compounds=(a, b), roles={"R": "parent", "S": "metabolite"}, products={"p": {"S": 1.0}})
    with pytest.raises(ValueError, match="no observer"):
        ModelSystem(name="m", compounds=(a,), roles={"R": "parent"}, products={"p": {"R": 1.0}},
                    analytes={"sum": Analyte(name="sum", kind="observer", observer="nope", output_path="x")})


def test_closure_follows_formation_chains():
    cpfs = tuple(CPF(compound=n) for n in ("pro", "act", "gluc"))
    system = ModelSystem(name="pro", compounds=cpfs, roles={"pro": "parent", "act": "parent", "gluc": "metabolite"},
                         formation=(Formation(compound="pro", internal_name="x", molecule="CES1", data_source="d", metabolite="act"),
                                    Formation(compound="act", internal_name="x", molecule="UGT2B15", data_source="d", metabolite="gluc")),
                         products={"pro": {"pro": 1.0}, "act": {"act": 1.0}})
    assert system.closure(("pro",)) == ("pro", "act", "gluc")
    assert system.closure(("act",)) == ("act", "gluc")


def test_verapamil_racemate_enantiomers_metabolites_and_sums():
    imported = _system("Verapamil")
    s = imported.system
    assert s.roles == {"R-Verapamil": "parent", "R-Norverapamil": "metabolite", "S-Verapamil": "parent",
                       "S-Norverapamil": "metabolite"}
    assert {(f.compound, f.molecule, f.metabolite) for f in s.formation} == {
        ("R-Verapamil", "CYP3A4", "R-Norverapamil"), ("S-Verapamil", "CYP3A4", "S-Norverapamil")}
    # 120 mg verapamil HCl -> 2 x 55.545 mg base in the published protocols: the salt and the racemic split
    assert s.products["R-Verapamil 0.462875 + S-Verapamil 0.462875"] == {"R-Verapamil": 0.462875, "S-Verapamil": 0.462875}
    assert "R-Verapamil 0.925767" in s.products  # an R-verapamil study doses one enantiomer
    # the racemic sums at the paths the published simulations output them (under different compounds)
    assert s.analytes["Sum-Verapamil Plasma (Peripheral Venous Blood)"].output_path == \
        "Organism|PeripheralVenousBlood|R-Verapamil|Sum-Verapamil Plasma (Peripheral Venous Blood)"
    assert s.analytes["Sum-Norverapamil Plasma (Peripheral Venous Blood)"].output_path == \
        "Organism|PeripheralVenousBlood|R-Norverapamil|Sum-Norverapamil Plasma (Peripheral Venous Blood)"
    assert s.observers["Sum-Verapamil"]["Observers"][0]["Formula"]["Formula"].startswith("fQ_art*(C_pls_art_R+C_pls_art_S)")
    analytes = {st["analyte"] for st in imported.studies}
    assert {"Sum-Verapamil Plasma (Peripheral Venous Blood)", "R-Verapamil", "S-Norverapamil"} <= analytes
    ids = [st["study_id"] for st in imported.studies]
    assert len(ids) == len(set(ids))
    for c in s.compounds:
        assert check_completeness(c).ready or s.roles[c.compound] == "metabolite"
    StudyRecord.model_validate({k: v for k, v in imported.studies[0].items() if k in StudyRecord.model_fields})


def test_omeprazole_distinguishes_esomeprazole_from_the_racemate():
    s = _system("Omeprazole").system
    assert s.products["Esomeprazole 1"] == {"Esomeprazole": 1.0}
    assert s.products["Esomeprazole 0.5 + R-omeprazole 0.5"] == {"Esomeprazole": 0.5, "R-omeprazole": 0.5}
    assert s.analytes["Omeprazole Plasma (Peripheral Venous Blood)"].kind == "observer"


def test_dabigatran_prodrug_chain_and_mass_sum():
    imported = _system("Dabigatran")
    s = imported.system
    assert {(f.compound, f.molecule, f.metabolite) for f in s.formation} == {
        ("DabiEtex", "CES1", "Dabigatran"), ("DabiEtex", "CES2", "Dabigatran"), ("Dabigatran", "UGT2B15", "DabiGluc")}
    # dabigatran is given IV in some studies and formed from the prodrug in others: a parent
    assert s.roles["Dabigatran"] == "parent" and s.roles["DabiGluc"] == "metabolite"
    assert s.analytes["SUM"].output_path == "Organism|PeripheralVenousBlood|Dabigatran|SUM"
    assert "Rifampicin" not in s.roles  # a DDI perpetrator, not part of the system
    sums = [st for st in imported.studies if st["analyte"] == "SUM"]
    assert sums and any("observer is defined" in st["reference"] for st in sums)  # those reporting no compartment


def test_dabigatran_runs_its_abcb1_transport_on_the_individuals_pgp():
    """The published simulations select DabiEtex's ``ABCB1-FIT`` transport on the individual's ``P-gp`` (a modified
    profile): selected on ABCB1 with the library's ABCB1 profile, every oral exposure came out ~2-fold off on PK-Sim."""
    from pbpk_domain.cpf.build import PROCESS_SELECTION, process_molecules, selected_molecules
    from pbpk_domain.reference.roundtrip import system_roundtrip_inputs

    imported = _system("Dabigatran")
    etex = imported.system.cpf("DabiEtex")
    record = etex.get("molecule.ABCB1-FIT")
    assert record.value == "P-gp" and record.engine_binding.building_block == PROCESS_SELECTION
    assert selected_molecules(etex) == {"ABCB1-FIT": "P-gp"}
    assert "P-gp" in process_molecules(etex) and "ABCB1" not in process_molecules(etex)
    ours, _pairs, _notes = system_roundtrip_inputs(imported)
    sim = next(s for s in ours["Simulations"] if s["Name"] == "1160-0001-mean-953-200mg")
    etex_sel = next(c for c in sim["Compounds"] if c["Name"] == "DabiEtex")["Processes"]
    assert {"Name": "ABCB1-FIT", "MoleculeName": "P-gp"} in etex_sel
    individual = next(i for i in ours["Individuals"] if i["Name"] == sim["Individual"])
    molecules = {ref.split("|")[0] for ref in individual["ExpressionProfiles"]}
    assert "P-gp" in molecules and "ABCB1" not in molecules
    # the published P-gp profile's values (its "new ref. conc.") reach the individual
    published = next(p for p in _snapshot("Dabigatran")["ExpressionProfiles"] if p["Molecule"] == "P-gp")
    mine = next(p for p in ours["ExpressionProfiles"] if p["Molecule"] == "P-gp"
                and f"P-gp|{p['Species']}|{p['Category']}" in individual["ExpressionProfiles"])
    values = {q["Path"]: q["Value"] for q in mine["Parameters"] if q.get("Value") is not None}
    for q in published["Parameters"]:
        if q.get("Value") is not None:
            assert values[q["Path"]] == pytest.approx(q["Value"], rel=1e-12), q["Path"]


def test_a_selection_mapping_applies_to_interactions_and_leaves_others_alone():
    from pbpk_domain.snapshot.builder import CompetitiveInhibition, CompoundSpec, Measured, SnapshotBuilder

    base = dict(name="K", molecular_weight=Measured(value=500.0, unit="g/mol"),
                lipophilicity=Measured(value=3.0, unit="Log Units"), fraction_unbound=Measured(value=0.1))
    processes = [CompetitiveInhibition(molecule="ABCB1", data_source="W", ki=Measured(value=1.0, unit="µmol/l")),
                 CompetitiveInhibition(molecule="CYP3A4", data_source="W", ki=Measured(value=1.0, unit="µmol/l"))]
    builder = SnapshotBuilder()
    builder.add_compound(CompoundSpec(**base, processes=processes, selected_molecules={"ABCB1-W": "P-gp"}))
    _entry, interactions = builder._simulation_compound("K", None, None)
    assert {"Name": "ABCB1-W", "MoleculeName": "P-gp", "CompoundName": "K"} in interactions
    assert {"Name": "CYP3A4-W", "MoleculeName": "CYP3A4", "CompoundName": "K"} in interactions


def test_a_minority_or_tied_selection_mapping_is_not_imported():
    from pbpk_domain.reference.osp_import import _selection_molecules

    compound = {"Name": "K", "Processes": [{"InternalName": "ActiveTransportSpecific_MM", "Molecule": "ABCB1",
                                            "DataSource": "W"}]}

    def sim(name, molecule):
        return {"Name": name, "Compounds": [{"Name": "K", "Protocol": {"Name": "p"},
                                             "Processes": [{"Name": "ABCB1-W", "MoleculeName": molecule}]}]}

    assert _selection_molecules({"Simulations": [sim("a", "P-gp"), sim("b", "P-gp"), sim("c", "ABCB1")]},
                                compound) == {"ABCB1-W": "P-gp"}
    assert _selection_molecules({"Simulations": [sim("a", "P-gp"), sim("b", "ABCB1")]}, compound) == {}
    assert _selection_molecules({"Simulations": [sim("a", "ABCB1")]}, compound) == {}


def test_itraconazole_imports_its_metabolite_data():
    imported = _system("Itraconazole")
    assert imported.system.closure(("Itraconazole",)) == ("Itraconazole", "Hydroxy-Itraconazole", "Keto-Itraconazole",
                                                          "N-desalkyl-Itraconazole")
    assert sum(st["analyte"] == "Hydroxy-Itraconazole" for st in imported.studies) >= 20


def test_a_verapamil_study_builds_both_enantiomers_their_metabolites_and_the_sums():
    from pbpk_domain.reference.roundtrip import system_roundtrip_inputs

    imported = _system("Verapamil")
    ours, pairs, _notes = system_roundtrip_inputs(imported)
    assert len(pairs) == len(imported.studies)
    sim = next(s for s in ours["Simulations"] if s["Name"] == "backman-1994-verapamil")
    compounds = {c["Name"]: c for c in sim["Compounds"]}
    assert set(compounds) == {"R-Verapamil", "S-Verapamil", "R-Norverapamil", "S-Norverapamil"}
    # each enantiomer dosed by its own protocol at dose x fraction (80 mg x 0.462884); the metabolites only formed
    assert compounds["R-Norverapamil"].get("Protocol") is None
    protocols = {p["Name"]: p for p in ours["Protocols"]}
    for name in ("R-Verapamil", "S-Verapamil"):
        protocol = protocols[compounds[name]["Protocol"]["Name"]]
        dose = next(q for q in protocol["Schemas"][0]["SchemaItems"][0]["Parameters"] if q["Name"] == "InputDose")
        assert dose["Value"] == pytest.approx(80.0 * 0.462883625, rel=1e-6)
    # formation selected with its metabolite, as the published simulations do
    assert {"Name": "CYP3A4-Norverapamil", "MoleculeName": "CYP3A4", "MetaboliteName": "R-Norverapamil"} in \
        compounds["R-Verapamil"]["Processes"]
    # every compound's mechanism-based CYP3A4 inhibition acts (four compounds x MBI + P-gp)
    assert len(sim["Interactions"]) == 8
    assert sim["ObserverSets"] == [{"Name": "Sum-Verapamil"}, {"Name": "Sum-Norverapamil"}]
    assert "Organism|PeripheralVenousBlood|R-Verapamil|Sum-Verapamil Plasma (Peripheral Venous Blood)" in sim["OutputSelections"]
    assert {o["Name"] for o in ours["ObserverSets"]} == {"Sum-Verapamil", "Sum-Norverapamil"}
    pair = next(p for p in pairs if p["ours"] == "backman-1994-verapamil")
    assert pair["output"].endswith("|Sum-Verapamil Plasma (Peripheral Venous Blood)")


@pytest.mark.parametrize("model", ["Omeprazole", "Dabigatran", "Itraconazole"])
def test_every_system_study_with_a_published_simulation_builds(model):
    from pbpk_domain.reference.roundtrip import system_roundtrip_inputs

    imported = _system(model)
    _ours, pairs, notes = system_roundtrip_inputs(imported)
    assert pairs
    assert not [n for n in notes if n.startswith("NOT SIMULATED")]
