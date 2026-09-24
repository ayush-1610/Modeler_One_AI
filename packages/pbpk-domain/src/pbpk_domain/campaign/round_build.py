"""Turn a CPF plus the MAP's scenarios into the snapshot a stage simulates (task T-13 wiring).

`build_round_snapshot` (the Temporal activity) is a thin adapter over `build_stage_snapshot` here. Given the
CPF and the MAP scenarios for one stage, this builds the PK-Sim individual for each study's demographics
(MS-01 §2.3) and one simulation per study — protocol, formulation and meal events — then regenerates the
snapshot from the CPF (`pbpk_domain.cpf.build_from_cpf`). The mapping is deterministic and never invents a
value: a study-specific unknown the scenario does not carry (an IV infusion time, an IR/MR dissolution model)
raises `ScenarioBuildError` naming the gap rather than guessing one.

Each process protein (enzyme, transporter, binding partner) is given its expression profile, harvested from the
OSP reference models (`pbpk_domain.expression`). What is deferred, and surfaced as a build note rather than
silently dropped:
- a process protein with no harvested profile (its process cannot act), and
- an explicit study weight/height (the OSP reference individuals carry none; the OriginData keys await
  harvest — see `pbpk_domain.campaign.split.Demographics`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from pbpk_domain.campaign.map import MapScenario
from pbpk_domain.cpf.build import BuildReport, FormulationSpec, Scenario, build_from_cpf
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
# Liquid forms are placed as Dissolved; solid forms (tablet, capsule, MR) use the CPF formulation they name.
_DISSOLVED_FORMULATIONS = ("solution", "suspension")
# Default simulation window for a single-dose study when the scenario carries no sampling schedule.
DEFAULT_SIM_END_TIME_H = 24.0
# Regular multiple-dose schedules, by interval in hours -> the PK-Sim DosingInterval. Only values that occur in
# the OSP reference snapshots (services/engine-worker/golden/fixtures) are listed — never invented; any other
# interval is surfaced as a ScenarioBuildError until it is harvested.
_DOSING_INTERVAL = {24.0: "DI_24", 12.0: "DI_12_12"}


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


def _schedule(scenario: MapScenario) -> tuple[str, Measured | None]:
    """The protocol's PK-Sim DosingInterval and End time: ("Single", None) for one dose, else a regular schedule
    whose End time is n_doses × interval (PK-Sim repeats the dose while time < End time)."""
    if scenario.dosing_interval_h is None:
        return "Single", None
    interval = _DOSING_INTERVAL.get(float(scenario.dosing_interval_h))
    if interval is None:
        raise ScenarioBuildError(
            f"scenario {scenario.study_id!r}: a dose every {scenario.dosing_interval_h:g} h has no harvested PK-Sim "
            f"DosingInterval (known: {', '.join(f'{k:g} h' for k in _DOSING_INTERVAL)})"
        )
    if scenario.n_doses is None:
        raise ScenarioBuildError(
            f"scenario {scenario.study_id!r}: a multiple-dose study needs its number of doses; none is recorded"
        )
    return interval, Measured(value=scenario.n_doses * float(scenario.dosing_interval_h), unit="h")


def _sim_end(scenario: MapScenario, default_h: float) -> float:
    """Simulate at least the default window, the whole sampled window, and a multiple-dose regimen to its end."""
    end = max(default_h, scenario.sim_end_time_h or 0.0)
    if scenario.dosing_interval_h is not None and scenario.n_doses is not None:
        end = max(end, scenario.n_doses * float(scenario.dosing_interval_h))
    return end


def protocol_name(study_id: str) -> str:
    """The protocol a study's simulation uses (formulation parameters live under it: Events|<protocol>|…)."""
    return f"{study_id} protocol"


def _solid_formulation(scenario: MapScenario, cpf: CPF | None) -> tuple[FormulationSpec, str | None]:
    from pbpk_domain.cpf.formulations import FormulationError, cpf_formulation, resolve_formulation_name

    if cpf is None:
        raise ScenarioBuildError(f"scenario {scenario.study_id!r}: a solid oral form needs the CPF formulation")
    try:
        name, note = resolve_formulation_name(cpf, scenario.formulation_name)
        return cpf_formulation(cpf, name).to_spec(), (f"{scenario.study_id}: {note}" if note else None)
    except FormulationError as exc:
        raise ScenarioBuildError(f"scenario {scenario.study_id!r} ({scenario.formulation}): {exc}") from exc


def _scenario_specs(scenario: MapScenario, *, subject_name: str, compound: str, sim_end_time_h: float,
                    cpf: CPF | None = None, notes: list[str] | None = None) -> Scenario:
    sid = scenario.study_id
    dose = Measured(value=scenario.dose_mg, unit="mg")
    dosing_interval, dosing_end = _schedule(scenario)
    sim_end_time_h = _sim_end(scenario, sim_end_time_h)

    if scenario.route in _ORAL_ROUTES:
        protocol = OralProtocolSpec(name=protocol_name(sid), dose=dose, dosing_interval=dosing_interval, end_time=dosing_end)
        if scenario.formulation in _DISSOLVED_FORMULATIONS:
            formulation: FormulationSpec = DissolvedFormulationSpec(name=f"{sid} formulation")
        else:
            formulation, note = _solid_formulation(scenario, cpf)
            if note and notes is not None:
                notes.append(note)
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
            name=protocol_name(sid), dose=dose, infusion_time_min=scenario.infusion_time_min,
            dosing_interval=dosing_interval, end_time=dosing_end,
        )
        simulation = SimulationSpec(
            name=sid, subject=subject_name, compound=compound, protocol=protocol.name, end_time_h=sim_end_time_h,
        )
        return Scenario(simulation=simulation, protocol=protocol, formulation=None, events=())

    raise ScenarioBuildError(f"scenario {sid!r}: route {scenario.route!r} is not supported by the round builder")


def _deferral_notes(snapshot: Snapshot, scenarios: Sequence[MapScenario], report: BuildReport | None = None) -> tuple[str, ...]:
    notes: list[str] = []
    # Parameters the builder could not place: they are in the CPF but not in the model, so the simulation does
    # not behave as the CPF describes (a missing elimination pathway is the dangerous case).
    if report is not None and report.unresolved:
        notes.append(
            "NOT PLACED IN THE MODEL: " + ", ".join(report.unresolved) + " — these CPF parameters have no engine "
            "binding the builder can use, so the simulation does not include them"
        )
    if report is not None and report.missing_expression:
        notes.append(
            "NOT ACTIVE IN THE MODEL: no harvested expression profile for " + ", ".join(report.missing_expression)
            + " — their processes have no protein to act on (harvest the profile from an OSP reference model)"
        )
    if report is not None and report.expression_profiles:
        from pbpk_domain.expression import expression_source

        notes.append("expression profiles: " + "; ".join(
            f"{m} from the {expression_source(m)}" for m in report.expression_profiles
        ))
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
    skip_unbuildable: bool = False,
) -> StageSnapshot:
    """Build the snapshot for one stage from the CPF and the MAP's scenarios for that stage.

    Raises `ScenarioBuildError` when a scenario cannot be built without inventing a study-specific value, or
    the errors of `build_from_cpf` (missing required CPF parameters, referential problems).

    ``skip_unbuildable`` is for the validation stages: one study the builder cannot place yet (say a tablet with
    no dissolution model) must not stop the others from being judged, so it is left out and named in the notes
    ("NOT SIMULATED"). A fitting stage keeps raising, because silently fitting to fewer studies than the MAP
    planned would change the model.
    """
    stage_scenarios = scenarios_for_stage(scenarios, stage)
    if not stage_scenarios:
        raise ScenarioBuildError(f"no MAP scenario trains stage {stage!r}")

    subjects: dict[str, SubjectSpec] = {}
    built: list[Scenario] = []
    placed: list[MapScenario] = []
    not_simulated: list[str] = []
    assigned: list[str] = []
    for scenario in stage_scenarios:
        subject = _subject_spec(scenario, seed=seed)
        try:
            spec = _scenario_specs(scenario, subject_name=subject.name, compound=cpf.compound,
                                   sim_end_time_h=sim_end_time_h, cpf=cpf, notes=assigned)
        except ScenarioBuildError as exc:
            if not skip_unbuildable:
                raise
            not_simulated.append(f"NOT SIMULATED: {exc}")
            continue
        subjects.setdefault(subject.name, subject)
        built.append(spec)
        placed.append(scenario)
    if not built:
        raise ScenarioBuildError(f"no scenario of stage {stage!r} could be built: " + "; ".join(not_simulated))

    snapshot, report = build_from_cpf(
        cpf, list(subjects.values()), built, snapshot_version=snapshot_version
    )
    return StageSnapshot(
        snapshot=snapshot,
        build_report=report,
        subjects=tuple(subjects),
        simulations=tuple(s.simulation.name for s in built),
        notes=tuple(not_simulated) + tuple(assigned) + _deferral_notes(snapshot, placed, report),
    )
