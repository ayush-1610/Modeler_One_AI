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
from pbpk_domain.cpf.build import BuildReport, FormulationSpec, Scenario, build_from_cpf, build_from_system
from pbpk_domain.cpf.models import CPF
from pbpk_domain.snapshot.builder import (
    CoCompoundSpec,
    DissolvedFormulationSpec,
    DosePhaseSpec,
    IntravenousBolusProtocolSpec,
    IntravenousProtocolSpec,
    MealEventSpec,
    Measured,
    OralProtocolSpec,
    SimulationSpec,
    SubjectSpec,
)
from pbpk_domain.snapshot.models import Snapshot
from pbpk_domain.system import ModelSystem

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
    name = f"Individual: {scenario.sex} {scenario.age_years:g}y {scenario.population}"
    if scenario.weight_kg is not None:
        name += f" {scenario.weight_kg:g}kg"
    if scenario.height_cm is not None:
        name += f" {scenario.height_cm:g}cm"
    if scenario.published_individual is not None:
        name += f" ({scenario.published_individual.name})"
    return name


def _subject_spec(scenario: MapScenario, *, seed: int) -> SubjectSpec:
    published = scenario.published_individual
    own: dict = {}
    if published is not None:
        own = {
            "own_physiology": True,
            "parameters": {path: Measured(value=v.value, unit=v.unit) for path, v in published.parameters.items()},
            "expression_overrides": {path: Measured(value=v.value, unit=v.unit) for path, v in published.expression.items()},
            "expression_documents": dict(published.profiles),
        }
        if published.seed is not None:
            seed = published.seed
    return SubjectSpec(
        name=_subject_name(scenario),
        population=scenario.population,
        gender=scenario.sex,  # "MALE" | "FEMALE" — validated by SubjectSpec
        age_years=scenario.age_years,
        weight_kg=scenario.weight_kg,
        height_cm=scenario.height_cm,
        seed=seed,
        **own,
    )


def _schedule(scenario: MapScenario) -> dict:
    """The protocol's dosing fields: one dose; a named PK-Sim DosingInterval with the End time n_doses × interval
    (PK-Sim repeats the dose while time < End time); or, for any other regular interval, a schema repeated n_doses
    times (the structure of the OSP reference multiple-dose protocols); a regimen whose doses differ, one schema per
    phase (the OSP Voriconazole loading-dose protocols)."""
    if scenario.dose_phases:
        unit = "mg/kg" if scenario.dose_per_kg else "mg"
        return {"phases": tuple(DosePhaseSpec(start_h=p.start_h, dose=Measured(value=p.dose_mg, unit=unit),
                                              repetitions=p.n_doses, interval_h=p.interval_h or 0.0,
                                              infusion_time_min=p.infusion_time_min)
                                for p in scenario.dose_phases)}
    if scenario.dosing_interval_h is None:
        return {}
    if scenario.n_doses is None:
        raise ScenarioBuildError(
            f"scenario {scenario.study_id!r}: a multiple-dose study needs its number of doses; none is recorded"
        )
    interval = _DOSING_INTERVAL.get(float(scenario.dosing_interval_h))
    if interval is None:
        return {"repetitions": scenario.n_doses, "repetition_interval_h": float(scenario.dosing_interval_h)}
    return {"dosing_interval": interval,
            "end_time": Measured(value=scenario.n_doses * float(scenario.dosing_interval_h), unit="h")}


def _sim_end(scenario: MapScenario, default_h: float) -> float:
    """Simulate at least the default window, the whole sampled window, and a multiple-dose regimen to its end."""
    end = max(default_h, scenario.sim_end_time_h or 0.0)
    if scenario.dosing_interval_h is not None and scenario.n_doses is not None:
        end = max(end, scenario.n_doses * float(scenario.dosing_interval_h))
    for phase in scenario.dose_phases:
        end = max(end, phase.start_h + phase.n_doses * (phase.interval_h or 0.0))
    return end


def protocol_name(study_id: str) -> str:
    """The protocol a study's simulation uses (formulation parameters live under it: Events|<protocol>|…)."""
    return f"{study_id} protocol"


def _bin_schedule(scenario: MapScenario) -> dict:
    """A binned product's regimen as schema repetitions (the published bin protocols: n doses, interval apart; a
    single dose is one repetition)."""
    if scenario.dose_phases:
        raise ScenarioBuildError(f"scenario {scenario.study_id!r}: a binned product given in phases (loading, then "
                                 "maintenance) is not placed yet; no published protocol does it")
    if scenario.dosing_interval_h is None:
        return {}
    if scenario.n_doses is None:
        raise ScenarioBuildError(
            f"scenario {scenario.study_id!r}: a multiple-dose study needs its number of doses; none is recorded"
        )
    return {"repetitions": scenario.n_doses, "repetition_interval_h": float(scenario.dosing_interval_h)}


def _solid_formulation(scenario: MapScenario, cpf: CPF | None) -> tuple[list, tuple[tuple[str, float], ...], str | None]:
    """(formulation specs — one, or every bin of a binned product —, the bins, a note)."""
    from pbpk_domain.cpf.formulations import FormulationError, cpf_formulation, resolve_formulation_name

    if cpf is None:
        raise ScenarioBuildError(f"scenario {scenario.study_id!r}: a solid oral form needs the CPF formulation")
    try:
        name, note = resolve_formulation_name(cpf, scenario.formulation_name)
        specs, bins = cpf_formulation(cpf, name).to_specs()
        return specs, bins, (f"{scenario.study_id}: {note}" if note else None)
    except FormulationError as exc:
        raise ScenarioBuildError(f"scenario {scenario.study_id!r} ({scenario.formulation}): {exc}") from exc


def _scenario_specs(scenario: MapScenario, *, subject_name: str, compound: str, sim_end_time_h: float,
                    cpf: CPF | None = None, notes: list[str] | None = None) -> Scenario:
    sid = scenario.study_id
    dose = Measured(value=scenario.dose_mg, unit="mg/kg" if scenario.dose_per_kg else "mg")
    schedule = _schedule(scenario)
    sim_end_time_h = _sim_end(scenario, sim_end_time_h)

    if scenario.route in _ORAL_ROUTES:
        extra: list = []
        bins: tuple[tuple[str, float], ...] = ()
        # a solution the published model gives as its own formulation (Ketoconazole: 8 nm particles, dissolution still
        # limited by solubility) uses it; otherwise a solution is dissolved
        if scenario.formulation in _DISSOLVED_FORMULATIONS and not scenario.formulation_name:
            formulation: FormulationSpec = DissolvedFormulationSpec(name=f"{sid} formulation")
        else:
            specs, bins, note = _solid_formulation(scenario, cpf)
            formulation, extra = specs[0], specs[1:]
            if note and notes is not None:
                notes.append(note)
        if bins:
            protocol = OralProtocolSpec(name=protocol_name(sid), dose=dose, bins=bins, **_bin_schedule(scenario))
        else:
            protocol = OralProtocolSpec(name=protocol_name(sid), dose=dose, **schedule)
        meal_events: tuple[MealEventSpec, ...] = ()
        event_names: tuple[str, ...] = ()
        if scenario.food_state == "fed" and scenario.meal_template:
            meal_events = (MealEventSpec(name=f"{sid} meal", template=scenario.meal_template),)
            event_names = (f"{sid} meal",)
        simulation = SimulationSpec(
            name=sid, subject=subject_name, compound=compound, protocol=protocol.name,
            formulation=formulation.name, end_time_h=sim_end_time_h, events=event_names,
            formulation_bins=tuple(name for name, _f in bins),
        )
        return Scenario(simulation=simulation, protocol=protocol, formulation=formulation, events=meal_events,
                        extra_formulations=tuple(extra))

    if scenario.route in _IV_ROUTES:
        if scenario.infusion_time_min is None and scenario.route != "iv_bolus":
            raise ScenarioBuildError(
                f"scenario {sid!r}: an IV infusion study needs an infusion time; "
                "the scenario carries none, so it is surfaced rather than invented"
            )
        protocol: IntravenousProtocolSpec | IntravenousBolusProtocolSpec
        if scenario.infusion_time_min is None:  # a bolus: PK-Sim IntravenousBolus, no infusion time
            protocol = IntravenousBolusProtocolSpec(name=protocol_name(sid), dose=dose, **schedule)
        else:
            protocol = IntravenousProtocolSpec(
                name=protocol_name(sid), dose=dose, infusion_time_min=scenario.infusion_time_min, **schedule,
            )
        simulation = SimulationSpec(
            name=sid, subject=subject_name, compound=compound, protocol=protocol.name, end_time_h=sim_end_time_h,
        )
        return Scenario(simulation=simulation, protocol=protocol, formulation=None, events=())

    raise ScenarioBuildError(f"scenario {sid!r}: route {scenario.route!r} is not supported by the round builder")


def _observer_members(document: dict) -> set[str]:
    """The compounds a published observer's formula reads (the MOLECULE placeholder is the observer's own)."""
    refs = [r.get("Path", "") for o in document.get("Observers", []) for r in (o.get("Formula") or {}).get("References", [])]
    return {path.split("|")[-2] for path in refs if path.count("|") >= 2 and path.split("|")[-1] == "Concentration"} - {"MOLECULE"}


def _system_scenario(scenario: MapScenario, system: ModelSystem, *, subject_name: str, sim_end_time_h: float,
                     cpf: CPF, notes: list[str]) -> Scenario:
    """A study of a model system: each compound its product doses gets the study's protocol at dose x fraction, the
    metabolites they form are simulated with them, and the published sum observers of those compounds are computed."""
    product = scenario.product or (system.parents[0] if len(system.products) == 1 else None)
    fractions = system.products.get(product) if product is not None else None
    if fractions is None and len(system.products) == 1:
        fractions = next(iter(system.products.values()))
    if fractions is None:
        raise ScenarioBuildError(f"scenario {scenario.study_id!r}: the system has several products and the study names "
                                 f"none it has ({scenario.product!r}); which compounds it doses is not guessed")
    dosed = list(fractions)

    def share(compound: str) -> dict:
        f = fractions[compound]
        return {"dose_mg": scenario.dose_mg * f,
                "dose_phases": tuple(p.model_copy(update={"dose_mg": p.dose_mg * f}) for p in scenario.dose_phases)}

    first = scenario.model_copy(update=share(dosed[0]))
    base = _scenario_specs(first, subject_name=subject_name, compound=dosed[0], sim_end_time_h=sim_end_time_h,
                           cpf=cpf, notes=notes)
    extra, co = [], []
    for compound in dosed[1:]:
        mine = _scenario_specs(scenario.model_copy(update=share(compound)), subject_name=subject_name, compound=compound,
                               sim_end_time_h=sim_end_time_h, cpf=cpf).protocol
        protocol = mine.model_copy(update={"name": f"{base.protocol.name} {compound}"})
        extra.append(protocol)
        co.append(CoCompoundSpec(name=compound, protocol=protocol.name,
                                 formulation=base.formulation.name if base.formulation is not None else None))
    present = system.closure(tuple(dosed))
    co.extend(CoCompoundSpec(name=name) for name in present if name not in dosed)
    observers = tuple(name for name, doc in system.observers.items()
                      if (members := _observer_members(doc)) and members <= set(present))
    outputs = tuple(dict.fromkeys(a.output_path for a in system.analytes.values()
                                  if (a.kind == "compound" and a.compound in present)
                                  or (a.kind == "observer" and a.observer in observers)))
    simulation = base.simulation.model_copy(update={"co_compounds": tuple(co), "observer_sets": observers,
                                                    "additional_outputs": outputs})
    return base.model_copy(update={"simulation": simulation, "extra_protocols": tuple(extra)})


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
            f"{m} from the model's own published profile" if m in report.expression_documents
            else f"{m} from the {expression_source(m)}" for m in report.expression_profiles
        ))
    own = sorted({f"{s.study_id} ({s.published_individual.name})" for s in scenarios if s.published_individual})
    if own:
        notes.append("simulated in the published model's own individual for the study: " + ", ".join(own))
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
    system: ModelSystem | None = None,
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
    main_cpf = cpf if system is None else system.cpf(system.parents[0])
    for scenario in stage_scenarios:
        subject = _subject_spec(scenario, seed=seed)
        try:
            if system is None:
                spec = _scenario_specs(scenario, subject_name=subject.name, compound=cpf.compound,
                                       sim_end_time_h=sim_end_time_h, cpf=cpf, notes=assigned)
            else:
                spec = _system_scenario(scenario, system, subject_name=subject.name, sim_end_time_h=sim_end_time_h,
                                        cpf=main_cpf, notes=assigned)
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

    if system is None:
        snapshot, report = build_from_cpf(cpf, list(subjects.values()), built, snapshot_version=snapshot_version)
    else:
        snapshot, report = build_from_system(system, list(subjects.values()), built, snapshot_version=snapshot_version)
    return StageSnapshot(
        snapshot=snapshot,
        build_report=report,
        subjects=tuple(subjects),
        simulations=tuple(s.simulation.name for s in built),
        notes=tuple(not_simulated) + tuple(assigned) + _deferral_notes(snapshot, placed, report),
    )
