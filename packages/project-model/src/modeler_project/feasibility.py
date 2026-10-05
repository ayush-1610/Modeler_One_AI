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

from modeler_project.brief import ProjectBrief

Status = Literal["SUPPORTED", "LIMITED", "NEEDS_HARVEST", "NOT_SUPPORTED", "UNDETERMINED"]

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


@lru_cache
def expression_proteins() -> frozenset[str]:
    text = resources.files("pbpk_domain.data").joinpath("expression_library.json").read_text(encoding="utf-8")
    return frozenset(json.loads(text)["molecules"])


_PROTEIN = re.compile(r"\b(CYP\d[A-Z]\d{1,2}|UGT\d[A-Z]\d{1,2}|OATP\d[A-Z]\d|P-gp|BCRP|ABC[A-Z]\d|OCT\d|MATE\d|OAT\d|MRP\d|"
                      r"AADAC|CES\d|FMO\d|SLC\w+)\b", re.IGNORECASE)


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
