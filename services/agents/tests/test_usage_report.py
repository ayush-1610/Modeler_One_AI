"""The agents' token use read from their run records, and priced per Claude model (the owner, 2026-11-10). Synthetic
runs written through the run store itself."""

from __future__ import annotations

import pytest

from modeler_agents.run_store import FileRunStore
from modeler_agents.usage_report import cost, main, read_runs, report

pytestmark = pytest.mark.req("T-20")


def _run(root, agent: str, turns: list[tuple[int, int, int]]) -> str:
    store = FileRunStore(root, project_id="p1")
    run_id = store.start_run(tenant_id="t1", agent=agent, provider="litellm", model="qwen-coder", campaign_id=None,
                             budget={"max_turns": 10})
    for seq, (turn, tokens_in, tokens_out) in enumerate(turns, start=1):
        usage = {"input_tokens": tokens_in, "output_tokens": tokens_out}
        store.record_step(run_id=run_id, seq=seq, kind="model_turn", content={"type": "model_turn", "turn": turn,
                                                                               "usage": usage}, usage=usage)
        store.record_step(run_id=run_id, seq=seq, kind="tool_result", content={"type": "tool_result"}, usage={})
    store.finish_run(run_id=run_id, status="COMPLETED", input_tokens=sum(t[1] for t in turns),
                     output_tokens=sum(t[2] for t in turns), cost_usd=0.0, summary={})
    return run_id


def test_one_conversation_is_priced_without_and_with_its_history_cached(tmp_path):
    _run(tmp_path, "A1-proposal-intake", [(1, 1000, 100), (2, 1500, 100), (3, 2200, 100)])
    (run,) = read_runs(tmp_path)
    assert (run.input_tokens, run.output_tokens, len(run.turns)) == (4700, 300, 3)
    # uncached: 4,700 input at $4 and 300 output at $20 per million
    assert cost(run, "claude-opus-5-5", cached=False) == pytest.approx((4700 * 4 + 300 * 20) / 1e6)
    # cached: each turn writes only what is new (1,000, 500, 700 at $5) and reads what it sent before (1,000, 1,500 at $0.20)
    assert cost(run, "claude-opus-5-5", cached=True) == pytest.approx((2200 * 5 + 2500 * 0.2 + 300 * 20) / 1e6)


def test_interleaved_conversations_each_read_their_own_history_and_the_shared_prefix(tmp_path):
    # two searches side by side (A2's workers): turn numbers restart, inputs interleave
    _run(tmp_path, "A2-literature", [(1, 800, 50), (1, 900, 50), (2, 1200, 50), (2, 1300, 50)])
    (run,) = read_runs(tmp_path)
    # first conversation writes 800; the second reads the 800 both share and writes 100; each second turn reads its own
    expected = (800 * 5 + (800 * 0.2 + 100 * 5) + (900 * 0.2 + 300 * 5) + (800 * 0.2 + 500 * 5) + 200 * 20) / 1e6
    assert cost(run, "claude-opus-5-5", cached=True) == pytest.approx(expected)


def test_the_report_gives_each_agent_its_runs_tokens_largest_turn_and_costs(tmp_path, capsys):
    _run(tmp_path, "A1-proposal-intake", [(1, 1000, 100), (2, 1500, 100)])
    _run(tmp_path, "A1-proposal-intake", [(1, 3000, 200)])
    _run(tmp_path, "A4-sheet-reading", [(1, 150_000, 10)])
    data = report(read_runs(tmp_path))
    a1 = data["agents"]["A1-proposal-intake"]
    assert (a1["runs"], a1["largest_turn_input"], a1["total_input_tokens"]) == (2, 3000, 5500)
    two_turns, one_turn = sorted(read_runs(tmp_path), key=lambda r: -len(r.turns))[:2]
    assert cost(two_turns, "claude-opus-5-5", cached=True) < cost(two_turns, "claude-opus-5-5", cached=False)
    # a single turn only writes the cache (1.25x) and never reads it back: caching it costs more
    assert cost(one_turn, "claude-opus-5-5", cached=True) > cost(one_turn, "claude-opus-5-5", cached=False)
    # over 100,000 tokens Claude Haiku 5.5 is priced higher ($0.50 / $2.50)
    a4 = data["agents"]["A4-sheet-reading"]
    assert a4["usd_total"]["claude-haiku-5-5"]["uncached"] == pytest.approx((150_000 * 0.5 + 10 * 2.5) / 1e6, abs=0.01)
    assert data["busiest_minute"]["input_tokens"] == 155_500
    assert main(["--root", str(tmp_path)]) == 0
    printed = capsys.readouterr().out
    assert "A1-proposal-intake  (2 runs" in printed and "largest turn        150,000 input tokens" in printed
