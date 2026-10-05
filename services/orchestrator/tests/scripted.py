"""A scripted executor for the non-linear backend's control flow (no engine, no PK-Sim).

Each round's verdict is looked up by (stage, parameter set): `verdicts[(stage, cpf)]` is True (passes), False (fails),
the name of the parameter set a fit produces (the fitted set passes), or (name, passes). Before a fit, a round with a
fit scripted fails and asks for the fit, except the joint stage's baseline, judged by `base[(stage, cpf)]` (default
passes). `gmfe[(stage, cpf)]` is the agreement the joint
stage compares. With `studies[stage]` set, rounds carry per-study results: each study's flags follow the round's
verdict unless `study_ok[(study, cpf)]` says otherwise. It exercises sequencing, propagation, joint refinement and feedback decisions only; every number in a
real campaign comes from the engine.
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
    base: dict = field(default_factory=dict)
    gmfe: dict = field(default_factory=dict)
    joint_ids: tuple = ("phys.logp", "perm.intestinal")
    studies: dict = field(default_factory=dict)
    study_ok: dict = field(default_factory=dict)
    calls: list = field(default_factory=list)

    def _metrics(self, stage: str, cpf: str, passes: bool = True) -> dict:
        g = self.gmfe.get((stage, cpf), 1.3)
        metrics: dict = {"AUC": {"gmfe": g}, "Cmax": {"gmfe": g}}
        if self.studies:
            ok = {sid: self.study_ok.get((sid, cpf), passes) for sid in self.studies.get(stage, [])}
            # a failing study is over-predicted 2.6-fold, a passing one 1.1-fold (for the S5 diagnosis)
            metrics["studies"] = [{"study_id": sid, "auc_in_limits": v, "cmax_in_limits": v,
                                   "group": "fed" if sid.startswith("fed") else "fasted",
                                   "observed_auc": 100.0, "predicted_auc": 110.0 if v else 260.0,
                                   "observed_cmax": 10.0, "predicted_cmax": 11.0 if v else 26.0} for sid, v in ok.items()]
        return metrics

    def _run_round(self, ctx, *, judge_only: bool = False) -> _RoundOutcome:
        cpf = cpf_name(ctx.cpf_sha256)
        self.calls.append((ctx.stage, cpf, ctx.phase, ctx.pending_action))
        verdict = self.verdicts.get((ctx.stage, cpf), True)
        if isinstance(verdict, str | tuple) and ctx.pending_action:            # the fit: a new parameter set
            name, passes = (verdict, True) if isinstance(verdict, str) else verdict
            run = RoundRunResult(results_uri="", cpf_uri=f"file:///cpf-{name}", cpf_sha256=f"sha-{name}")
            return _RoundOutcome(run_result=run, evaluation=RoundEvaluation(passes, passes, self._metrics(ctx.stage, name, passes),
                                                                            [f"fitted {name}"]),
                                 diagnosis=RoundDiagnosis(), choice=None, notes=[], fitted=True)
        if isinstance(verdict, str | tuple):
            # before the fit: the joint stage's baseline passes unless scripted; a fit stage fails and asks to fit
            verdict = self.base.get((ctx.stage, cpf), True if ctx.stage == "SJ" else "fit")
        run = RoundRunResult(results_uri="", cpf_uri=ctx.cpf_uri, cpf_sha256=ctx.cpf_sha256)
        if verdict is True:
            return _RoundOutcome(run_result=run, evaluation=RoundEvaluation(True, True, self._metrics(ctx.stage, cpf), []),
                                 diagnosis=RoundDiagnosis(), choice=None, notes=[])
        evaluation = RoundEvaluation(False, False, self._metrics(ctx.stage, cpf, False), [f"{ctx.stage} misses with parameter set {cpf}"])
        if judge_only or verdict is False:
            return _RoundOutcome(run_result=run, evaluation=evaluation,
                                 diagnosis=RoundDiagnosis(escalate=verdict is False and not judge_only,
                                                          escalation_reason="no_permitted_action"), choice=None, notes=[])
        return _RoundOutcome(run_result=run, evaluation=evaluation, diagnosis=RoundDiagnosis(),
                             choice=ActionChoice(action_id="fit phys.logp"), notes=[])

    def _persist(self, request, outcome) -> None:
        pass

    def _joint_plan(self, cpf_uri, stages):
        from modeler_orchestrator.joint import JointPlan

        return JointPlan(fit_ids=tuple(self.joint_ids), bounds={}, guarded=())

    def _joint_map(self, request, stages, tag):
        return "", "", [f"study-{s}" for s in stages]


def patch_planning(monkeypatch) -> None:
    """Every stage has scenarios; S0 is ready; validation stages judge once."""
    monkeypatch.setattr(local_runner, "plan_campaign", lambda request: S0Readiness(ready=True, findings=[]))
    monkeypatch.setattr(local_runner, "plan_stage", lambda r: StagePlan(
        stage=r.stage, kind={"S4": "validate", "S5": "validate", "SJ": "joint"}.get(
            r.stage, "fit" if r.stage in ("S1", "S2", "S3") else "readiness")))
