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
from modeler_project.inputs import (
    PATHWAY_TARGETS,
    assemble,
    elimination_pathways,
    evidence_view,
    pksim_unit,
    placement,
    set_choice,
    tab_of,
    todo,
)
from modeler_project.inputs_view import compound_rows, study_rows
from modeler_project.requirements import RequirementMatrix, derive
from modeler_project.review import review_rows
from pbpk_domain import parameters

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


def test_the_inputs_page_has_a_row_to_fill_for_every_model_input_the_data_plan_owns(ws):
    """Plan 2026-11-14 §3 API 1: a row ("empty") for every exact registry id PK-Sim takes that an item of the data plan
    owns, so a value no to-do asks for can be entered. Empty is not missing: the to-do list, S0 and the review table
    are what they were, and nothing is made up (a family's members and an id no item owns are left out)."""
    _propose(ws, "phys.logp", 2.1)
    assemble(ws, by="u")
    items = todo(ws)
    before = compound_rows(ws, items)
    rows = {r["id"]: r for r in compound_rows(ws, items, empty=True)}
    matrix = RequirementMatrix.from_content(ws.latest(ArtifactKind.REQUIREMENTS, "main").content)
    owned = {i for i in parameters.model_ids()
             if any(i == item.target or i.startswith(item.target + ".") for item in matrix.items)}
    empty = {k: r for k, r in rows.items() if r["state"] == "empty"}
    # with the elimination pathways the builder places with one value (final review OWN-5): process parameters, not
    # model ids, filed under the data plan's elimination item
    pathways = {p["id"] for p in elimination_pathways()}
    assert set(empty) == (owned | pathways) - {r["id"] for r in before} and empty
    assert {"perm.intestinal", "bind.partner", "elim.ehc_fraction"} <= set(empty)
    assert not {"alt.select", "perm.cellular", "dist.partition_method"} & set(rows)          # no item owns them
    for row in empty.values():
        assert placement(row["id"]) == ("process" if row["id"] in pathways else "model")
        assert row["req_id"] is not None and row["tab"] == tab_of(row["id"])
        assert (row["value"], row["sources"], row["alternatives"], row["message"]) == (None, [], [], None)
    assert empty["perm.intestinal"]["req_id"] == "REQ-perm.intestinal"
    # the rows that were there are unchanged; nothing new is missing; the review table is the CPF's alone
    assert [r for r in rows.values() if r["state"] != "empty"] == before
    assert todo(ws) == items and not any(i["kind"] == "missing" and i["target"] in empty for i in items)
    assert [r["id"] for r in review_rows(ws)] == [r["id"] for r in before]
    # a value kept fills the row: it is no longer empty
    decide(ws, _propose(ws, "perm.intestinal", 1.5e-5, "cm/s").id, state=EvidenceState.ACCEPTED, reason="read", by="u")
    assemble(ws, by="u")
    filled = {r["id"]: r for r in compound_rows(ws, todo(ws), empty=True)}
    assert filled["perm.intestinal"]["state"] == "kept"


def test_the_minimum_elimination_pathway_is_asked_for_by_its_pathway_never_as_the_placeholder(ws):
    """Final review OWN-5: the data plan's "elim" (at least one elimination pathway, S0) is filled by choosing a pathway
    first. The pathways offered are the concrete ones the S0 gate counts that one harvested PK-Sim process carries, each
    with the unit its value is stored in (the registry's), never made up; the to-do item about "elim" names them, the
    Compound area has a row to fill each, and a value filed under one meets S0 (the placeholder itself is never placed)."""
    from pbpk_domain.cpf.process_bindings import binding_candidates

    offered = elimination_pathways()
    assert [p["id"] for p in offered] == ["elim.renal.gfr_fraction", "elim.hepatic.total.plasma_clearance"]
    for p in offered:
        assert p["id"] in PATHWAY_TARGETS and not any(r.requirement == "elim" for r in parameters.unmet_s0([p["id"]]))
        (candidate,) = binding_candidates(p["id"])                       # one harvested process takes it
        assert (p["process"], p["parameter"]) == (candidate.process, candidate.parameter)
        family = parameters.storage_family(p["id"])
        assert p["unit"] == (family if isinstance(family, str) and family != "fraction" else None)
    assert {p["id"]: p["unit"] for p in offered} == {"elim.renal.gfr_fraction": None,
                                                    "elim.hepatic.total.plasma_clearance": "ml/min/kg"}
    assemble(ws, by="u")
    (missing,) = [t for t in todo(ws) if t["kind"] == "missing" and t["target"] == "elim"]
    assert missing["pathways"] == offered
    assert all("pathways" not in t for t in todo(ws) if t["target"] != "elim")
    rows = {r["id"]: r for r in compound_rows(ws, todo(ws), empty=True)}
    assert rows["elim"]["state"] == "missing"
    assert rows["elim.hepatic.total.plasma_clearance"]["unit"] == "ml/min/kg"
    assert rows["elim.hepatic.total.plasma_clearance"]["req_id"] == "REQ-elim.pathway"
    # the unit PK-Sim holds a value in, for a value typed there by hand; none for the placeholder (filed first)
    assert (pksim_unit("elim"), pksim_unit("elim.hepatic.total.plasma_clearance"), pksim_unit("phys.logp")) == (None, "ml/min/kg", "")
    assert pksim_unit("elim.hepatic.<enzyme>.km") is None and pksim_unit("elim.renal.total.plasma_clearance") == "ml/min/kg"
    # a value filed under a pathway, in its unit, flows into the CPF and meets S0: "elim" is no longer missing
    cl = _propose(ws, "elim.hepatic.total.plasma_clearance", 3.2, "ml/min/kg")
    assert evidence_view(cl)["pksim_unit"] == "ml/min/kg" and cl.value_pksim == pytest.approx(3.2)
    assemble(ws, by="u")
    assert not [t for t in todo(ws) if t["target"] == "elim"]
    assert {r["id"]: r["state"] for r in compound_rows(ws, todo(ws), empty=True)}["elim.hepatic.total.plasma_clearance"] == "kept"
    # a value held under a kind of parameter (no enzyme named) cannot be checked as it is: its item names the parameters
    # it may be filed under, as a value to correct does; a value held under a parameter PK-Sim takes names none
    _propose(ws, "elim.hepatic.<enzyme>.clspec", 0.8, "l/µmol/min")
    _propose(ws, "bind.fu", 85, "fraction")                              # held: not a fraction as stated
    assemble(ws, by="u")
    held = {t["target"]: t for t in todo(ws) if t["kind"] == "review"}
    assert held["elim.hepatic.<enzyme>.clspec"]["suggestions"]["targets"] == list(PATHWAY_TARGETS)
    assert held["elim.hepatic.<enzyme>.clspec"]["items"][0]["pksim_unit"] is None
    assert "suggestions" not in held["bind.fu"] and held["bind.fu"]["items"][0]["pksim_unit"] == ""


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
