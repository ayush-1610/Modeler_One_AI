"""The paid models' spend (plan 2026-11-24 §2.4; the owner's decision D3): one call priced at list prices as the usage
page prices runs, the guard in front of a paid model, and the estimate a paid Data room run shows before it starts. No
model is called."""

from __future__ import annotations

import pytest

from modeler_agents.dataroom.cost import SHARES, estimate, files_to_do
from modeler_agents.llm import ChatResult
from modeler_agents.spend import BudgetCapReached, SpendBudget, guard_paid, uses_paid
from modeler_agents.usage_report import call_cost, price_key

pytestmark = pytest.mark.req("T-20")

PAID = ("bedrock", "anthropic")


def test_a_call_is_priced_at_its_models_list_price_with_the_cache_as_claude_reports_it():
    assert price_key("anthropic.claude-opus-5-5") == "claude-opus-5-5"           # Bedrock's id
    assert price_key("claude-sonnet-5-5-20261101") == "claude-sonnet-5-5"        # the direct API's, dated
    assert price_key("nvidia/nemotron-3-ultra") is None
    usage = {"input_tokens": 100_000, "cache_creation_input_tokens": 200_000, "cache_read_input_tokens": 1_000_000,
             "output_tokens": 10_000}
    # Opus 5.5: $4 input, $5 cache write, $0.20 cache read, $20 output, a million tokens
    assert call_cost("anthropic.claude-opus-5-5", usage) == pytest.approx(0.4 + 1.0 + 0.2 + 0.2)
    assert call_cost("some-new-paid-model", {"input_tokens": 1_000_000}) == pytest.approx(4.0)   # priced as the dearest


class _Model:
    def __init__(self, provider: str, model: str = "anthropic.claude-opus-5-5"):
        self.provider, self.model, self.calls, self.fail_fast = provider, model, 0, False

    def complete(self, messages, tools):
        self.calls += 1
        return ChatResult(content="ok", tool_calls=(), finish_reason="stop", usage={"input_tokens": 250_000},
                          model=self.model)


def test_the_guard_refuses_a_paid_call_at_the_cap_and_records_each_call():
    rows = []
    budget = SpendBudget(run_cap=2, month_cap=90, record=rows.append)
    inner = _Model("bedrock")
    guarded = guard_paid(inner, budget, PAID, "A8")
    guarded.fail_fast = True                          # what a chain sets reaches the model itself
    assert inner.fail_fast and guarded.provider == "bedrock" and uses_paid(guarded, PAID)
    guarded.complete([], [])
    guarded.complete([], [])
    with pytest.raises(BudgetCapReached) as reached:
        guarded.complete([], [])
    assert inner.calls == 2 and reached.value.scope == "run" and reached.value.cap == 2
    assert [r["usd"] for r in rows] == [1.0, 1.0] and rows[0]["agent"] == "A8" and rows[0]["input_tokens"] == 250_000
    month = SpendBudget(run_cap=10, month_cap=90, month_spent=lambda: 95.0)
    with pytest.raises(BudgetCapReached) as over:
        guard_paid(_Model("anthropic", "claude-opus-5-5"), month, PAID).complete([], [])
    assert over.value.scope == "month" and "this month's $90 limit" in over.value.said
    free = _Model("groq", "openai/gpt-oss-120b")
    assert guard_paid(free, month, PAID) is free and not uses_paid(free, PAID)


def test_every_agents_paid_calls_are_metered_once_and_a_run_moves_them_behind_its_cap():
    # every agent's paid model is metered with no cap (A1 … A5 only warn); the Data room's run moves the same guard
    # behind its own budget, so each call is recorded once, on the run's budget
    metered, capped = [], []
    meter = SpendBudget(run_cap=None, month_cap=None, record=metered.append)
    inner = _Model("anthropic", "claude-opus-5-5")
    guarded = guard_paid(inner, meter, PAID, "A2")
    for _ in range(3):
        guarded.complete([], [])                       # no cap: never refused
    assert len(metered) == 3 and metered[0]["agent"] == "A2"
    run = SpendBudget(run_cap=10, month_cap=90, record=capped.append)
    assert guard_paid(guarded, run, PAID, "A8") is guarded and guarded.inner is inner
    guarded.complete([], [])
    assert len(metered) == 3 and [r["agent"] for r in capped] == ["A8"] and run.run_spent == pytest.approx(1.0)


def test_a_paid_runs_estimate_follows_the_measured_ratios_and_prices_only_the_paid_agents():
    # ten files of 40,000 characters (10,000 tokens each) on Claude Opus 5.5: §2.2's 10-file delivery
    files = [(f"f{i}.pdf", 40_000) for i in range(10)]
    opus = {a: ("bedrock", "anthropic.claude-opus-5-5") for a in ("A6", "A7", "A8", "A9", "A10")}
    got = estimate(files, opus, PAID)
    assert got["paid"] and (got["calls_low"], got["calls_high"]) == (85, 100)
    assert 500_000 <= got["input_tokens_low"] < got["input_tokens_high"] <= 1_100_000
    assert (got["output_tokens_low"], got["output_tokens_high"]) == (90_000, 130_000)
    # 0.765 M input at $4 and 90 k output × 1.5 at $20 … 0.9 M and 130 k: the plan's "$5–8 without the cache"
    assert (got["usd_low"], got["usd_high"]) == (pytest.approx(5.76), pytest.approx(7.5))
    assert got["usd"] == pytest.approx((got["usd_low"] + got["usd_high"]) / 2, abs=0.01)
    # only the extractor on a paid model: its measured share of the input and of the output (`DELIVERY_TOKENS`)
    share_in, share_out = SHARES["A8"]
    assert 0.8 < share_in < 0.9 and sum(s for s, _o in SHARES.values()) == pytest.approx(1.0)
    mixed = {**{a: ("nvidia", "nvidia/nemotron-3-ultra-550b-a55b") for a in opus}, "A8": opus["A8"]}
    high = (share_in * got["input_tokens_high"] * 4 + share_out * 130_000 * 1.5 * 20) / 1e6
    assert estimate(files, mixed, PAID)["usd_high"] == pytest.approx(high, abs=0.01)
    free = estimate(files, {a: ("litellm", "qwen-coder") for a in opus}, PAID)
    assert not free["paid"] and free["usd"] == 0.0
    # a very large file is read through the tools, a page at a time: its tokens are capped
    assert estimate([("big.pdf", 10_000_000)], opus, PAID)["input_tokens_high"] == round(10 * (4_000 + 20_000 / 2))


def test_the_estimate_counts_only_the_files_still_to_read(tmp_path):
    from modeler_agents.dataroom import run_room
    from modeler_project.dataroom import DataRoomStore
    from modeler_project.dataroom.synthetic import delivery_zip, seed
    from modeler_project.store import FileProjectStore
    from modeler_project.workspace import Workspace

    store = DataRoomStore(Workspace(FileProjectStore(tmp_path), "t1", "p1"))
    store.add_upload("Exampleamide delivery.zip", delivery_zip(), by="u")
    unread = files_to_do(store)                       # not read yet: each file's bytes stand for its characters
    assert len(unread) == 10 and all(chars > 0 for _p, chars in unread)
    run_room(store, chat_for=lambda agent: None, actor="u", stages=["read"], use_ocr=False, workers=1)
    read = dict(files_to_do(store))
    assert 0 < len(read) <= 10 and all(chars > 0 for chars in read.values())
    seed(store, by="test")                            # triage and extraction stored: nothing left to read
    assert files_to_do(store) == []
