"""Agent run lifecycle: persistence, token/cost budgets and provider-failure handling (task T-20).

Every agent invocation is an ``AgentRun``: it opens a row in ``agent_runs`` through a ``RunStore``, appends
one immutable ``agent_steps`` record per model turn (so the audit viewer shows exactly what the agent did),
charges a ``Budget`` for the tokens each turn used, and closes with a terminal status. When a budget limit is
reached the run stops and finishes ``INCOMPLETE``; when the provider is unreachable the run finishes
``LLM_UNAVAILABLE`` and the work is placed on a ``RetryQueue``. The store is a protocol so the same lifecycle
runs against Postgres in production and an in-memory store in tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol


class RunStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    INCOMPLETE = "INCOMPLETE"  # budget or step limit reached before the agent finished
    REFUSED = "REFUSED"
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"


class LLMUnavailableError(RuntimeError):
    """The model provider could not be reached; the run is retryable."""


# Transient provider failures that mean "unavailable, retry later" rather than a bug. Resolved from the
# anthropic SDK when present so we do not hard-depend on its exact class layout.
def _transient_error_types() -> tuple[type[BaseException], ...]:
    types: list[type[BaseException]] = [LLMUnavailableError]
    try:
        import anthropic

        for name in ("APIConnectionError", "RateLimitError", "InternalServerError", "APITimeoutError"):
            exc = getattr(anthropic, name, None)
            if isinstance(exc, type) and issubclass(exc, BaseException):
                types.append(exc)
    except ImportError:  # pragma: no cover - anthropic is a dependency, but keep the module importable
        pass
    return tuple(types)


TRANSIENT_LLM_ERRORS = _transient_error_types()


@dataclass(frozen=True)
class ModelPricing:
    """USD per one million tokens. Approximate and configurable per deployment."""
    input_per_mtok: float
    output_per_mtok: float

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.input_per_mtok + output_tokens * self.output_per_mtok) / 1_000_000


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    @classmethod
    def from_response(cls, response: Any) -> Usage:
        """Read token usage off an Anthropic Messages response (or any object with a ``usage``)."""
        usage = getattr(response, "usage", None)
        if usage is None:
            return cls()
        return cls(input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
                   output_tokens=int(getattr(usage, "output_tokens", 0) or 0))

    def as_dict(self) -> dict[str, int]:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens}


@dataclass
class Budget:
    """Per-run limits and running totals. Any limit left as ``None`` is unlimited."""
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    max_total_tokens: int | None = None
    max_cost_usd: float | None = None
    max_steps: int | None = None
    pricing: ModelPricing | None = None
    # running totals
    input_tokens: int = 0
    output_tokens: int = 0
    steps: int = 0
    cost_usd: float = 0.0

    def charge(self, usage: Usage) -> None:
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.steps += 1
        if self.pricing is not None:
            self.cost_usd += self.pricing.cost(usage.input_tokens, usage.output_tokens)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def exceeded(self) -> bool:
        return self.exceeded_reason is not None

    @property
    def exceeded_reason(self) -> str | None:
        if self.max_input_tokens is not None and self.input_tokens > self.max_input_tokens:
            return f"input tokens {self.input_tokens} > {self.max_input_tokens}"
        if self.max_output_tokens is not None and self.output_tokens > self.max_output_tokens:
            return f"output tokens {self.output_tokens} > {self.max_output_tokens}"
        if self.max_total_tokens is not None and self.total_tokens > self.max_total_tokens:
            return f"total tokens {self.total_tokens} > {self.max_total_tokens}"
        if self.max_cost_usd is not None and self.cost_usd > self.max_cost_usd:
            return f"cost ${self.cost_usd:.4f} > ${self.max_cost_usd:.4f}"
        if self.max_steps is not None and self.steps >= self.max_steps:
            return f"steps {self.steps} >= {self.max_steps}"
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_input_tokens": self.max_input_tokens, "max_output_tokens": self.max_output_tokens,
            "max_total_tokens": self.max_total_tokens, "max_cost_usd": self.max_cost_usd,
            "max_steps": self.max_steps,
        }


class RunStore(Protocol):
    def start_run(self, *, tenant_id: str, agent: str, provider: str, model: str,
                  campaign_id: str | None, budget: dict[str, Any]) -> str: ...

    def record_step(self, *, run_id: str, seq: int, kind: str, content: dict[str, Any], usage: dict[str, int]) -> None: ...

    def record_proposal(self, *, run_id: str, parameter_id: str, value: str | None, unit: str | None,
                        citation: dict[str, Any]) -> str: ...

    def finish_run(self, *, run_id: str, status: str, input_tokens: int, output_tokens: int,
                   cost_usd: float, summary: dict[str, Any]) -> None: ...


class AgentRun:
    """One agent invocation. Records every turn, tracks the budget, and finishes with a terminal status."""

    def __init__(self, store: RunStore, *, tenant_id: str, agent: str, provider: str, model: str,
                 budget: Budget | None = None, campaign_id: str | None = None):
        self.store = store
        self.tenant_id = tenant_id
        self.agent = agent
        self.budget = budget or Budget()
        self.status = RunStatus.RUNNING
        self._seq = 0
        self.run_id = store.start_run(tenant_id=tenant_id, agent=agent, provider=provider, model=model,
                                      campaign_id=campaign_id, budget=self.budget.as_dict())

    def record(self, kind: str, content: dict[str, Any], usage: Usage | None = None) -> None:
        """Append one immutable step and charge its token usage to the budget."""
        if self.status is not RunStatus.RUNNING:
            raise RuntimeError(f"cannot record on a {self.status} run")
        usage = usage or Usage()
        self._seq += 1
        self.store.record_step(run_id=self.run_id, seq=self._seq, kind=kind, content=content, usage=usage.as_dict())
        self.budget.charge(usage)

    def proposal(self, *, parameter_id: str, value: str | None, unit: str | None, citation: dict[str, Any]) -> str:
        return self.store.record_proposal(run_id=self.run_id, parameter_id=parameter_id, value=value,
                                          unit=unit, citation=citation)

    @property
    def over_budget(self) -> bool:
        return self.budget.exceeded

    def stop_for_budget(self) -> None:
        """Finish the run INCOMPLETE because a budget limit was reached."""
        self.finish(RunStatus.INCOMPLETE, summary={"reason": self.budget.exceeded_reason or "budget exhausted"})

    def finish(self, status: RunStatus, *, summary: dict[str, Any] | None = None) -> None:
        if self.status is not RunStatus.RUNNING:
            return
        self.status = status
        self.store.finish_run(run_id=self.run_id, status=str(status), input_tokens=self.budget.input_tokens,
                              output_tokens=self.budget.output_tokens, cost_usd=round(self.budget.cost_usd, 6),
                              summary=summary or {})


class RetryQueue(Protocol):
    def enqueue(self, item: dict[str, Any]) -> None: ...


def on_provider_failure(run: AgentRun, exc: BaseException, *, retry_queue: RetryQueue | None = None) -> None:
    """Finish a run LLM_UNAVAILABLE and queue it for retry. Call from the ``except TRANSIENT_LLM_ERRORS`` clause."""
    run.finish(RunStatus.LLM_UNAVAILABLE, summary={"error": type(exc).__name__, "detail": str(exc)[:500]})
    if retry_queue is not None:
        retry_queue.enqueue({"run_id": run.run_id, "tenant_id": run.tenant_id, "agent": run.agent,
                             "error": type(exc).__name__, "queued_at": datetime.now(UTC).isoformat()})


# --- in-memory implementations (tests, and the reference for the Postgres-backed store) ----------


@dataclass
class _StoredRun:
    run_id: str
    tenant_id: str
    agent: str
    provider: str
    model: str
    campaign_id: str | None
    budget: dict[str, Any]
    status: str = "RUNNING"
    steps: list[dict[str, Any]] = field(default_factory=list)
    proposals: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class InMemoryRunStore:
    """A RunStore for tests. Mirrors the agent_runs / agent_steps / proposals tables (T-20 migration)."""

    def __init__(self) -> None:
        self.runs: dict[str, _StoredRun] = {}
        self._counter = 0

    def start_run(self, *, tenant_id, agent, provider, model, campaign_id, budget) -> str:
        self._counter += 1
        run_id = f"run-{self._counter}"
        self.runs[run_id] = _StoredRun(run_id=run_id, tenant_id=tenant_id, agent=agent, provider=provider,
                                       model=model, campaign_id=campaign_id, budget=budget)
        return run_id

    def record_step(self, *, run_id, seq, kind, content, usage) -> None:
        self.runs[run_id].steps.append({"seq": seq, "kind": kind, "content": content, "usage": usage})

    def record_proposal(self, *, run_id, parameter_id, value, unit, citation) -> str:
        pid = f"prop-{run_id}-{len(self.runs[run_id].proposals) + 1}"
        self.runs[run_id].proposals.append({"proposal_id": pid, "parameter_id": parameter_id, "value": value,
                                            "unit": unit, "citation": citation, "status": "PROPOSED"})
        return pid

    def finish_run(self, *, run_id, status, input_tokens, output_tokens, cost_usd, summary) -> None:
        run = self.runs[run_id]
        run.status = status
        run.input_tokens = input_tokens
        run.output_tokens = output_tokens
        run.cost_usd = cost_usd
        run.summary = summary


class InMemoryRetryQueue:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def enqueue(self, item: dict[str, Any]) -> None:
        self.items.append(item)
