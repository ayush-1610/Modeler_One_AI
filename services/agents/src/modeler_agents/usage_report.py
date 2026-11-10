"""What the agents' runs have used, read from the run records the server keeps, to choose the model they move to (the
owner, 2026-11-10: "I need to know what all usage and all tokens we are processing, inputs, outputs, so that I can
correctly pick the model").

Every agent run is recorded under ``<root>/<tenant>/agent_runs/<run_id>/``: ``run.json`` (the run's totals) and
``steps.jsonl`` (each model turn with the tokens the provider reported). From them, per agent: how many runs, how many
turns, the input and output tokens of a run, the largest single turn (the context a model must hold), the busiest
minute (against a provider's tokens-per-minute quota), and what each run would cost on each Claude model at the list
prices below, without and with prompt caching.

How caching is estimated: the agents resend the whole conversation on every turn (`llm.run_tool_loop`), so with the
conversation cached each turn pays the cache-read price for what the previous turn already sent and the cache-write
price only for what is new. Conversations are told apart by their turn numbers (a turn 1 starts one); the system
prompt and tool list a run's conversations share are counted as read after the first. An estimate: the real figure
needs the cache breakpoints in the requests.

The tokens are the current model's (qwen3-coder behind LiteLLM): Claude's tokenizer counts the same text
differently, and Claude's thinking is billed as output, so the output here is a floor. Re-baseline with the provider's
token counting once a key exists. Read-only: nothing is written.

    uv run python -m modeler_agents.usage_report --root "$MODELER_READ_ROOT" [--since 2026-10-01] [--json]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# USD per million tokens: input, 5-minute cache write, cache read, output. Anthropic's first-party list prices, read
# 2026-11-10 from platform.claude.com/docs/en/about-claude/pricing. Amazon Bedrock prices its own (aws.amazon.com/bedrock
# /pricing; a regional endpoint costs 10 % more than the global one).
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5-5": (4.00, 5.00, 0.20, 20.00),
    "claude-sonnet-5-5": (2.00, 2.50, 0.10, 10.00),
    "claude-haiku-5-5": (0.10, 0.125, 0.01, 0.50),
}
HAIKU_LONG = (0.50, 0.625, 0.05, 2.50)        # Claude Haiku 5.5 when a prompt is over 100,000 tokens
HAIKU_LONG_AT = 100_000


@dataclass
class Turn:
    at: datetime | None
    turn: int
    input_tokens: int
    output_tokens: int


@dataclass
class Run:
    run_id: str
    agent: str
    model: str
    status: str
    started_at: datetime | None
    turns: list[Turn] = field(default_factory=list)

    @property
    def input_tokens(self) -> int:
        return sum(t.input_tokens for t in self.turns)

    @property
    def output_tokens(self) -> int:
        return sum(t.output_tokens for t in self.turns)


def _time(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def read_runs(root: Path, since: datetime | None = None) -> list[Run]:
    """Every recorded run under `root` with its model turns (the code-only runs, with no turns, left out)."""
    runs = []
    for record_path in sorted(root.glob("*/agent_runs/*/run.json")):
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        started = _time(record.get("started_at"))
        if since and started and started < since:
            continue
        run = Run(record.get("run_id", record_path.parent.name), str(record.get("agent", "?")),
                  str(record.get("model", "?")), str(record.get("status", "?")), started)
        steps = record_path.parent / "steps.jsonl"
        lines = steps.read_text(encoding="utf-8").splitlines() if steps.exists() else []
        for line in lines:
            try:
                step = json.loads(line)
            except ValueError:
                continue
            usage = step.get("usage") or {}
            if step.get("kind") != "model_turn" or not usage:
                continue
            content = step.get("content") or {}
            run.turns.append(Turn(_time(step.get("at")), int(content.get("turn") or 0),
                                  int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)))
        if run.turns:
            runs.append(run)
    return runs


def _prices(model: str, prompt: int) -> tuple[float, float, float, float]:
    return HAIKU_LONG if model == "claude-haiku-5-5" and prompt > HAIKU_LONG_AT else PRICES[model]


def cost(run: Run, model: str, *, cached: bool) -> float:
    """The run's cost in USD on `model` at list prices, its conversations cached or not."""
    total = 0.0
    if not cached:
        for t in run.turns:
            p_in, _w, _r, p_out = _prices(model, t.input_tokens)
            total += t.input_tokens * p_in + t.output_tokens * p_out
        return total / 1e6
    # each conversation's last input, so a turn reads what its conversation sent before (see the module's note)
    open_: list[tuple[int, int]] = []            # (last turn number, last input) of each open conversation
    shared = min((t.input_tokens for t in run.turns if t.turn <= 1), default=0)   # the prefix every conversation sends
    started = False
    for t in run.turns:
        _p_in, p_write, p_read, p_out = _prices(model, t.input_tokens)
        if t.turn <= 1 or not open_:
            read = shared if started else 0
            started = True
            open_.append((t.turn, t.input_tokens))
        else:
            fits = [i for i, (n, last) in enumerate(open_) if n == t.turn - 1 and last <= t.input_tokens]
            i = max(fits, key=lambda j: open_[j][1]) if fits else max(range(len(open_)), key=lambda j: open_[j][1])
            read = min(open_[i][1], t.input_tokens)
            open_[i] = (t.turn, t.input_tokens)
        total += read * p_read + (t.input_tokens - read) * p_write + t.output_tokens * p_out
    return total / 1e6


def _busiest_minute(runs: list[Run]) -> tuple[int, int]:
    """The most input and output tokens sent within any 60 seconds, across all runs (turns stamped when they ended)."""
    turns = sorted((t for r in runs for t in r.turns if t.at), key=lambda t: t.at)   # type: ignore[arg-type,return-value]
    best_in = best_out = 0
    lo = 0
    window_in = window_out = 0
    for hi, t in enumerate(turns):
        window_in += t.input_tokens
        window_out += t.output_tokens
        while (t.at - turns[lo].at).total_seconds() > 60:  # type: ignore[operator]
            window_in -= turns[lo].input_tokens
            window_out -= turns[lo].output_tokens
            lo += 1
        best_in, best_out = max(best_in, window_in), max(best_out, window_out)
    return best_in, best_out


def _stats(values: list[int]) -> dict[str, int]:
    ordered = sorted(values)
    return {"median": int(statistics.median(ordered)), "p90": ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))],
            "max": ordered[-1]} if ordered else {"median": 0, "p90": 0, "max": 0}


def report(runs: list[Run]) -> dict[str, Any]:
    by_agent: dict[str, list[Run]] = defaultdict(list)
    for run in runs:
        by_agent[run.agent].append(run)
    agents = {}
    for agent, group in sorted(by_agent.items()):
        agents[agent] = {
            "runs": len(group),
            "models": sorted({r.model for r in group}),
            "statuses": {s: sum(1 for r in group if r.status == s) for s in sorted({r.status for r in group})},
            "turns_per_run": _stats([len(r.turns) for r in group]),
            "input_tokens_per_run": _stats([r.input_tokens for r in group]),
            "output_tokens_per_run": _stats([r.output_tokens for r in group]),
            "largest_turn_input": max(t.input_tokens for r in group for t in r.turns),
            "total_input_tokens": sum(r.input_tokens for r in group),
            "total_output_tokens": sum(r.output_tokens for r in group),
            "usd_per_run_median": {m: {"uncached": round(statistics.median(cost(r, m, cached=False) for r in group), 4),
                                       "cached": round(statistics.median(cost(r, m, cached=True) for r in group), 4)}
                                   for m in PRICES},
            "usd_total": {m: {"uncached": round(sum(cost(r, m, cached=False) for r in group), 4),
                              "cached": round(sum(cost(r, m, cached=True) for r in group), 4)} for m in PRICES},
        }
    stamps = [r.started_at for r in runs if r.started_at]
    busiest_in, busiest_out = _busiest_minute(runs)
    return {"runs": len(runs), "from": min(stamps).isoformat() if stamps else None,
            "to": max(stamps).isoformat() if stamps else None, "busiest_minute": {"input_tokens": busiest_in,
                                                                                  "output_tokens": busiest_out},
            "agents": agents, "prices_usd_per_mtok": {m: dict(zip(("input", "cache_write_5m", "cache_read", "output"), p,
                                                                   strict=True)) for m, p in PRICES.items()}}


def _table(data: dict[str, Any]) -> str:
    lines = [f"{data['runs']} runs with model turns, {data['from'] or '?'} to {data['to'] or '?'}",
             (f"busiest minute: {data['busiest_minute']['input_tokens']:,} input and "
              f"{data['busiest_minute']['output_tokens']:,} output tokens"), ""]
    for agent, a in data["agents"].items():
        t, i, o = a["turns_per_run"], a["input_tokens_per_run"], a["output_tokens_per_run"]
        lines += [f"{agent}  ({a['runs']} runs; {', '.join(a['models'])}; "
                  + ", ".join(f"{k} {v}" for k, v in a["statuses"].items()) + ")",
                  f"  turns per run       median {t['median']}, p90 {t['p90']}, max {t['max']}",
                  f"  input per run       median {i['median']:,}, p90 {i['p90']:,}, max {i['max']:,} tokens",
                  f"  output per run      median {o['median']:,}, p90 {o['p90']:,}, max {o['max']:,} tokens",
                  f"  largest turn        {a['largest_turn_input']:,} input tokens",
                  f"  all runs            {a['total_input_tokens']:,} input, {a['total_output_tokens']:,} output",
                  "  USD per run (median)  " + "; ".join(f"{m}: {c['uncached']:.3f} uncached, {c['cached']:.3f} cached"
                                                         for m, c in a["usd_per_run_median"].items()),
                  "  USD all runs          " + "; ".join(f"{m}: {c['uncached']:.2f} uncached, {c['cached']:.2f} cached"
                                                         for m, c in a["usd_total"].items()), ""]
    lines.append("Tokens are the current model's; Claude's tokenizer and thinking change them (see the module's note).")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="What the agents' recorded runs used, and what they would cost.")
    parser.add_argument("--root", required=True, help="the project store root (on the server: \"$MODELER_READ_ROOT\")")
    parser.add_argument("--since", help="only runs started on or after this date (YYYY-MM-DD)")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    since = datetime.fromisoformat(args.since).replace(tzinfo=None) if args.since else None
    runs = read_runs(Path(args.root))
    if since:
        runs = [r for r in runs if not r.started_at or r.started_at.replace(tzinfo=None) >= since]
    data = report(runs)
    print(json.dumps(data, indent=2) if args.json else _table(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
