"""The project document library as a table (docs/plans/2026-10-28-project-document-library.md, PR 1): each document
with who added it and what the project took from it, computed from what cites it."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from modeler_project import ArtifactKind, FileProjectStore, Workspace
from modeler_project.brief import Citation, FieldStatus, empty_brief
from modeler_project.brief_ops import agent_set
from modeler_project.dataset_register import propose_dataset
from modeler_project.datasets import ObservedDataset, Origin, Series, new_dataset_id
from modeler_project.documents import DocumentLibrary, LibraryError, RelatesTo, document_id, document_record
from modeler_project.evidence import EvidenceItem, SourceRef, SourceType, new_id
from modeler_project.evidence_register import propose
from modeler_project.library import library_rows

pytestmark = pytest.mark.req("T-41")


@pytest.fixture
def ws(tmp_path):
    return Workspace(FileProjectStore(tmp_path), "t1", "p1")


def test_each_document_says_who_added_it_and_what_cites_it(ws):
    library = DocumentLibrary(ws)
    proposal = library.add(b"# Proposal\nObjective: exposure after 10 mg.", "proposal.md", role="proposal", by="u1")
    paper = library.add(b"fu was 9 % in human plasma (equilibrium dialysis).", "paper.md", role="paper", by="agent:a2")
    library.add(b"unrelated notes", "notes.md", role="other", by="u1")
    sha = {v.content["sha256"]: v for v in (proposal, paper)}
    proposal_sha, paper_sha = list(sha)
    brief = agent_set(empty_brief("Drugol", by="u1"), "qoi.text", value="exposure after 10 mg", unit=None,
                      citations=(Citation(doc_sha256=proposal_sha, page=1, quote="exposure after 10 mg"),),
                      status=FieldStatus.EXTRACTED, confidence="A", by="agent:a1")
    ws.commit(ArtifactKind.BRIEF, "main", brief.to_content(), actor="agent:a1", reason="read")
    propose(ws, EvidenceItem(id=new_id(), req_id="REQ-bind.fu", target="bind.fu", value=9, unit="%",
                             source_type=SourceType.PUBLICATION, quote="fu was 9 %",
                             source=SourceRef(doc_sha256=paper_sha, page=1), conditions={"species": "human"}),
            actor="agent:a2", value_in_quote=True)
    propose_dataset(ws, ObservedDataset(
        id=new_dataset_id(), kind="profile", origin=Origin.LITERATURE, time_unit="h", unit="µmol/l",
        source=SourceRef(doc_sha256=paper_sha, page=1, locator="Figure 2"),
        study={"study_id": "iv-5", "n": 8, "route": "iv_bolus", "dose_mg": 5, "formulation": "solution", "food_state": "fasted",
               "n_timepoints": 3},
        series=(Series(times=(0.5, 1, 2), values=(20.0, 10.0, 5.0), n=8),)), actor="agent:a2")

    rows = {r.name: r for r in library_rows(ws)}
    assert list(rows) == ["proposal.md", "paper.md", "notes.md"]                       # oldest first
    assert (rows["proposal.md"].source, rows["proposal.md"].added_by, rows["proposal.md"].versions) == ("person", "u1", 1)
    assert rows["paper.md"].source == "agent" and rows["paper.md"].format == "markdown"
    (brief_use,) = rows["proposal.md"].contributions
    assert (brief_use.kind, brief_use.target, brief_use.value, brief_use.step) == ("brief", "qoi.text", "exposure after 10 mg",
                                                                                    "start")
    uses = {(c.kind, c.target, c.value) for c in rows["paper.md"].contributions}
    assert uses == {("value", "bind.fu", "9 %"), ("dataset", "iv-5", "concentration profile, 1 series")}
    assert rows["notes.md"].contributions == ()                                         # nothing cites it, and it says so


# --- PR 2: what a document relates to, and withdrawal (the owner's answers 11 and 12) ---------------------------------


def _audit(ws, action):
    return [r.event for r in ws.store.audit(ws.tenant_id).records() if r.event.action == action]


def test_a_document_says_what_it_relates_to(ws):
    library = DocumentLibrary(ws)
    doc = library.add(b"Formulation F2: 50 mg ER tablet.", "f2.md", role="annex", by="u1",
                      relates_to=RelatesTo(step="inputs", task="Formulations"))
    sha = doc.content["sha256"]
    (row,) = library_rows(ws)
    assert row.relates_to == RelatesTo(step="inputs", task="Formulations") and row.withdrawn is None
    (event,) = _audit(ws, "document.relate")
    assert (event.actor, event.resource_id) == ("u1", f"p1/{document_id(sha)}")
    # the same bytes again, said to relate elsewhere: the document is not stored twice, what it relates to is updated
    again = library.add(b"Formulation F2: 50 mg ER tablet.", "f2-copy.md", role="annex", by="u2",
                        relates_to=RelatesTo(step="start"))
    assert again.ref == doc.ref and library.entry(sha).relates_to == RelatesTo(step="start", task="")
    assert len(_audit(ws, "document.relate")) == 2
    with pytest.raises(ValidationError):
        RelatesTo(step="model", task="")                                         # not a step of this product


def test_a_withdrawn_document_is_marked_kept_and_hidden_from_the_agents(ws, tmp_path):
    library = DocumentLibrary(ws)
    kept = library.add(b"fu was 9 % in human plasma.", "paper.md", role="paper", by="agent:a2")
    gone = library.add(b"fu was 30 % in rat plasma (wrong compound).", "wrong.md", role="paper", by="agent:a2")
    sha = gone.content["sha256"]
    with pytest.raises(LibraryError, match="say why"):
        library.withdraw(sha, by="u1", reason="  ")
    with pytest.raises(KeyError):
        library.withdraw("0" * 64, by="u1", reason="not ours")
    library.withdraw(sha, by="u1", reason="a different compound")
    library.withdraw(sha, by="u1", reason="again")                                # already withdrawn: nothing changes

    rows = {r.name: r for r in library_rows(ws)}
    assert set(rows) == {"paper.md", "wrong.md"}                                  # still listed, never erased
    assert (rows["wrong.md"].withdrawn.by, rows["wrong.md"].withdrawn.reason) == ("u1", "a different compound")
    assert library.page_text(sha, 1) is not None                                  # the citations already made still check

    agents = DocumentLibrary(ws, for_agents=True)
    assert [document_record(v).name for v in agents.documents()] == ["paper.md"]
    assert agents.by_sha(sha) is None and agents.page_text(sha, 1) is None
    assert {h.title for h in agents.search("fu plasma")} == {"paper.md"}
    assert agents.by_sha(kept.content["sha256"]) is not None
    (event,) = _audit(ws, "document.withdraw")
    assert (event.reason, event.after) == ("a different compound", {"withdrawn": rows["wrong.md"].withdrawn.model_dump()})

    with pytest.raises(LibraryError, match="say why"):
        library.restore(sha, by="u1", reason="")
    library.restore(sha, by="u1", reason="it was the right compound after all")
    assert library.entry(sha).withdrawn is None and agents.by_sha(sha) is not None
    assert len(_audit(ws, "document.restore")) == 1

    # each project's library is its own
    other = DocumentLibrary(Workspace(ws.store, "t1", "p2"))
    other.add(b"fu was 30 % in rat plasma (wrong compound).", "wrong.md", role="paper", by="u1")
    library.withdraw(sha, by="u1", reason="a different compound")
    assert other.entry(sha).withdrawn is None
