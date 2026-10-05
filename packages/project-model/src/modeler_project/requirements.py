"""The requirement matrix (the data plan): every PK-Sim input and observed dataset this project needs, who provides it,
and for what (plan §7). Deterministic: the same brief, templates and overrides always give the same matrix.

Derivation: the core template always applies to a small molecule; each application template applies when the brief
names one of its applications. An item's `when` condition is evaluated on the brief and is true, false, or
*undetermined* when the brief does not say (shown, never assumed). Items marked ``per: solid_product`` repeat for each
solid product. The provider of an item is, in order: a person's override (locked across re-derivations), the
proposal's own data-plan statement for that category of data, else the template's default.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from functools import lru_cache
from importlib import resources
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from modeler_project.brief import ProjectBrief

Applies = Literal["yes", "no", "undetermined"]
Provider = Literal["CLIENT", "LITERATURE", "SPONSOR_TO_MEASURE", "PREDICT", "STRUCTURE", "LIBRARY", "STUDY", "PROPOSAL",
                   "NOT_NEEDED", "NOT_STATED"]
_SOLID = re.compile(r"tablet|capsule|granule|powder|pellet|film|chew|lozenge|sachet|solid", re.IGNORECASE)
_PATHWAY_WORDS = {
    "renal": ("renal", "kidney", "urine", "glomerular", "gfr"),
    "biliary": ("biliary", "bile", "feces", "faeces"),
    "secretion": ("tubular secretion", "secret"),
    "hepatic": ("hepatic", "liver", "cyp", "ugt", "metaboli"),
    "transporter": ("transporter", "oatp", "p-gp", "pgp", "bcrp", "oct", "mate"),
}


class RequirementOverride(BaseModel):
    """A person's decision on one item: provider, purpose, the literature cross-check toggle (D-02), always with why."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    req_id: str
    provider: Provider | None = None
    purpose: str | None = None
    cross_check: bool | None = None
    status: Literal["OPEN", "NOT_AVAILABLE", "WAIVED"] | None = None   # a person's call that it cannot / need not be met
    reason: str = Field(min_length=1)
    by: str
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RequirementItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    req_id: str
    label: str
    kind: str                         # parameter | dataset | formulation | system
    target: str
    group: str
    template: str
    pksim: dict[str, str] | None = None
    pksim_status: Literal["HARVESTED", "TO_HARVEST", "NOT_APPLICABLE"] = "HARVESTED"
    unit: str | None = None
    criticality: Literal["REQUIRED", "CONDITIONAL", "OPTIONAL"]
    applies: Applies
    condition_text: str = ""
    needed_for: tuple[str, ...] = ()
    data_category: str = "other"
    provider: Provider
    provider_source: str              # "override" | "data_plan[i]" | "template default"
    provider_statement: str = ""      # the proposal's own words, when the provider came from its data plan
    purpose: str | None = None
    due_date: str | None = None
    cross_check: bool = False         # also search the literature for a client-provided item (D-02 c)
    conditions: tuple[str, ...] = ()
    plausibility: str = ""
    product: str | None = None
    note: str = ""
    status: Literal["OPEN", "SATISFIED", "NOT_AVAILABLE", "WAIVED"] = "OPEN"
    satisfied_by: tuple[str, ...] = ()


class RequirementMatrix(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: str = Field(default="requirements/1", alias="schema")
    templates: tuple[str, ...]        # "id@version (status)"
    items: tuple[RequirementItem, ...]
    overrides: tuple[RequirementOverride, ...] = ()
    notes: tuple[str, ...] = ()

    def to_content(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)

    @classmethod
    def from_content(cls, content: dict[str, Any]) -> RequirementMatrix:
        return cls.model_validate(content)

    def get(self, req_id: str) -> RequirementItem | None:
        return next((i for i in self.items if i.req_id == req_id), None)


@lru_cache
def load_templates() -> tuple[dict[str, Any], ...]:
    package = resources.files("pbpk_domain.requirements")
    out = []
    for entry in sorted(package.iterdir(), key=lambda p: p.name):
        if entry.name.endswith(".yaml"):
            out.append(yaml.safe_load(entry.read_text(encoding="utf-8")))
    return tuple(out)


# --- reading the brief -------------------------------------------------------------------------------------------


def _items(brief: ProjectBrief, group: str) -> list[dict[str, Any]]:
    return [{k: brief.value(f"{group}[{i}].{k}") for k in item} for i, item in enumerate(brief.groups.get(group, ()))]


def _applications(brief: ProjectBrief) -> set[str]:
    return {str(a).split(" ", 1)[0] for a in (brief.value("qoi.applications") or [])}


def _solid_products(brief: ProjectBrief) -> list[str]:
    out = []
    for item in _items(brief, "products"):
        form = " ".join(str(item.get(k) or "") for k in ("dosage_form", "name", "release"))
        if _SOLID.search(form) or item.get("release") in ("IR", "DR", "ER"):
            out.append(str(item.get("name") or item.get("role") or "product"))
    return out


def evaluate_when(when: dict[str, Any] | None, brief: ProjectBrief) -> bool | None:
    """True / False, or None when the brief does not hold what the condition needs."""
    if not when:
        return True
    results: list[bool | None] = []
    scenarios = _items(brief, "scenarios")
    for key, wanted in when.items():
        if key == "route":
            routes = {s.get("route") for s in scenarios if s.get("route")}
            results.append(bool(routes & set(wanted)) if routes else None)
        elif key == "food":
            states = {s.get("food_state") for s in scenarios if s.get("food_state")}
            if "APP-12" in _applications(brief):
                states.add("fed")
            results.append(bool(states & set(wanted)) if states else None)
        elif key == "application":
            apps = _applications(brief)
            results.append(bool(apps & set(wanted)) if apps else None)
        elif key == "bcs":
            bcs = brief.value("drug.bcs_class")
            results.append(None if bcs in (None, "unknown") else bcs in wanted)
        elif key == "pathway":
            text = " ".join(map(str, brief.value("scope.pathways_stated") or [])).lower()
            results.append(any(w in text for p in wanted for w in _PATHWAY_WORDS.get(p, (p,))) if text else None)
        elif key == "nonlinear":
            text = brief.value("scope.nonlinearity")
            results.append(None if text is None else bool(str(text).strip()) == bool(wanted))
        elif key == "ehc":
            flag = brief.value("scope.ehc")
            results.append(None if flag is None else flag == wanted)
        else:
            results.append(None)
    if any(r is False for r in results):
        return False
    return None if any(r is None for r in results) else True


def _data_plan(brief: ProjectBrief) -> list[tuple[int, dict[str, Any]]]:
    return list(enumerate(_items(brief, "data_plan")))


def _provider_from_plan(category: str, purpose: str | None, plan: list[tuple[int, dict[str, Any]]]):
    matches = [(i, d) for i, d in plan if d.get("category") == category and d.get("provider")]
    if not matches:
        return None
    preferred = [(i, d) for i, d in matches if purpose and d.get("purpose") == purpose]
    return (preferred or matches)[0]


# --- derivation -------------------------------------------------------------------------------------------------


def derive(brief: ProjectBrief, overrides: tuple[RequirementOverride, ...] = (),
           previous: RequirementMatrix | None = None) -> RequirementMatrix:
    """The matrix for `brief`. Overrides (and the satisfaction state of a previous matrix) carry over unchanged."""
    modality = brief.value("drug.modality")
    applications = _applications(brief)
    notes: list[str] = []
    if modality == "large_molecule":
        notes.append("large molecule: the core template is for small molecules; see the feasibility check")
    plan = _data_plan(brief)
    by_override = {o.req_id: o for o in overrides}
    kept = {i.req_id: i for i in previous.items} if previous else {}
    items: list[RequirementItem] = []
    used_templates: list[str] = []
    for template in load_templates():
        scope = template.get("applies_to")
        if scope != "all" and not (applications & set(scope or [])):
            continue
        used_templates.append(f"{template['id']}@{template['version']} ({template['status']})")
        for raw in template["items"]:
            applies = evaluate_when(raw.get("when"), brief)
            if raw.get("criticality") == "CONDITIONAL" and raw.get("when") == {}:
                applies = True  # recommended without condition (e.g. IV data)
            products = _solid_products(brief) if raw.get("per") == "solid_product" else [None]
            if raw.get("per") == "solid_product" and not products:
                products = [None]
                applies = None if not brief.groups.get("products") else False
            for product in products:
                req_id = raw["id"] + (f"@{_slug(product)}" if product else "")
                items.append(_item(raw, template["id"], req_id, product, applies, plan, by_override.get(req_id),
                                   kept.get(req_id)))
    return RequirementMatrix(templates=tuple(used_templates), items=tuple(items), overrides=tuple(overrides),
                             notes=tuple(notes))


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower() or "product"


def _item(raw: dict[str, Any], template: str, req_id: str, product: str | None, applies: bool | None,
          plan: list[tuple[int, dict[str, Any]]], override: RequirementOverride | None,
          previous: RequirementItem | None) -> RequirementItem:
    category = raw.get("data_category", "other")
    purpose = raw.get("purpose")
    statement = ""
    due = None
    match = _provider_from_plan(category, purpose, plan)
    if override and override.provider:
        provider, source = override.provider, "override"
    elif match:
        index, row = match
        provider = row["provider"] if row["provider"] in Provider.__args__ else "NOT_STATED"  # type: ignore[attr-defined]
        source, statement, due = f"data_plan[{index}]", str(row.get("item") or ""), row.get("due_date")
        purpose = purpose or row.get("purpose")
    else:
        provider, source = raw.get("default_provider", "LITERATURE"), "template default"
    if override and override.purpose:
        purpose = override.purpose
    pksim = raw.get("pksim")
    label = raw["label"] + (f" — {product}" if product else "")
    return RequirementItem(
        req_id=req_id, label=label, kind=raw["kind"], target=raw["target"].replace("{product}", _slug(product or "")),
        group=raw["group"], template=template, pksim={k: str(v) for k, v in pksim.items()} if pksim else None,
        pksim_status=raw.get("pksim_status", "HARVESTED" if pksim else "NOT_APPLICABLE"), unit=raw.get("unit"),
        criticality=raw["criticality"], applies={True: "yes", False: "no", None: "undetermined"}[applies],
        condition_text=raw.get("condition_text", ""), needed_for=tuple(raw.get("needed_for", ())),
        data_category=category, provider=provider, provider_source=source, provider_statement=statement,
        purpose=purpose, due_date=str(due) if due else None,
        cross_check=bool(override.cross_check) if override and override.cross_check is not None else False,
        conditions=tuple(raw.get("conditions", ())), plausibility=str(raw.get("plausibility", "")), product=product,
        note=str(raw.get("note", "")),
        status=override.status if override and override.status else (previous.status if previous else "OPEN"),
        satisfied_by=previous.satisfied_by if previous else (),
    )


def literature_items(matrix: RequirementMatrix) -> list[RequirementItem]:
    """What P2 searches: applicable items the literature provides, plus client items flagged for a cross-check."""
    return [i for i in matrix.items if i.applies != "no" and (i.provider == "LITERATURE" or i.cross_check)]


def client_items(matrix: RequirementMatrix) -> list[RequirementItem]:
    """What P3 expects from the client (the reconciliation checks each)."""
    return [i for i in matrix.items if i.applies != "no" and i.provider == "CLIENT"]
