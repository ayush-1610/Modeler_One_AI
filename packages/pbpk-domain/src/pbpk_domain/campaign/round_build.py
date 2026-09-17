"""Turn a CPF plus the MAP's scenarios into the snapshot a stage simulates (task T-13 wiring).

`build_round_snapshot` (the Temporal activity) is a thin adapter over `build_stage_snapshot` here. Given the
CPF and the MAP scenarios for one stage, this builds the PK-Sim individual for each study's demographics
(MS-01 §2.3) and one simulation per study — protocol, formulation and meal events — then regenerates the
snapshot from the CPF (`pbpk_domain.cpf.build_from_cpf`). The mapping is deterministic and never invents a
value: a study-specific unknown the scenario does not carry (an IV infusion time, an IR/MR dissolution model)
raises `ScenarioBuildError` naming the gap rather than guessing one.

What is deferred, and surfaced as a build note rather than silently dropped:
- expression profiles for the compound's process molecules (needed for the run; the CPF does not yet model
  reference concentrations), and
- an explicit study weight/height (the OSP reference individuals carry none; the OriginData keys await
  harvest — see `pbpk_domain.campaign.split.Demographics`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from pbpk_domain.campaign.map import MapScenario
from pbpk_domain.cpf.build import BuildReport, Scenario, build_from_cpf
from pbpk_domain.cpf.models import CPF
from pbpk_domain.snapshot.builder import (
    DissolvedFormulationSpec,
    IntravenousProtocolSpec,
    MealEventSpec,
    Measured,
    OralProtocolSpec,
    SimulationSpec,
    SubjectSpec,
)
from pbpk_domain.snapshot.models import Snapshot

# Routes as they arrive on a MapScenario (from split.Route values).
_IV_ROUTES = ("iv_bolus", "iv_infusion")
_ORAL_ROUTES = ("oral",)
# Formulations the builder can place today; IR/MR need a dissolution model the CPF does not yet carry.
_DISSOLVED_FORMULATIONS = ("solution", "suspension")
# Default simulation window for a single-dose study when the scenario carries no sampling schedule.
DEFAULT_SIM_END_TIME_H = 24.0


class ScenarioBuildError(ValueError):
    """A scenario cannot be built without inventing a study-specific value (surfaced, never guessed)."""


@dataclass(frozen=True)
class StageSnapshot:
    snapshot: Snapshot
    build_report: BuildReport
    subjects: tuple[str, ...]          # individual names built for this stage
    simulations: tuple[str, ...]       # simulation (study) names built for this stage
    notes: tuple[str, ...] = field(default_factory=tuple)  # deferred/assumed items, for the record


def scenarios_for_stage(scenarios: Sequence[MapScenario], stage: str) -> tuple[MapScenario, ...]:
    """The MAP scenarios that train (or validate) one stage, in MAP order."""
    return tuple(s for s in scenarios if s.stage == stage)


def _subject_name(scenario: MapScenario) -> str:
    return f"Individual: {scenario.sex} {scenario.age_years:g}y {scenario.population}"


def _subject_spec(scenario: MapScenario, *, seed: int) -> SubjectSpec:
    return SubjectSpec(
        name=_subject_name(scenario),
        population=scenario.population,
        gender=scenario.sex,  # "MALE" | "FEMALE" — validated by SubjectSpec
        age_years=scenario.age_years,
        seed=seed,
    )


def _scenario_specs(scenario: MapScenario, *, subject_name: str, compound: str, sim_end_time_h: float) -> Scenario:
    sid = scenario.study_id
    dose = Measured(value=scenario.dose_mg, unit="mg")

    if scenario.route in _ORAL_ROUTES:
        if scenario.formulation not in _DISSOLVED_FORMULATIONS:
            raise ScenarioBuildError(
                f"scenario {sid!r}: formulation {scenario.formulation!r} needs a dissolution model that the CPF "
                "does not yet carry (only solution/suspension are placed today; IR/MR is a formulation-coverage gap)"
            )
        protocol = OralProtocolSpec(name=f"{sid} protocol", dose=dose)
        formulation = DissolvedFormulationSpec(name=f"{sid} formulation")
        meal_events: tuple[MealEventSpec, ...] = ()
        event_names: tuple[str, ...] = ()
        if scenario.food_state == "fed" and scenario.meal_template:
            meal_events = (MealEventSpec(name=f"{sid} meal", template=scenario.meal_template),)
            event_names = (f"{sid} meal",)
        simulation = SimulationSpec(
            name=sid, subject=subject_name, compound=compound, protocol=protocol.name,
            formulation=formulation.name, end_time_h=sim_end_time_h, events=event_names,
        )
        return Scenario(simulation=simulation, protocol=protocol, formulation=formulation, events=meal_events)

    if scenario.route in _IV_ROUTES:
        if scenario.infusion_time_min is None:
            raise ScenarioBuildError(
                f"scenario {sid!r}: an IV study needs an infusion time (even a short one for a bolus); "
                "the scenario carries none, so it is surfaced rather than invented"
            )
        protocol = IntravenousProtocolSpec(
            name=f"{sid} protocol", dose=dose, infusion_time_min=scenario.infusion_time_min
        )
        simulation = SimulationSpec(
            name=sid, subject=subject_name, compound=compound, protocol=protocol.name, end_time_h=sim_end_time_h,
        )
        return Scenario(simulation=simulation, protocol=protocol, formulation=None, events=())

    raise ScenarioBuildError(f"scenario {sid!r}: route {scenario.route!r} is not supported by the round builder")


def _deferral_notes(snapshot: Snapshot, scenarios: Sequence[MapScenario]) -> tuple[str, ...]:
    notes: list[str] = []
    molecules = sorted({
        p.molecule
        for c in snapshot.compounds
        for p in c.processes
        if p.molecule and p.internal_name != "GlomerularFiltration"
    })
    if molecules:
        notes.append(
            "expression profiles are required for " + ", ".join(molecules) + " for these processes to act in the "
            "simulation; they are not emitted yet (the CPF does not model reference concentrations)"
        )
    weighed = sorted({s.study_id for s in scenarios if s.weight_kg is not None or s.height_cm is not None})
    if weighed:
        notes.append(
            "study weight/height recorded for " + ", ".join(weighed) + " but not written into the snapshot "
            "(PK-Sim derives them from the population; explicit OriginData keys await harvest)"
        )
    return tuple(notes)


def build_stage_snapshot(
    cpf: CPF,
    scenarios: Sequence[MapScenario],
    *,
    stage: str,
    seed: int = 1,
    sim_end_time_h: float = DEFAULT_SIM_END_TIME_H,
    snapshot_version: int | None = None,
) -> StageSnapshot:
    """Build the snapshot for one stage from the CPF and the MAP's scenarios for that stage.

    Raises `ScenarioBuildError` when a scenario cannot be built without inventing a study-specific value, or
    the errors of `build_from_cpf` (missing required CPF parameters, referential problems).
    """
    stage_scenarios = scenarios_for_stage(scenarios, stage)
    if not stage_scenarios:
        raise ScenarioBuildError(f"no MAP scenario trains stage {stage!r}")

    subjects: dict[str, SubjectSpec] = {}
    built: list[Scenario] = []
    for scenario in stage_scenarios:
        subject = _subject_spec(scenario, seed=seed)
        subjects.setdefault(subject.name, subject)
        built.append(
            _scenario_specs(scenario, subject_name=subject.name, compound=cpf.compound, sim_end_time_h=sim_end_time_h)
        )

    snapshot, report = build_from_cpf(
        cpf, list(subjects.values()), built, snapshot_version=snapshot_version
    )
    return StageSnapshot(
        snapshot=snapshot,
        build_report=report,
        subjects=tuple(subjects),
        simulations=tuple(s.simulation.name for s in built),
        notes=_deferral_notes(snapshot, stage_scenarios),
    )
