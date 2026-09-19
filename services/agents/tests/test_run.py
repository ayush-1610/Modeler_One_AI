from __future__ import annotations

import pytest

from modeler_agents.run import (
    AgentRun,
    Budget,
    InMemoryRetryQueue,
    InMemoryRunStore,
    LLMUnavailableError,
    ModelPricing,
    RunStatus,
    Usage,
    on_provider_failure,
)

PRICING = ModelPricing(input_per_mtok=15.0, output_per_mtok=75.0)


def _run(store, budget=None):
    return AgentRun(store, tenant_id="t1", agent="strategist", provider="anthropic",
                    model="claude-opus-5", budget=budget, campaign_id="camp-1")


# --- persistence: every step recorded, run row opened and closed --------------------------------


def test_steps_are_recorded_and_run_finishes_completed():
    store = InMemoryRunStore()
    run = _run(store)
    run.record("assistant", {"text": "considering clearance"}, Usage(1000, 200))
    run.record("decision", {"action_id": "fit phys.logp"}, Usage(500, 100))
    run.finish(RunStatus.COMPLETED, summary={"action": "fit phys.logp"})

    stored = store.runs[run.run_id]
    assert stored.status == "COMPLETED"
    assert [s["seq"] for s in stored.steps] == [1, 2]  # append-only, ordered
    assert stored.steps[0]["kind"] == "assistant"
    assert stored.input_tokens == 1500 and stored.output_tokens == 300
    assert stored.summary["action"] == "fit phys.logp"


def test_proposals_are_recorded_against_the_run():
    store = InMemoryRunStore()
    run = _run(store)
    pid = run.proposal(parameter_id="phys.logp", value="2.5", unit="Log Units",
                       citation={"source": "doi:x", "quote": "logP 2.5"})
    assert pid.startswith("prop-")
    assert store.runs[run.run_id].proposals[0]["parameter_id"] == "phys.logp"


# --- budgets: exceeding a limit stops the run INCOMPLETE (T-20 acceptance) ------------------------


@pytest.mark.req("T-20")
def test_budget_stop_produces_incomplete():
    store = InMemoryRunStore()
    run = _run(store, budget=Budget(max_total_tokens=2000, pricing=PRICING))

    steps = 0
    for _ in range(10):
        run.record("assistant", {"text": "turn"}, Usage(700, 100))
        steps += 1
        if run.over_budget:
            run.stop_for_budget()
            break

    assert run.status is RunStatus.INCOMPLETE
    stored = store.runs[run.run_id]
    assert stored.status == "INCOMPLETE"
    assert "total tokens" in stored.summary["reason"]
    assert steps == 3  # 3*800 = 2400 > 2000, stops on the third turn


def test_cost_budget_tracks_pricing():
    budget = Budget(max_cost_usd=0.05, pricing=PRICING)
    budget.charge(Usage(1_000_000, 0))  # $15 -> way over
    assert budget.exceeded
    assert "cost" in budget.exceeded_reason


def test_step_budget_limits_turns():
    budget = Budget(max_steps=2)
    budget.charge(Usage(1, 1))
    assert not budget.exceeded
    budget.charge(Usage(1, 1))
    assert budget.exceeded and "steps" in budget.exceeded_reason


def test_unlimited_budget_never_exceeds():
    budget = Budget()
    for _ in range(100):
        budget.charge(Usage(10_000, 10_000))
    assert not budget.exceeded


def test_usage_reads_from_a_response_like_object():
    class Resp:
        class usage:
            input_tokens = 42
            output_tokens = 7
    u = Usage.from_response(Resp())
    assert u.input_tokens == 42 and u.output_tokens == 7
    assert Usage.from_response(object()) == Usage(0, 0)


# --- provider unavailable: finish LLM_UNAVAILABLE and enqueue a retry -----------------------------


def test_provider_failure_marks_unavailable_and_enqueues_retry():
    store = InMemoryRunStore()
    queue = InMemoryRetryQueue()
    run = _run(store)
    try:
        raise LLMUnavailableError("connection reset")
    except LLMUnavailableError as exc:
        on_provider_failure(run, exc, retry_queue=queue)

    assert run.status is RunStatus.LLM_UNAVAILABLE
    assert store.runs[run.run_id].status == "LLM_UNAVAILABLE"
    assert queue.items and queue.items[0]["run_id"] == run.run_id
    assert queue.items[0]["error"] == "LLMUnavailableError"


def test_finish_is_idempotent():
    store = InMemoryRunStore()
    run = _run(store)
    run.finish(RunStatus.COMPLETED)
    run.finish(RunStatus.REFUSED)  # ignored; already terminal
    assert store.runs[run.run_id].status == "COMPLETED"


def test_cannot_record_after_finish():
    store = InMemoryRunStore()
    run = _run(store)
    run.finish(RunStatus.COMPLETED)
    with pytest.raises(RuntimeError, match="cannot record"):
        run.record("assistant", {"text": "late"}, Usage(1, 1))
