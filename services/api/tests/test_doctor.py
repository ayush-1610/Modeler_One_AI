"""The project doctor: a project's state as a shareable report, without observed values or secrets."""

from __future__ import annotations

import pytest

from modeler_api.doctor import main, report
from modeler_project import ArtifactKind, FileProjectStore, Workspace
from modeler_project.brief import empty_brief
from modeler_project.dataset_register import propose_dataset
from modeler_project.datasets import ObservedDataset, Origin, Series, new_dataset_id
from modeler_project.evidence import EvidenceItem, EvidenceState, SourceRef, SourceType, new_id
from modeler_project.evidence_register import decide, propose
from modeler_project.inputs import assemble
from modeler_project.requirements import derive

pytestmark = pytest.mark.req("T-49")


def _project(root):
    ws = Workspace(FileProjectStore(root), "dev", "p-desv")
    brief = empty_brief("desvenlafaxine", by="u")
    b = ws.commit(ArtifactKind.BRIEF, "main", brief.to_content(), actor="u", reason="start")
    ws.commit(ArtifactKind.REQUIREMENTS, "main", derive(brief).to_content(), derived_from=[b.ref], actor="u", reason="derived")
    for target, value in (("bind.fu", 0.70), ("bind.fu", 0.73), ("plasma protein binding", 30.0)):
        item = propose(ws, EvidenceItem(id=new_id(), target=target, value=value, source_type=SourceType.PUBLICATION,
                                        source=SourceRef(title="Review"), quote=f"{target} {value}"), actor="u")
        decide(ws, item.id, state=EvidenceState.ACCEPTED, reason="read", by="u", value_pksim=value)
    propose_dataset(ws, ObservedDataset(
        id=new_dataset_id(), kind="profile", origin=Origin.CLIENT, provider="CLIENT", purpose="external_validation",
        study={"study_id": "230-23-REF", "n": 6, "route": "oral", "dose_mg": 50, "formulation": "mr", "food_state": "fasted",
               "n_timepoints": 3},
        series=(Series(name="001", statistic="individual", times=(1, 2, 4), values=(41.23, 87.65, 95.43)),)), actor="u")
    assemble(ws, by="u")
    return ws


def test_the_report_names_what_stops_each_phase_and_holds_no_observed_values(tmp_path):
    ws = _project(tmp_path)
    text = report(ws)
    assert "drug: **desvenlafaxine**" in text and "P4 " in text
    assert "`bind.fu`" in text and "several accepted (keep one)" in text
    assert "`plasma protein binding`" in text and "not a parameter the model uses" in text
    assert "230-23-REF · proposed · external_validation" in text and "conflict bind.fu" in text
    assert not any(v in text for v in ("41.23", "87.65", "95.43"))


def test_the_command_lists_projects_and_writes_the_report(tmp_path, monkeypatch, capsys):
    _project(tmp_path / "root")
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "api.log").write_text("INFO ok\nERROR boom in inputs:assemble\nINFO Authorization: Bearer secret ERROR\n")
    monkeypatch.setenv("MODELER_READ_ROOT", str(tmp_path / "root"))
    monkeypatch.setenv("MODELER_LOGS", str(logs))
    assert main(["--list"]) == 0 and "dev\tp-desv\tdesvenlafaxine" in capsys.readouterr().out
    assert main(["p-desv"]) == 0
    written = (logs / "doctor-p-desv.md").read_text()
    assert "ERROR boom in inputs:assemble" in written and "secret" not in written
