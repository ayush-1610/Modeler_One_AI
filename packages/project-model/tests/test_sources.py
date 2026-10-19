"""D-32: values flow in without a per-item decision, and the source-selection rule picks the one a parameter takes
(agree within 10 %, best source within 2-fold, a person beyond; never averaged). The rule is UNVERIFIED, version 0.1."""

from __future__ import annotations

import pytest

from modeler_project import ArtifactKind, FileProjectStore, Workspace
from modeler_project.brief import empty_brief
from modeler_project.evidence import EvidenceItem, EvidenceState, SourceRef, SourceType, assess, new_id
from modeler_project.evidence_register import decide, propose
from modeler_project.inputs import assemble, current_cpf, inputs_ready, refresh_inputs, todo
from modeler_project.requirements import derive
from modeler_project.sources import compare, held, rule, select

pytestmark = pytest.mark.req("T-49")


def _item(value, *, source=SourceType.PUBLICATION, state=EvidenceState.PROPOSED, target="bind.fu", grade=None, **extra):
    extra.setdefault("quote", f"fu {value}")
    item = assess(EvidenceItem(id=new_id(), target=target, value=value, source_type=source, conditions={"species": "human"},
                               source=SourceRef(title="paper"), **extra), value_in_quote=True)
    return item.model_copy(update={"state": state, **({"confidence": grade} if grade else {})})


def test_the_rule_is_provisional_and_versioned():
    assert (rule().version, rule().status, rule().agreement_relative, rule().conflict_fold) == ("0.1", "UNVERIFIED", 0.10, 2.0)


def test_agreeing_values_are_one_value_with_all_their_sources():
    a, b, c = _item(0.70), _item(0.73), _item(0.75)
    chosen = select([a, b, c])
    assert chosen.kept == a.id and set(chosen.agreeing) == {b.id, c.id} and not chosen.conflict
    assert compare(a, b) == ("agrees", pytest.approx(100 * 0.03 / 0.70))


def test_within_two_fold_the_best_source_wins_and_never_an_average():
    literature = _item(0.50, source=SourceType.PUBLICATION, grade="A")
    client = _item(0.80, source=SourceType.CLIENT_REPORT, grade="B")
    database = _item(0.55, source=SourceType.DATABASE)
    chosen = select([literature, database, client])
    assert chosen.kept == client.id and not chosen.conflict          # the client, then the literature, then PubChem
    assert {a.id: a.relation for a in chosen.alternatives} == {literature.id: "differs", database.id: "differs"}
    within_literature = select([_item(0.5, grade="B"), graded := _item(0.62, grade="A")])
    assert within_literature.kept == graded.id                       # within a source, the higher grade


def test_beyond_two_fold_a_person_keeps_one_and_an_accepted_value_stands_against_proposals():
    a, b = _item(0.20), _item(0.70)
    assert select([a, b]).conflict and select([a, b]).kept is None
    accepted = _item(0.20, state=EvidenceState.ACCEPTED)
    chosen = select([accepted, _item(0.70)])
    assert chosen.kept == accepted.id and not chosen.conflict and chosen.alternatives[0].relation == "conflicts"
    assert select([accepted, _item(0.70, state=EvidenceState.ACCEPTED)]).conflict   # two accepted: still a person's call


def test_words_agree_only_when_equal():
    a = _item("Rodgers", target="dist.partition_method")
    assert compare(a, _item("rodgers ", target="dist.partition_method"))[0] == "agrees"
    assert select([a, _item("Schmitt", target="dist.partition_method")]).conflict


def test_a_flagged_value_is_held_until_a_person_accepts_it():
    bound = _item(30, unit="%", quote="plasma protein binding 30 %")
    assert any(f.startswith("check:") for f in held(bound))
    assert held(bound.model_copy(update={"state": EvidenceState.ACCEPTED})) == ()


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


def test_proposed_values_reach_the_cpf_with_no_acceptance_and_excluded_ones_do_not(ws):
    _propose(ws, "phys.logp", 2.1)
    other = _propose(ws, "phys.logp", 2.2)
    mw = _propose(ws, "phys.mw", 408.9, "g/mol")
    decide(ws, mw.id, state=EvidenceState.REJECTED, reason="the salt's weight", by="u")
    assemble(ws, by="u")
    cpf = current_cpf(ws)
    assert cpf.get("phys.logp").value == 2.1 and other.id in cpf.get("phys.logp").provenance.reference
    assert cpf.get("phys.mw") is None


def test_two_pka_values_of_one_kind_wait_on_a_person(ws):
    first = _propose(ws, "phys.pka", 9.1, type="base")
    second = _propose(ws, "phys.pka", 9.3, type="base")
    assemble(ws, by="u")
    listed = {(t["kind"], t["target"]): t for t in todo(ws)}
    assert {i["id"] for i in listed[("pka", "phys.pka")]["items"]} == {first.id, second.id}
    assert current_cpf(ws).get("phys.pka.base.0") is None and current_cpf(ws).get("phys.pka.base.1") is None
    decide(ws, second.id, state=EvidenceState.REJECTED, reason="same amine, older method", by="u")
    assemble(ws, by="u")
    assert current_cpf(ws).get("phys.pka.base.0").value == 9.1


def test_a_value_proposed_after_the_assembly_flows_in_on_the_next_refresh(ws):
    """A new value is a new artifact, which makes nothing stale: the assembly's key over what it read says it changed."""
    first = _propose(ws, "phys.logp", 2.1)
    assert refresh_inputs(ws, by="u") and inputs_ready(ws)[1] != "the model inputs are not assembled yet"
    assert not refresh_inputs(ws, by="u")                                     # nothing changed: no new assembly
    second = _propose(ws, "phys.logp", 2.2)
    assert "changed since" in inputs_ready(ws)[1]                             # the plan would not read the old inputs
    assert refresh_inputs(ws, by="u")
    reference = current_cpf(ws).get("phys.logp").provenance.reference
    assert first.id not in reference and second.id in reference               # the kept source names the one that agrees
