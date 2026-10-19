"""Redesign §3.2: each study's role is proposed by the MS-01 split before any plan, read-only; blinding follows the S5
role from the moment a study is read (D-33)."""

from __future__ import annotations

import pytest

from modeler_project import ArtifactKind, FileProjectStore, Workspace
from modeler_project.blinding import blinded_studies, external_studies
from modeler_project.brief import empty_brief
from modeler_project.dataset_register import propose_dataset
from modeler_project.datasets import ObservedDataset, Origin, Series, new_dataset_id
from modeler_project.inputs import assemble
from modeler_project.requirements import derive
from modeler_project.roles import proposed_roles

pytestmark = pytest.mark.req("T-50")


@pytest.fixture
def ws(tmp_path):
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    brief = empty_brief("Renaldrug", by="u")
    b = ws.commit(ArtifactKind.BRIEF, "main", brief.to_content(), actor="u", reason="start")
    ws.commit(ArtifactKind.REQUIREMENTS, "main", derive(brief).to_content(), derived_from=[b.ref], actor="u", reason="derived")
    for sid, route, dose in (("iv-250", "iv_infusion", 250), ("iv-500", "iv_infusion", 500), ("po-10", "oral", 10),
                             ("po-50", "oral", 50), ("po-100", "oral", 100)):
        propose_dataset(ws, ObservedDataset(
            id=new_dataset_id(), kind="profile", origin=Origin.LITERATURE, time_unit="h", unit="µmol/l",
            demographics_choice="healthy_adult_default",
            study={"study_id": sid, "n": 12, "route": route, "dose_mg": dose, "formulation": "solution",
                   "food_state": "fasted", "n_timepoints": 5, **({"infusion_time_min": 60} if route == "iv_infusion" else {})},
            series=(Series(times=(0.5, 1, 2, 4, 8), values=(20.0, 35.0, 21.0, 9.0, 2.0), n=12),)), actor="u")
    return ws


def test_roles_are_proposed_by_the_split_before_any_plan(ws):
    assert proposed_roles(ws) == {}                                       # nothing assembled yet
    assemble(ws, by="u")
    assert proposed_roles(ws) == {"iv-250": "S1", "iv-500": "S5", "po-10": "S2", "po-50": "S5", "po-100": "S2"}


def test_a_study_proposed_for_s5_is_blinded_from_the_moment_it_is_read(ws):
    assemble(ws, by="u")
    assert external_studies(ws) == {"iv-500", "po-50"}
    assert blinded_studies(ws, {"blinding": {"on": True, "reason": "high risk"}}, "high") == {"iv-500", "po-50"}
    assert blinded_studies(ws, None, "low") == set()                       # blinding off by default below high risk
