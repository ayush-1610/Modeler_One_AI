from __future__ import annotations

from types import SimpleNamespace

from modeler_agents.strategist import (
    StrategistChoice,
    StrategistProposal,
    StrategyContext,
    decide,
    default_parameters,
    llm_decider,
)


def ctx(**kw) -> StrategyContext:
    base = dict(
        stage="S1",
        permitted_actions=("fit elim.hepatic.{enzyme}.clspec", "fit phys.logp"),
        actions_tried=(),
        evidence=("clearance_off",),
        causes=("Systemic clearance mis-specified",),
    )
    base.update(kw)
    return StrategyContext(**base)


class StubDecider:
    def __init__(self, proposal: StrategistProposal | None = None, raises: Exception | None = None):
        self.proposal, self.raises = proposal, raises

    def propose(self, _ctx):
        if self.raises:
            raise self.raises
        return self.proposal


# --- deterministic fallback ----------------------------------------------------------------------


def test_no_decider_takes_first_permitted() -> None:
    c = decide(ctx())
    assert c.action_id == "fit elim.hepatic.{enzyme}.clspec"
    assert c.source == "fallback"
    assert c.parameters_to_fit == ("elim.hepatic.{enzyme}.clspec",)


def test_skips_tried_actions() -> None:
    c = decide(ctx(actions_tried=("fit elim.hepatic.{enzyme}.clspec",)))
    assert c.action_id == "fit phys.logp"


def test_no_permitted_action_left() -> None:
    c = decide(ctx(actions_tried=("fit elim.hepatic.{enzyme}.clspec", "fit phys.logp")))
    assert c.action_id is None
    assert c.source == "none"


def test_default_parameters() -> None:
    assert default_parameters("fit phys.logp") == ("phys.logp",)
    assert default_parameters("branch dist.partition_method") == ()
    assert default_parameters("switch elim.hepatic.{enzyme}.mm") == (
        "elim.hepatic.{enzyme}.km", "elim.hepatic.{enzyme}.vmax",
    )


# --- constrained by the permitted set ------------------------------------------------------------


def test_strategist_may_choose_a_non_first_permitted_action() -> None:
    c = decide(ctx(), decider=StubDecider(StrategistProposal(action_id="fit phys.logp", rationale="Vss looks off")))
    assert c.action_id == "fit phys.logp"
    assert c.source == "strategist"
    assert c.rationale == "Vss looks off"


def test_disallowed_action_is_rejected_and_falls_back() -> None:
    steps: list[dict] = []
    c = decide(
        ctx(),
        decider=StubDecider(StrategistProposal(action_id="fit perm.intestinal")),  # not permitted at S1
        log_step=steps.append,
    )
    assert c.action_id == "fit elim.hepatic.{enzyme}.clspec"
    assert c.source == "fallback"
    assert any(s["event"] == "rejected" for s in steps)


def test_already_tried_proposal_falls_back() -> None:
    c = decide(
        ctx(actions_tried=("fit elim.hepatic.{enzyme}.clspec",)),
        decider=StubDecider(StrategistProposal(action_id="fit elim.hepatic.{enzyme}.clspec")),
    )
    assert c.action_id == "fit phys.logp"
    assert c.source == "fallback"


def test_decider_error_falls_back() -> None:
    c = decide(ctx(), decider=StubDecider(raises=RuntimeError("boom")))
    assert c.action_id == "fit elim.hepatic.{enzyme}.clspec"
    assert c.source == "fallback"


def test_none_proposal_falls_back() -> None:
    c = decide(ctx(), decider=StubDecider(proposal=None))
    assert c.source == "fallback"


# --- advisory refinements ------------------------------------------------------------------------


def test_valid_bounds_override_is_kept() -> None:
    proposal = StrategistProposal(
        action_id="fit phys.logp", parameters_to_fit=["phys.logp"], bounds_override={"phys.logp": [1.0, 4.0]},
    )
    c = decide(ctx(), decider=StubDecider(proposal))
    assert c.bounds_override == {"phys.logp": (1.0, 4.0)}


def test_malformed_or_foreign_bounds_are_dropped() -> None:
    proposal = StrategistProposal(
        action_id="fit phys.logp", parameters_to_fit=["phys.logp"],
        bounds_override={"phys.logp": [4.0, 1.0], "bind.fu": [0.1, 0.2]},  # inverted; foreign key
    )
    c = decide(ctx(), decider=StubDecider(proposal))
    assert c.bounds_override is None


def test_proposal_is_logged() -> None:
    steps: list[dict] = []
    decide(ctx(), decider=StubDecider(StrategistProposal(action_id="fit phys.logp")), log_step=steps.append)
    assert any(s["event"] == "proposal" for s in steps)


# --- llm_decider over a fake structured-output client --------------------------------------------


def test_llm_decider_reads_parsed_output() -> None:
    proposal = StrategistProposal(action_id="fit phys.logp", rationale="from the model")

    class FakeMessages:
        def parse(self, **kwargs):
            assert kwargs["output_format"] is StrategistProposal
            return SimpleNamespace(content=[SimpleNamespace(parsed_output=proposal)])

    fake_llm = SimpleNamespace(
        client=SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages())),
        model="claude-test", request_options={}, beta_options={},
    )
    c = decide(ctx(), decider=llm_decider(fake_llm))
    assert isinstance(c, StrategistChoice)
    assert c.action_id == "fit phys.logp"
    assert c.source == "strategist"
    assert c.rationale == "from the model"
