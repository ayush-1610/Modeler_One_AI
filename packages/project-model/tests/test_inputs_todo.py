"""T-49: what keeps P4 from ready is listed with what settles it, and a person settles each without leaving the page.

Reproduces the state of a real project (2026-10-06): several accepted values for one parameter, a value filed under a
name the model does not use ("plasma protein binding"), values under the data plan's placeholder ("elim"), a pKa
without acid / base, and a template target (elim.hepatic.{enzyme}.km/vmax).
"""

from __future__ import annotations

import pytest

from modeler_project import ArtifactKind, FileProjectStore, Workspace
from modeler_project.brief import Citation, FieldStatus, empty_brief
from modeler_project.brief_ops import agent_set
from modeler_project.documents import DocumentLibrary
from modeler_project.evidence import EvidenceItem, EvidenceState, SourceRef, SourceType, new_id
from modeler_project.evidence_register import EvidenceError, choose, correct, decide, items, propose
from modeler_project.inputs import assemble, current_cpf, placement, propose_identity_mw, todo
from modeler_project.requirements import derive

pytestmark = pytest.mark.req("T-49")
PAPER = SourceRef(title="Clinical pharmacology review", authors="Doe J", year=2008, locator="Table 2", page=3)


def _accept(ws, target, value, unit=None, conditions=None, by_hand=False):
    """Accepted as on the real project; `by_hand`: the PK-Sim value typed on acceptance (no automatic conversion)."""
    item = propose(ws, EvidenceItem(id=new_id(), target=target, value=value, unit=unit, source_type=SourceType.REGULATORY_REVIEW,
                                    source=PAPER, quote=f"{target} {value}", conditions=conditions or {}), actor="u",
                   value_in_quote=True)
    extra = {"value_pksim": float(value), "unit_pksim": unit} if by_hand else {}
    return decide(ws, item.id, state=EvidenceState.ACCEPTED, reason="checked", by="u", **extra)


@pytest.fixture
def ws(tmp_path):
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    brief = empty_brief("desvenlafaxine", by="u")
    record = '{"PropertyTable": {"Properties": [{"CID": 125017, "MolecularWeight": "263.37"}]}}'
    sha = DocumentLibrary(ws).add_text(record, "pubchem-desvenlafaxine.txt", role="retrieved_record", by="system").content["sha256"]
    brief = agent_set(brief, "drug.pubchem_cid", value="125017", unit=None, status=FieldStatus.RETRIEVED, confidence="A", by="system",
                      citations=(Citation(doc_sha256=sha, page=1, quote='"CID": 125017', locator="PubChem CID 125017"),))
    b = ws.commit(ArtifactKind.BRIEF, "main", brief.to_content(), actor="u", reason="start")
    ws.commit(ArtifactKind.REQUIREMENTS, "main", derive(brief).to_content(), derived_from=[b.ref], actor="u", reason="derived")
    return ws


def test_a_name_the_model_does_not_use_is_kept_out_of_the_cpf():
    assert placement("bind.fu") == "model" and placement("phys.pka.base.0") == "model" and placement("dist.bp_ratio") == "reference"
    assert placement("elim.renal.gfr_fraction") == "process" and placement("elim.hepatic.CYP3A4.km") == "process"
    assert placement("plasma protein binding") is None and placement("elim") is None and placement("elim.biliary.cl") is None


def test_each_open_item_is_listed_with_what_settles_it_and_settled_in_place(ws):
    fu = [_accept(ws, "bind.fu", v, None) for v in (0.70, 0.73)]
    ppb = _accept(ws, "plasma protein binding", 30, "%", by_hand=True)
    elim = _accept(ws, "elim", 0.45, by_hand=True)
    pka = _accept(ws, "phys.pka", 10.11)
    template = _accept(ws, "elim.hepatic.{enzyme}.km/vmax", 120, "µmol/l", by_hand=True)
    _accept(ws, "phys.logp", 2.29)
    assemble(ws, by="u")
    cpf = current_cpf(ws)
    assert cpf.get("plasma protein binding") is None and cpf.get("elim") is None and cpf.get("bind.fu") is None
    listed = {(t["kind"], t["target"]): t for t in todo(ws)}
    conflict = listed[("conflict", "bind.fu")]
    assert [i["id"] for i in conflict["items"]] == [f.id for f in fu] and conflict["items"][0]["source"]["title"] == PAPER.title
    assert "not a parameter the model uses" in listed[("correct", "plasma protein binding")]["message"]
    assert "elim.renal.gfr_fraction" in listed[("correct", "elim")]["suggestions"]["targets"]
    assert listed[("correct", "elim.hepatic.{enzyme}.km/vmax")]["suggestions"]["targets"] == [
        "elim.hepatic.<enzyme>.km", "elim.hepatic.<enzyme>.vmax"]
    assert "CYP3A4" in listed[("correct", "elim.hepatic.{enzyme}.km/vmax")]["suggestions"]["molecules"]
    assert ("pka", "phys.pka") in listed
    mw = listed[("missing", "phys.mw")]
    assert mw["identity"]["value"] == 263.37 and mw["identity"]["quote"] == '"MolecularWeight": "263.37"'
    assert ("missing", "bind.fu") not in listed and ("missing", "elim") not in listed      # the issues above settle them
    assert listed[("datasets", "observed data")]["items"] == []

    # the person settles each: one value kept, the others rejected with the reason; corrections replace the originals
    assert choose(ws, fu[0].id, reason="equilibrium dialysis in human plasma", by="u") == [fu[1].id]
    decide(ws, ppb.id, state=EvidenceState.REJECTED, reason="percent bound; fu is given separately", by="u")
    renal = correct(ws, elim.id, target="elim.renal.gfr_fraction", reason="renal filtration is the main route", by="u")
    acid_base = correct(ws, pka.id, conditions={"type": "base"}, reason="tertiary amine", by="u")
    km = correct(ws, template.id, target="elim.hepatic.CYP3A4.km", reason="CYP3A4 oxidation (minor)", by="u")
    states = {e.id: e.state for e in items(ws)}
    assert states[elim.id] is EvidenceState.REJECTED and acid_base.state is EvidenceState.ACCEPTED
    assert acid_base.conditions == {"type": "base"}                                  # same parameter: still accepted
    assert renal.state is km.state is EvidenceState.PROPOSED                           # another parameter: accepted again
    assert km.value_pksim == 120 and km.unit_pksim == "µmol/l" and renal.value_pksim == 0.45
    assert "corrected from" in renal.note and renal.quote == elim.quote
    listed = {(t["kind"], t["target"]): t for t in (assemble(ws, by="u"), todo(ws))[1]}
    assert {i["id"] for i in listed[("missing", "elim")]["items"]} == {renal.id, km.id}   # waiting, on the same list
    decide(ws, renal.id, state=EvidenceState.ACCEPTED, reason="fraction of GFR", by="u")
    decide(ws, km.id, state=EvidenceState.ACCEPTED, reason="CYP3A4 Km, recombinant", by="u")
    mw_item = propose_identity_mw(ws, by="u")
    decide(ws, mw_item.id, state=EvidenceState.ACCEPTED, reason="PubChem record of the free base", by="u")
    assemble(ws, by="u")
    cpf = current_cpf(ws)
    assert cpf.get("bind.fu").value == pytest.approx(0.70) and cpf.get("phys.pka.base.0").value == 10.11
    assert cpf.get("elim.renal.gfr_fraction").engine_binding.process == "GlomerularFiltration"
    assert cpf.get("phys.mw").provenance.source_type == "Database"
    left = {(t["kind"], t["target"]) for t in todo(ws)}
    assert not {k for k in left if k[0] in ("conflict", "correct", "pka")}
    assert ("missing", "phys.solubility.ref") in left


def test_a_correction_to_a_name_the_model_does_not_use_is_refused(ws):
    item = _accept(ws, "plasma protein binding", 30, "%", by_hand=True)
    with pytest.raises(EvidenceError, match="not a parameter the model uses"):
        correct(ws, item.id, target="bind.ppb", reason="try", by="u")
    with pytest.raises(EvidenceError, match="template"):
        correct(ws, item.id, target="elim.hepatic.<enzyme>.km", reason="try", by="u")
    # renaming can change what the number means (30 % bound is fu 0.70, not 0.30): the copy is only proposed, its
    # converted value shown for the person to accept or reject
    copy = correct(ws, item.id, target="bind.fu", reason="it is the binding", by="u")
    assert copy.state is EvidenceState.PROPOSED and copy.value_pksim == pytest.approx(0.30)
