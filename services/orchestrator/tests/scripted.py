"""A scripted executor for the non-linear backend's control flow (no engine, no PK-Sim).

Each round's verdict is looked up by (stage, parameter set): `verdicts[(stage, cpf)]` is True (passes), False (fails),
or the name of the parameter set a fit produces (the round fits and the fitted set passes). It exercises sequencing,
propagation, joint refinement and feedback decisions only; every number in a real campaign comes from the engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from modeler_contracts.runs import (
    ActionChoice,
    CampaignRequest,
    RoundDiagnosis,
    RoundEvaluation,
    RoundRunResult,
    S0Readiness,
    StagePlan,
)
from modeler_orchestrator import local_runner
from modeler_orchestrator.local_runner import LocalExecutor, _RoundOutcome


def cpf_name(sha: str) -> str:
    return sha.removeprefix("sha-")


def request(stages: list[str]) -> CampaignRequest:
    return CampaignRequest(campaign_id="camp-s", tenant_id="t1", compound="X", map_id="m", cpf_uri="file:///cpf-A",
                           cpf_sha256="sha-A", stages=stages, stage_budgets_seconds={s: 600 for s in stages})


@dataclass
class ScriptedExecutor(LocalExecutor):
    verdicts: dict = field(default_factory=dict)
    calls: list = field(default_factory=list)

    def _run_round(self, ctx, *, judge_only: bool = False) -> _RoundOutcome:
        cpf = cpf_name(ctx.cpf_sha256)
        self.calls.append((ctx.stage, cpf, ctx.phase))
        verdict = self.verdicts.get((ctx.stage, cpf), True)
        if isinstance(verdict, str) and ctx.pending_action:                     # the fit: a new parameter set
            run = RoundRunResult(results_uri="", cpf_uri=f"file:///cpf-{verdict}", cpf_sha256=f"sha-{verdict}")
            return _RoundOutcome(run_result=run, evaluation=RoundEvaluation(True, True, {}, [f"fitted {verdict}"]),
                                 diagnosis=RoundDiagnosis(), choice=None, notes=[], fitted=True)
        run = RoundRunResult(results_uri="", cpf_uri=ctx.cpf_uri, cpf_sha256=ctx.cpf_sha256)
        if verdict is True:
            return _RoundOutcome(run_result=run, evaluation=RoundEvaluation(True, True, {}, []), diagnosis=RoundDiagnosis(),
                                 choice=None, notes=[])
        evaluation = RoundEvaluation(False, False, {}, [f"{ctx.stage} misses with parameter set {cpf}"])
        if judge_only or verdict is False:
            return _RoundOutcome(run_result=run, evaluation=evaluation,
                                 diagnosis=RoundDiagnosis(escalate=verdict is False and not judge_only,
                                                          escalation_reason="no_permitted_action"), choice=None, notes=[])
        return _RoundOutcome(run_result=run, evaluation=evaluation, diagnosis=RoundDiagnosis(),
                             choice=ActionChoice(action_id="fit phys.logp"), notes=[])

    def _persist(self, request, outcome) -> None:
        pass


def patch_planning(monkeypatch) -> None:
    """Every stage has scenarios; S0 is ready; validation stages judge once."""
    monkeypatch.setattr(local_runner, "plan_campaign", lambda request: S0Readiness(ready=True, findings=[]))
    monkeypatch.setattr(local_runner, "plan_stage", lambda r: StagePlan(
        stage=r.stage, kind="validate" if r.stage in ("S4", "S5") else "fit" if r.stage in ("S1", "S2", "S3", "SJ") else "readiness"))
