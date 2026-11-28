"""The release model chosen on Inputs (the owner's D1; plan 2026-11-26 §8): the Data room sends the Weibull fit with its
suggestion as a proposal; a person confirms it, or holds the formulation for particle dissolution, or takes the Weibull
fit again. The delivery is the made-up Exampleamide one (its reformulated tablet levels off at 87 %)."""

from __future__ import annotations

import pytest

from modeler_project.dataroom import DataRoomStore, room_inputs
from modeler_project.dataroom.assemble import assemble
from modeler_project.dataroom.publish import plan_publication, publish
from modeler_project.dataroom.reading import read_uploads
from modeler_project.dataroom.synthetic import delivery, seed
from modeler_project.evidence import EvidenceState
from modeler_project.release_choice import HELD, HELD_WHY, ReleaseChoiceError, release_states, set_release_model
from modeler_project.store import FileProjectStore
from modeler_project.workspace import Workspace

pytestmark = pytest.mark.req("T-47")

REFORMULATED = "Exampleamide_100_mg_reformulated"


def _sent(tmp_path, *, room_choice: str | None = None):
    """The room with every decision taken as suggested but Inputs' own (the release model too, unless `room_choice`
    takes it in the room), sent into the project."""
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    store = DataRoomStore(ws)
    for name, data in delivery().items():
        store.add_upload(name, data, by="user:m")
    read_uploads(store, use_ocr=False, workers=1)
    seed(store, confirmed=True)
    for _ in range(3):                    # a decision that appears once another is made (the release model) too
        view = assemble(room_inputs(store))
        open_ = [d for d in view.decisions if not d.chosen and not d.on_inputs]
        if not open_:
            break
        for d in open_:
            store.decide(d.id, chosen=d.suggested, reason="as suggested", by="user:m")
    if room_choice:
        store.decide("release-model:Exampleamide 100 mg reformulated", chosen=room_choice, reason="the lab's advice",
                     by="user:m")
    view = assemble(room_inputs(store))
    return ws, view


def test_the_release_model_is_a_proposal_sent_with_the_weibull_fit_and_not_waited_on_in_the_room(tmp_path):
    ws, view = _sent(tmp_path)
    decision = next(d for d in view.decisions if d.id.startswith("release-model:"))
    assert decision.on_inputs and not decision.chosen
    plan = plan_publication(view, by="u")
    assert plan.blocked == ()                                   # not held for it: Inputs decides
    kind = next(e for e in plan.evidence if e.target == f"form.{REFORMULATED}.type")
    model = kind.proposed["release_model"]
    assert (kind.value, model["value"], model["other"]["value"]) == ("Weibull", "weibull", "particles")
    assert "levels off" in model["detail"] or "highest mean is 87 %" in model["why"]
    assert all(e.proposed is None for e in plan.evidence if e.target != kind.target)
    publish(ws, view, by="u", reason="sent")
    states = release_states(ws)
    assert list(states) == [REFORMULATED] and states[REFORMULATED]["state"] == "proposed"
    # a second send of the same data keeps the proposal as it stands (the evidence id leaves it out)
    again = publish(ws, view, by="u", reason="again")
    assert again["evidence"] == 0 and release_states(ws)[REFORMULATED]["state"] == "proposed"


def test_a_room_that_took_the_weibull_fit_sends_no_proposal_and_one_that_took_particles_still_blocks(tmp_path):
    _ws, view = _sent(tmp_path / "w", room_choice="weibull")
    plan = plan_publication(view, by="u")
    assert plan.blocked == () and all(e.proposed is None for e in plan.evidence)
    _ws, view = _sent(tmp_path / "p", room_choice="particles")
    assert any("particle dissolution needs the particle size" in b for b in plan_publication(view, by="u").blocked)


def test_a_person_confirms_holds_or_takes_back_the_release_model_on_inputs(tmp_path):
    from modeler_project.evidence_register import items

    ws, view = _sent(tmp_path)
    publish(ws, view, by="u", reason="sent")
    with pytest.raises(ReleaseChoiceError, match="say why particle dissolution"):
        set_release_model(ws, REFORMULATED, model="particles", reason=" ", by="u")
    with pytest.raises(ReleaseChoiceError, match="no release model waits"):
        set_release_model(ws, "Refamide_100_mg", model="weibull", by="u")
    held = set_release_model(ws, REFORMULATED, model="particles", reason="the plateau is the solubility limit", by="u")
    assert len(held["held"]) >= 3                               # its type, t50 and shape set aside
    state = release_states(ws)[REFORMULATED]
    assert (state["state"], state["reason"], state["by"]) == ("held", "the plateau is the solubility limit", "u")
    mine = [e for e in items(ws) if e.target.startswith(f"form.{REFORMULATED}.")]
    assert all(e.state is EvidenceState.REJECTED and e.decision_reason.startswith(HELD) for e in mine)
    assert all(e.proposed is None for e in mine)               # the proposal is answered
    taken = set_release_model(ws, REFORMULATED, model="weibull", reason="no particle size in the delivery", by="u")
    assert sorted(taken["taken"]) == sorted(held["held"]) and release_states(ws) == {}
    assert all(e.state is EvidenceState.ACCEPTED for e in items(ws) if e.target.startswith(f"form.{REFORMULATED}."))


def test_the_readiness_waits_for_the_answer_and_says_why_a_held_formulation_is_not_built():
    from modeler_project.inputs import readiness
    from pbpk_domain.cpf import CPF

    cpf = CPF(compound="Exampleamide", version="1", parameters=())
    rows = [{"study_id": "EX-01-A", "n": 6, "dose_mg": 100.0, "route": "oral", "design": "SD", "n_timepoints": 8, "formulation": "ir_tablet",
             "formulation_name": REFORMULATED}]
    proposed = {REFORMULATED: {"state": "proposed", "evidence_id": "ev-1", "value": "weibull"}}
    checks = {c["check"]: c for c in readiness(cpf, rows, {"problems": []}, None, None, proposed)["checks"]}
    assert checks["the Data room's proposals confirmed (D1)"]["detail"] == [
        f"{REFORMULATED}: confirm or change its release model (proposed by the Data room)"]
    held = {REFORMULATED: {"state": "held", "evidence_id": "ev-1", "reason": "r", "by": "u"}}
    checks = {c["check"]: c for c in readiness(cpf, rows, {"problems": []}, None, None, held)["checks"]}
    assert checks["formulations of solid studies"]["detail"] == [f"EX-01-A: {REFORMULATED}: {HELD_WHY}"]
    assert checks["the Data room's proposals confirmed (D1)"]["ok"]


def test_a_held_formulations_particle_inputs_are_entered_and_it_is_built_as_particle_dissolution(tmp_path):
    """Registry 1.3: the radius and the unstirred-layer thickness, as the source states them, converted to the builder's
    µm and mm and accepted with the type `Particles`; the CPF then builds the formulation as particle dissolution."""
    from modeler_project.evidence import SourceType
    from modeler_project.evidence_register import items
    from modeler_project.inputs import assemble_cpf, choices
    from modeler_project.release_choice import enter_particles
    from pbpk_domain.cpf.formulations import PARTICLES, cpf_formulation

    ws, view = _sent(tmp_path)
    publish(ws, view, by="u", reason="sent")
    with pytest.raises(ReleaseChoiceError, match="not held for particle dissolution"):
        enter_particles(ws, REFORMULATED, radius=(50, "µm"), thickness=(0.03, "mm"), source_type=SourceType.PUBLICATION,
                        by="u")
    set_release_model(ws, REFORMULATED, model="particles", reason="the plateau is the solubility limit", by="u")
    with pytest.raises(ReleaseChoiceError, match="radius must be above 0"):
        enter_particles(ws, REFORMULATED, radius=(0, "µm"), thickness=(0.03, "mm"), source_type=SourceType.PUBLICATION,
                        by="u")
    with pytest.raises(ReleaseChoiceError, match="PK-Sim unit"):           # a unit no length converts from: none kept
        enter_particles(ws, REFORMULATED, radius=(50, "min"), thickness=(0.03, "mm"), source_type=SourceType.PUBLICATION,
                        by="u")
    assert not [e for e in items(ws) if e.target == f"form.{REFORMULATED}.type" and e.state is EvidenceState.ACCEPTED]
    ids = enter_particles(ws, REFORMULATED, radius=(0.05, "mm"), thickness=(30, "µm"), source_type=SourceType.PUBLICATION,
                          title="Particle size report", quote="d50 100 µm", by="u")
    assert len(ids) == 3 and release_states(ws) == {}
    taken = {e.target.rsplit(".", 1)[-1]: e for e in items(ws) if e.id in ids}
    assert (taken["type"].value, taken["radius"].value_pksim, taken["radius"].unit_pksim) == ("Particles", 50.0, "µm")
    assert (taken["thickness"].value_pksim, taken["thickness"].unit_pksim) == (pytest.approx(0.03), "mm")
    assert all(e.state is EvidenceState.ACCEPTED for e in taken.values())
    cpf, _report, _used = assemble_cpf(ws, "Exampleamide", choices(ws))
    built = cpf_formulation(cpf, REFORMULATED)
    assert (built.type, built.radius_um, built.thickness_mm) == (PARTICLES, 50.0, pytest.approx(0.03))
