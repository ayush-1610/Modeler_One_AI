"""The feasibility check (plan §7.5, T-43): what the brief needs that the PK-Sim builder cannot produce yet.

"Any drug in the world" (R-13) is true of the pipeline: nothing in it knows a drug by name. What limits a project is
the builder's coverage of PK-Sim. This check reports, on day 1, each feature the brief needs with its status and the
route to support, instead of a failure at S3. Coverage facts come from the harvested catalog
(`services/engine-worker/golden/catalog.json` via `pbpk_domain.catalog`), the harvested expression library and the
builder's spec types; nothing here names a PK-Sim structure that was not harvested.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib import resources
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from modeler_project.brief import FORMULATIONS_BUILT, OPTION_LABELS, FieldStatus, ProjectBrief, definition_of

Status = Literal["SUPPORTED", "LIMITED", "NEEDS_HARVEST", "NOT_SUPPORTED", "UNDETERMINED"]
GateState = Literal["supported", "limited", "not_supported", "not_set"]

# What the builder emits today (pbpk_domain.snapshot.builder spec types), as PK-Sim structures harvested from the
# OSP reference snapshots. Updated with the builder, never by guesswork.
BUILDER_ROUTES = {"iv_infusion", "iv_bolus", "oral"}
BUILDER_FORMULATIONS = {"Formulation_Dissolved", "Formulation_Tablet_Weibull", "Formulation_Particles"}


class FeasibilityLine(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    feature: str
    needed_because: str
    status: Status
    route: str = ""        # how it becomes supported (harvest a reference model, extend the builder, MoBi …)


class FeasibilityReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    lines: tuple[FeasibilityLine, ...]

    @property
    def blocking(self) -> tuple[FeasibilityLine, ...]:
        return tuple(line for line in self.lines if line.status in ("NOT_SUPPORTED", "NEEDS_HARVEST"))

    def to_content(self) -> dict[str, Any]:
        return {"lines": [line.model_dump() for line in self.lines],
                "blocking": len(self.blocking), "undetermined": sum(line.status == "UNDETERMINED" for line in self.lines)}


class ScopeGate(BaseModel):
    """One question Start asks before any data work (D-28): what the builder can model, and what it cannot yet."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    gate: Literal["modality", "pbpk_model", "site_of_action", "formulation_types", "routes"]
    label: str
    path: str                      # the brief field it reads ("scenarios" for the routes of the scenarios)
    state: GateState
    values: tuple[str, ...] = ()
    message: str = ""              # what is not supported yet (or limited), in words; empty when supported
    supported: str                 # what the builder makes today


_LIMITED_FORMULATION = ("extended release through a Weibull fitted to dissolution; delayed (enteric) release needs a "
                        "harvested lag / pH-dependent model before a regulatory claim")
_ORDER: dict[GateState, int] = {"supported": 0, "limited": 1, "not_supported": 2}


def _gate(gate: str, path: str, supported: str, values: list[str], judge, *, applicable: bool = True) -> ScopeGate:
    """`judge(value)` gives each value's state and, when not supported, why; the gate takes the worst of them."""
    label = "Routes" if gate == "routes" else definition_of(path).label
    if not applicable:
        return ScopeGate(gate=gate, label=label, path=path, state="supported", message="not applicable", supported=supported)  # type: ignore[arg-type]
    if not values:
        return ScopeGate(gate=gate, label=label, path=path, state="not_set", supported=supported)  # type: ignore[arg-type]
    judged = [(v, *judge(v)) for v in values]
    state = max((s for _, s, _ in judged), key=_ORDER.__getitem__)
    names = OPTION_LABELS.get(path, {})
    notes = [f"{names.get(v, v.replace('_', ' '))}: {why}" for v, s, why in judged if s != "supported"]
    return ScopeGate(gate=gate, label=label, path=path, state=state, values=tuple(values),  # type: ignore[arg-type]
                     message="; ".join(notes), supported=supported)


_NOT_YET = "not supported yet"
_LOCAL = f"{_NOT_YET}: a local site of action needs a site model the builder does not make"


def _only(supported_value: str, why: str = _NOT_YET):
    return lambda v: ("supported", "") if v == supported_value else ("not_supported", why)


def _formulation(value: str) -> tuple[GateState, str]:
    if value == "mr":
        return "limited", _LIMITED_FORMULATION
    return ("supported", "") if value in FORMULATIONS_BUILT else ("not_supported", _NOT_YET)


def _route(value: str) -> tuple[GateState, str]:
    return ("supported", "") if value in BUILDER_ROUTES else ("not_supported", _NOT_YET)


def scope_gates(brief: ProjectBrief) -> tuple[ScopeGate, ...]:
    """Modality, PBPK model, site of action, formulation types and routes (D-28). Anything the builder cannot model
    is "not supported yet" at Start, before any data work, instead of a failure at S0 or S3."""
    def one(path: str) -> list[str]:
        value = brief.value(path)
        return [str(value)] if value not in (None, "") else []

    formulations = [str(v) for v in (brief.value("scope.formulation_types") or [])]
    routes = sorted({str(r) for r in _values(brief, "scenarios", "route") if r})
    return (
        _gate("modality", "drug.modality", "small molecules", one("drug.modality"), _only("small_molecule")),
        _gate("pbpk_model", "scope.pbpk_model", "full (whole-body) PK-Sim models", one("scope.pbpk_model"), _only("full")),
        _gate("site_of_action", "scope.site_of_action", "systemic action (plasma and tissue exposure)",
              one("scope.site_of_action"), _only("systemic", _LOCAL)),
        _gate("formulation_types", "scope.formulation_types",
              "solutions, suspensions, immediate-release tablets and capsules (dissolved, Weibull or particle release); "
              "modified release is limited", formulations, _formulation,
              applicable=brief.get("scope.formulation_types").status is not FieldStatus.NOT_APPLICABLE),
        _gate("routes", "scenarios", "intravenous (bolus, infusion) and oral", routes, _route),
    )


@lru_cache
def expression_proteins() -> frozenset[str]:
    text = resources.files("pbpk_domain.data").joinpath("expression_library.json").read_text(encoding="utf-8")
    return frozenset(json.loads(text)["molecules"])


_PROTEIN = re.compile(r"\b(CYP\d[A-Z]\d{1,2}|UGT\d[A-Z]\d{1,2}|OATP\d[A-Z]\d|P-gp|BCRP|ABC[A-Z]\d|OCT\d|MATE\d|OAT\d|MRP\d|"
                      r"AADAC|CES\d|FMO\d|SLC\w+)\b", re.IGNORECASE)


def pathway_suggestions() -> list[str]:
    """The enzymes and transporters the harvested expression library has a profile for: offered when the pathways are
    picked at Start (a typed name is kept too; one without a profile is flagged NEEDS_HARVEST)."""
    return [p for p in sorted(expression_proteins()) if _PROTEIN.fullmatch(p)]


def _values(brief: ProjectBrief, group: str, field: str) -> list[Any]:
    return [brief.value(f"{group}[{i}].{field}") for i in range(len(brief.groups.get(group, ())))]


def check(brief: ProjectBrief) -> FeasibilityReport:
    lines: list[FeasibilityLine] = []
    add = lines.append

    modality = brief.value("drug.modality")
    if modality is None:
        add(FeasibilityLine(feature="modality", needed_because="drug.modality not set", status="UNDETERMINED"))
    elif modality == "small_molecule":
        add(FeasibilityLine(feature="small-molecule PBPK model", needed_because="drug.modality", status="SUPPORTED"))
    else:
        add(FeasibilityLine(feature=f"{modality.replace('_', ' ')} model", needed_because="drug.modality",
                            status="NOT_SUPPORTED", route="harvest the PK-Sim large-molecule model from a reference "
                            "snapshot and extend the builder (T-10)"))

    routes = {r for r in _values(brief, "scenarios", "route") if r}
    if not routes:
        add(FeasibilityLine(feature="administration routes", needed_because="no scenario route yet", status="UNDETERMINED"))
    for route in sorted(routes):
        supported = route in BUILDER_ROUTES
        add(FeasibilityLine(feature=f"route: {route.replace('_', ' ')}", needed_because="a planned scenario",
                            status="SUPPORTED" if supported else "NOT_SUPPORTED",
                            route="" if supported else "not built: needs a harvested PK-Sim protocol of that application "
                            "type, or a MoBi extension for routes PK-Sim does not model"))

    for gate in scope_gates(brief):
        if gate.gate in ("pbpk_model", "site_of_action", "formulation_types") and gate.state in ("limited", "not_supported"):
            add(FeasibilityLine(feature=f"{gate.label}: {gate.message}", needed_because=gate.path,
                                status="LIMITED" if gate.state == "limited" else "NOT_SUPPORTED",
                                route=f"the builder makes {gate.supported}; support is added one product type at a "
                                "time, with the SME (D-28)"))

    for index in range(len(brief.groups.get("products", ()))):
        name = brief.value(f"products[{index}].name") or f"product {index + 1}"
        release = brief.value(f"products[{index}].release")
        form = str(brief.value(f"products[{index}].dosage_form") or "")
        if release in ("ER", "DR"):
            add(FeasibilityLine(feature=f"{name}: {release} release", needed_because="products",
                                status="LIMITED", route="Weibull or particle release fitted to dissolution; delayed (enteric) "
                                "release needs a harvested lag / pH-dependent model before a regulatory claim"))
        elif release == "IR" or form:
            add(FeasibilityLine(feature=f"{name}: {form or 'IR'} release", needed_because="products",
                                status="SUPPORTED", route="Dissolved, Weibull or particle dissolution (harvested)"))

    stated = " ".join(map(str, brief.value("scope.pathways_stated") or []))
    for protein in sorted({m.group(0).upper().replace("P-GP", "P-gp") for m in _PROTEIN.finditer(stated)}):
        known = protein in expression_proteins()
        add(FeasibilityLine(feature=f"expression profile: {protein}", needed_because="scope.pathways_stated",
                            status="SUPPORTED" if known else "NEEDS_HARVEST",
                            route="" if known else "harvest its profile from an OSP reference model "
                            "(scripts/harvest_expression_library.py); without it S0 refuses the CPF"))
    lowered = stated.lower()
    if "biliary" in lowered or "secretion" in lowered:
        add(FeasibilityLine(feature="biliary / tubular-secretion clearance", needed_because="scope.pathways_stated",
                            status="NEEDS_HARVEST", route="T-10 tail: harvest the process from a reference model"))

    if brief.value("scope.parent_metabolite") == "parent_and_metabolites":
        add(FeasibilityLine(feature="parent and metabolites", needed_because="scope.parent_metabolite", status="LIMITED",
                            route="model systems build them together; MS-01 v1.0 fits the parent only (§6.5)"))
    if brief.value("scope.pd") is True:
        add(FeasibilityLine(feature="PK/PD", needed_because="scope.pd", status="NOT_SUPPORTED",
                            route="MS-01 §6.9: a MoBi PD module, out of v1.0"))

    for kind in sorted({k for k in _values(brief, "populations", "kind") if k}):
        status: Status
        if kind in ("healthy", "patient", "ethnic", "elderly"):
            status, route = "SUPPORTED", "PK-Sim populations harvested (8 human databases)"
        elif kind in ("pediatric", "pregnancy", "genotype"):
            status, route = "LIMITED", "population database harvested; the application template is T-31"
        elif kind == "preclinical":
            status, route = "LIMITED", "species harvested; species CPF variants per MS-01 §6.8"
        else:
            status, route = "NEEDS_HARVEST", "disease-state physiology to harvest or parameterize (T-31)"
        add(FeasibilityLine(feature=f"population: {kind.replace('_', ' ')}", needed_because="populations", status=status,
                            route=route))

    apps = {str(a).split(" ", 1)[0] for a in (brief.value("qoi.applications") or [])}
    templates = {"APP-03": "DDI", "APP-04": "transporter DDI", "APP-06": "pediatric", "APP-07": "hepatic impairment",
                 "APP-08": "renal impairment", "APP-14": "virtual bioequivalence", "APP-02": "FIH translation"}
    for app in sorted(apps):
        if app in templates:
            add(FeasibilityLine(feature=f"application: {templates[app]}", needed_because="qoi.applications", status="LIMITED",
                                route="model build, validation, sensitivity and uncertainty run today; the S6 application "
                                "template is T-31"))
        elif app in ("APP-16", "APP-17"):
            add(FeasibilityLine(feature=f"application: {app}", needed_because="qoi.applications", status="NOT_SUPPORTED",
                                route="large molecules / PD are outside the builder and MS-01 v1.0"))
        elif app in ("APP-01", "APP-11", "APP-12"):
            add(FeasibilityLine(feature=f"application: {app}", needed_because="qoi.applications", status="SUPPORTED"))
    if not apps:
        add(FeasibilityLine(feature="applications", needed_because="qoi.applications not set", status="UNDETERMINED"))
    if "APP-12" in apps or "fed" in set(_values(brief, "scenarios", "food_state")):
        add(FeasibilityLine(feature="fed state (meal events)", needed_because="food effect / fed scenario", status="LIMITED",
                            route="meal templates harvested; fitting a fed parameter (S3 fed sub-loop) is partial"))
    return FeasibilityReport(lines=tuple(lines))
