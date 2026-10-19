"""Redesign §3.2: the Inputs step shows one row per model input with its sources, and one row per study with its facts,
proposed role, blinding and demographics. Read only; the rows come from the assembly (D-32) and the catalog."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from modeler_project import ArtifactKind, FileProjectStore, Workspace
from modeler_project.brief import empty_brief
from modeler_project.dataset_register import propose_dataset, set_study_facts
from modeler_project.datasets import HUMAN_POPULATIONS, DatasetError, ObservedDataset, Origin, Series, new_dataset_id
from modeler_project.evidence import EvidenceItem, EvidenceState, SourceRef, SourceType, new_id
from modeler_project.evidence_register import decide, propose
from modeler_project.inputs import assemble, set_choice, tab_of, todo
from modeler_project.inputs_view import compound_rows, study_rows
from modeler_project.requirements import derive

pytestmark = pytest.mark.req("T-49")

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def ws(tmp_path):
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    brief = empty_brief("Drugol", by="u")
    b = ws.commit(ArtifactKind.BRIEF, "main", brief.to_content(), actor="u", reason="start")
    ws.commit(ArtifactKind.REQUIREMENTS, "main", derive(brief).to_content(), derived_from=[b.ref], actor="u", reason="derived")
    return ws


def _propose(ws, target, value, unit=None, **conditions):
    return propose(ws, EvidenceItem(id=new_id(), target=target, value=value, unit=unit, source_type=SourceType.PUBLICATION,
                                    source=SourceRef(title="paper"), quote=f"{target} {value}", conditions=conditions),
                   actor="agent:a2", value_in_quote=True)


def _study(ws, sid, route="oral", **study):
    return propose_dataset(ws, ObservedDataset(
        id=new_dataset_id(), kind="profile", origin=Origin.LITERATURE, time_unit="h", unit="µmol/l",
        study={"study_id": sid, "n": 12, "route": route, "dose_mg": 10, "formulation": "solution", "food_state": "fasted",
               "n_timepoints": 5, **study},
        series=(Series(times=(0.5, 1, 2, 4, 8), values=(20.0, 35.0, 21.0, 9.0, 2.0), n=12),)), actor="u")


def test_each_input_shows_its_kept_value_its_agreeing_sources_and_what_waits(ws):
    first, second = _propose(ws, "phys.logp", 2.1), _propose(ws, "phys.logp", 2.2)
    low, high = _propose(ws, "bind.fu", 0.2), _propose(ws, "bind.fu", 0.7)
    for item in (low, high):
        decide(ws, item.id, state=EvidenceState.ACCEPTED, reason="read in the paper", by="u")
    assemble(ws, by="u")
    rows = {r["id"]: r for r in compound_rows(ws, todo(ws))}
    logp = rows["phys.logp"]
    assert (logp["state"], logp["value"], logp["tab"]) == ("kept", 2.1, "compound")
    assert [s["id"] for s in logp["sources"]] == [first.id, second.id]           # one value, both sources (D-32)
    fu = rows["bind.fu"]
    assert fu["state"] == "conflict" and fu["value"] is None and {a["id"] for a in fu["alternatives"]} == {low.id, high.id}
    assert rows["phys.mw"]["state"] == "missing" and rows["phys.mw"]["sources"] == []
    assert (logp["req_id"], rows["phys.mw"]["req_id"]) == ("REQ-phys.logp", "REQ-phys.mw")   # where a typed value is filed


def test_the_tabs_follow_pksims_building_blocks():
    ids = ("phys.logp", "form.tab.weibull.t50", "expr.CYP3A4|t1/2 (liver)", "expr.profile.CYP3A4",
           "sim.Dapagliflozin|Blood/Plasma concentration ratio", "dist.partition_method", "dist.bp_ratio")
    assert [tab_of(i) for i in ids] == ["compound", "formulations", "individuals", "individuals", "settings", "settings",
                                        "compound"]


def test_each_study_shows_its_role_blinding_demographics_and_regimen(ws):
    md = _study(ws, "po-md", design="MD")
    _study(ws, "iv-1", route="iv_infusion", infusion_time_min=60, dose_mg=5)
    left = _study(ws, "po-old")
    set_study_facts(ws, md.id, changes={}, demographics_choice="healthy_adult_default", by="u")
    set_choice(ws, kind="excluded_studies", key="po-old", value="assay not validated", reason="assay not validated", by="u")
    assemble(ws, by="u")
    rows = {r["study_id"]: r for r in study_rows(ws, blinded={"iv-1"})}
    assert rows["po-md"]["demographics"] == "default" and rows["po-md"]["regimen_missing"]
    assert rows["iv-1"]["demographics"] == "missing" and rows["iv-1"]["blinded"] and rows["iv-1"]["role"]
    assert rows["po-md"]["role_source"] == "proposed" and "profile" not in rows["iv-1"]["facts"]
    assert rows["po-old"]["excluded"] == "assay not validated" and rows["po-old"]["dataset_id"] == left.id


def test_a_study_names_only_a_harvested_population(ws):
    ds = _study(ws, "po-1")
    with pytest.raises(DatasetError, match="not a PK-Sim population"):
        set_study_facts(ws, ds.id, changes={"demographics": {"population": "European", "sex": "MALE", "age_years": 30}},
                        by="u")
    entered = set_study_facts(ws, ds.id, changes={"demographics": {"population": "Japanese_Population", "sex": "FEMALE",
                                                                   "age_years": 41}}, by="u")
    assert entered.demographics_choice == "entered"


def test_the_population_list_is_the_engines_own():
    harvested = json.loads((ROOT / "services/engine-worker/golden/catalog.json").read_text())["populations"]["Human"]
    assert set(HUMAN_POPULATIONS) == set(harvested) - {"Pregnant", "Preterm"}
