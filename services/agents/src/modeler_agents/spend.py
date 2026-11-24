"""A hard cap on paid models' spend (plan 2026-11-24 §2.4; the owner's decision D3: $10 a run, $90 a month, for paid
models only; free and in-house models stay warn-only).

`guard_paid(model, budget, paid)` wraps each model of a paid provider (a chain's paid models, one by one; a free model
is left as it is). Before every call it asks the budget (`SpendBudget.check`): the run's paid spend at or over the run's
cap, or the month's at or over the month's, raises `BudgetCapReached` and no call is made. After a call, its cost at
list prices (`usage_report.call_cost`, the prices of the usage page) is added to the run and recorded (`record`, the
caller's ledger). The call that crosses a cap finishes; the next one is not made. Every agent's paid model is metered
(A1 … A5 behind a budget with no cap, so the month counts their calls too); only the Data room's run is capped.

`BudgetCapReached` is not a provider failure: a chain never moves to its next model on it (a cap is the owner's word,
not an outage), and the Data room's run pauses on it (`modeler_agents.dataroom.run`) until the cap is raised or the agent
is switched to a free model.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Collection
from datetime import UTC, datetime
from typing import Any, Literal

from modeler_agents.usage_report import call_cost


class BudgetCapReached(RuntimeError):
    """A paid model's call refused before it was made: the run's or the month's cap is reached."""

    def __init__(self, scope: Literal["run", "month"], cap: float, spent: float):
        self.scope, self.cap, self.spent = scope, cap, spent
        self.said = (f"the run reached its ${cap:g} limit for paid models (Admin → Limits)" if scope == "run"
                     else f"paid models reached this month's ${cap:g} limit (Admin → Limits)")
        super().__init__(f"{self.said}: ${spent:.2f} spent")


class SpendBudget:
    """One run's caps and what it has spent on paid models. `month_spent` reads the month's paid spend (the ledger every
    paid call of every agent is recorded to, so two runs side by side see each other's); `record` keeps one call's row
    on that ledger. A cap of None is no cap: the budget of an agent that only warns (A1 … A5) records and never stops."""

    def __init__(self, *, run_cap: float | None, month_cap: float | None, run_spent: float = 0.0,
                 month_spent: Callable[[], float] = lambda: 0.0,
                 record: Callable[[dict[str, Any]], None] = lambda row: None):
        self.run_cap = None if run_cap is None else float(run_cap)
        self.month_cap = None if month_cap is None else float(month_cap)
        self.run_spent = float(run_spent)
        self._month_spent = month_spent
        self._record = record
        self._lock = threading.Lock()

    def check(self) -> None:
        with self._lock:
            run = self.run_spent
        if self.run_cap is not None and run >= self.run_cap:
            raise BudgetCapReached("run", self.run_cap, run)
        if self.month_cap is not None and (month := self._month_spent()) >= self.month_cap:
            raise BudgetCapReached("month", self.month_cap, month)

    def add(self, *, provider: str, model: str, usage: dict[str, Any], agent: str = "") -> float:
        usd = call_cost(model, usage)
        with self._lock:
            self.run_spent += usd
        self._record({"at": datetime.now(UTC).isoformat(timespec="seconds"), "agent": agent, "provider": provider,
                      "model": model, "input_tokens": int(usage.get("input_tokens") or 0),
                      "output_tokens": int(usage.get("output_tokens") or 0),
                      "cache_write": int(usage.get("cache_creation_input_tokens") or 0),
                      "cache_read": int(usage.get("cache_read_input_tokens") or 0), "usd": round(usd, 6)})
        return usd


class PaidGuard:
    """A paid chat model behind the budget: everything else (its provider, model, label, `fail_fast` a chain sets) is the
    model's own."""

    def __init__(self, inner: Any, budget: SpendBudget, agent: str = ""):
        self.__dict__.update(inner=inner, budget=budget, agent=agent)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.__dict__["inner"], name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self.__dict__["inner"], name, value)        # a chain's `fail_fast` reaches the model itself

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any:
        inner, budget = self.__dict__["inner"], self.__dict__["budget"]
        budget.check()
        result = inner.complete(messages, tools)
        # priced as the model that answered (Claude's own fallback may have), else as the one asked
        budget.add(provider=inner.provider, model=result.model or inner.model, usage=result.usage, agent=self.__dict__["agent"])
        return result


def is_paid(model: Any, paid: Collection[str]) -> bool:
    return getattr(model, "provider", "") in paid


def _guarded(model: Any, budget: SpendBudget, paid: Collection[str], agent: str) -> Any:
    if isinstance(model, PaidGuard):          # already metered (every agent's model is): now behind this budget, once
        model.__dict__.update(budget=budget, agent=agent or model.__dict__["agent"])
        return model
    return PaidGuard(model, budget, agent) if is_paid(model, paid) else model


def guard_paid(model: Any, budget: SpendBudget, paid: Collection[str], agent: str = "") -> Any:
    """`model` with each of its paid models behind `budget`: a chain's (`FallbackChat.models`) one by one, in place, its
    free models untouched; a single paid model wrapped; a free one returned as it is. A model already behind a budget
    (`agent_jobs.chat_model` meters every agent's) is moved to this one, never wrapped twice, so each call is recorded
    once."""
    if model is None or isinstance(model, str):
        return model
    if hasattr(model, "models") and not isinstance(model, PaidGuard):
        model.models = [_guarded(m, budget, paid, agent) for m in model.models]
        return model
    return _guarded(model, budget, paid, agent)


def uses_paid(model: Any, paid: Collection[str]) -> bool:
    """Whether an agent's model (or the chain it starts with) is a paid one: the model it starts on."""
    first = model.models[0] if hasattr(model, "models") else model
    return first is not None and not isinstance(first, str) and is_paid(first, paid)
