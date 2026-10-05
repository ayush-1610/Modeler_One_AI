from __future__ import annotations

import pytest

from pbpk_domain.cpf import EngineBinding, ParameterRecord, ParameterStatus, Provenance
from pbpk_domain.pksim_paths import ParameterPathError, pksim_parameter_path

PROV = Provenance(source_type="measured", reference="x")


def rec(pid, value=1.0, unit=None, binding=None):
    return ParameterRecord(id=pid, value=value, unit=unit, status=ParameterStatus.FIXED, provenance=PROV, engine_binding=binding)


# --- compound physicochemistry (harvested {compound}|<name>) -------------------------------------


@pytest.mark.parametrize("pid,name", [
    ("phys.logp", "Lipophilicity"),
    ("bind.fu", "Fraction unbound (plasma, reference value)"),
    ("phys.mw", "Molecular weight"),
    ("phys.solubility.ref", "Solubility at reference pH"),
    ("perm.intestinal", "Specific intestinal permeability (transcellular)"),
    ("perm.cellular", "Permeability"),
])
def test_compound_parameter_paths(pid, name):
    assert pksim_parameter_path(rec(pid), compound="Aciclovir") == f"Aciclovir|{name}"


# --- molecule-based process (harvested {compound}-{molecule}-{data_source}|<name>) ----------------


@pytest.mark.req("T-13")
def test_first_order_clearance_path():
    b = EngineBinding(building_block="Compound", process="MetabolizationSpecific_FirstOrder:CYP3A4",
                      parameter="CLspec/[Enzyme]", data_source="Optimized")
    assert pksim_parameter_path(rec("elim.hepatic.CYP3A4.clspec", binding=b), compound="Example-A") == \
        "Example-A-CYP3A4-Optimized|CLspec/[Enzyme]"


def test_michaelis_menten_paths_use_the_reaction_container():
    for cpf_param, name in (("vmax", "Vmax"), ("km", "Km")):
        b = EngineBinding(building_block="Compound", process="MetabolizationSpecific_MM:CYP3A4",
                          parameter=name, data_source="InVitro")
        assert pksim_parameter_path(rec(f"elim.hepatic.CYP3A4.{cpf_param}", binding=b), compound="Drug") == \
            f"Drug-CYP3A4-InVitro|{name}"


# Harvested from the published PIs' LinkedParameters (OSP model library), one case per shape.
@pytest.mark.req("T-13")
@pytest.mark.parametrize("process,param,compound,expected", [
    ("ActiveTransportSpecific_MM:OCT1", "kcat", "Cimetidine", "Cimetidine|OCT1-Paper|kcat"),
    ("CompetitiveInhibition:CYP3A4", "Ki", "Cimetidine", "Cimetidine|CYP3A4-Paper|Ki"),
    ("Induction:CYP3A4", "EC50", "Carbamazepine", "Carbamazepine|CYP3A4-Paper|EC50"),
    ("rCYP450_MM:CYP1A2", "kcat", "Efavirenz", "Efavirenz-CYP1A2-Paper|kcat"),
    ("MetabolizationIntrinsic_FirstOrder:CYP3A4", "Intrinsic clearance", "Alfentanil",
     "Alfentanil-CYP3A4-Paper|Intrinsic clearance"),
    ("LiverClearance", "Specific clearance", "Cimetidine", "Cimetidine-Total Hepatic Clearance-Paper|Specific clearance"),
])
def test_process_paths_harvested_from_the_published_parameter_identifications(process, param, compound, expected):
    b = EngineBinding(building_block="Compound", process=process, parameter=param, data_source="Paper")
    assert pksim_parameter_path(rec("x", binding=b), compound=compound) == expected


def test_a_process_type_with_no_harvested_path_is_not_fittable():
    b = EngineBinding(building_block="Compound", process="IrreversibleInhibition:CYP3A4", parameter="kinact", data_source="x")
    with pytest.raises(ParameterPathError, match="no harvested path"):
        pksim_parameter_path(rec("ddi.perp.CYP3A4.kinact", binding=b), compound="Drug")


# --- glomerular filtration (harvested Neighborhoods path) -----------------------------------------


def test_gfr_fraction_path():
    b = EngineBinding(building_block="Compound", process="GlomerularFiltration", parameter="GFR fraction", data_source="assumed")
    assert pksim_parameter_path(rec("elim.renal.gfr_fraction", binding=b), compound="RenalDrug") == \
        "Neighborhoods|Kidney_pls_Kidney_ur|RenalDrug|Glomerular Filtration-assumed-RenalDrug|GFR fraction"


# --- gaps are surfaced, never invented -----------------------------------------------------------


def test_unmapped_compound_parameter_raises():
    with pytest.raises(ParameterPathError, match="no harvested compound path"):
        pksim_parameter_path(rec("phys.pka.base.0"), compound="Drug")


def test_process_without_data_source_raises():
    b = EngineBinding(building_block="Compound", process="GlomerularFiltration", parameter="GFR fraction")
    with pytest.raises(ParameterPathError, match="needs a data source"):
        pksim_parameter_path(rec("elim.renal.gfr_fraction", binding=b), compound="Drug")


def test_unknown_process_raises():
    b = EngineBinding(building_block="Compound", process="SomeNewProcess_Model:CYP2D6", parameter="Kd", data_source="x")
    with pytest.raises(ParameterPathError, match="no harvested path for process"):
        pksim_parameter_path(rec("elim.other.CYP2D6.kd", binding=b), compound="Drug")
