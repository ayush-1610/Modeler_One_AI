"""What gives a tablet study its formulation, as the project stands (final review round 4: the step bar named "add a
product" whatever the project held, and on a project whose products had dissolution profiles it opened an empty form).

The readiness check "formulations of solid studies" says what each tablet or capsule study lacks, one problem per study
(`pbpk_domain.cpf.formulations`: "<study>: <problem>"). Which lever settles a missing formulation depends on what is here,
so it is read here once, from the project, for every place that names it (the step bar and Review & sign through
`steps.inputs_step`, To do's formulation item and Products and dissolution through `inputs.todo`):

- `use_profile`: a dissolution profile here can give a release (read as a curve, with a Weibull fit: what "Use this
  profile as the release" on a product's card takes). `products`: the products of those profiles, in the register's
  order (the first is the one a link opens);
- `add_dissolution`: products are here (the delivery's with values, the sheet form's, the proposal's, a profile's) but
  no profile of one can give a release: the product's dissolution file is added, or the client is asked. `products`:
  the products here;
- `add_product`: no product is here at all: the product the study used is added (the proposal's products list), or the
  client is asked;
- `choose`: the model holds several formulations and a tablet study names none: a person chooses the one it used.

A study that names its formulation ("the CPF defines no formulation 'Test 10 mg'") puts that product first. None when
no problem is one of these (a formulation not complete, of a type the builder does not place, a study record not
complete): the formulation item on To do says each problem. `studies`: the tablet studies the way is for.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from modeler_project.artifacts import ArtifactKind
from modeler_project.workspace import Workspace

FormulationLever = Literal["use_profile", "add_dissolution", "add_product", "choose"]

# the formulation problems a lever settles (pbpk_domain.cpf.formulations' own words, after the study's id)
_NONE = re.compile(r"^(?P<study>.+?): the study is a solid oral form but the CPF defines no formulation\b")
_NAMED = re.compile(r"^(?P<study>.+?): the CPF defines no formulation (?P<q>['\"])(?P<name>.+)(?P=q) \(")
_SEVERAL = re.compile(r"^(?P<study>.+?): the study does not name its formulation and the CPF defines several: ")


class FormulationWay(BaseModel):
    """The lever that gives a tablet study its formulation, as the project stands (the module docstring)."""

    model_config = ConfigDict(frozen=True)

    way: FormulationLever
    products: tuple[str, ...] = ()
    studies: tuple[str, ...] = ()
    # `use_profile`: the first product's profile can be used now (a person confirmed its product's dissolution data, as
    # "Use this profile as the release" asks); False: its data are confirmed first, on its card
    ready: bool = True


def _key(name: Any) -> str:
    """A product's name as two readers of it compare it: case and spacing aside, a leading "Product" dropped."""
    text = " ".join(str(name or "").casefold().split())
    return text.removeprefix("product ").strip()


def usable(profile: dict[str, Any]) -> bool:
    """A dissolution profile that can give a formulation's release on its product's card: read as a curve, with a
    Weibull fit (the card's "Use this profile as the release"; a plateau below complete release is a table)."""
    return profile.get("release_model") != "Table" and (profile.get("fit") or {}).get("t50_min") is not None


def _profiles(ws: Workspace) -> list[dict[str, Any]]:
    from modeler_project.dissolution_register import profiles

    return profiles(ws)


def products_here(ws: Workspace) -> list[str]:
    """The products the project holds, each once, in this order: the delivery's products with values, the products of
    the dissolution profiles and of the compositions the sheet form read, and the products the proposal names."""
    from modeler_project.brief import ProjectBrief
    from modeler_project.client_data import document_compositions
    from modeler_project.ledger_view import LedgerView

    names: list[str] = []
    reader = LedgerView(ws)
    if reader.store.available:
        names += [e.label for e in reader.entities("product") if reader.values(product=e.id)]
    names += [str(p["key"].get("product")) for p in _profiles(ws) if p["key"].get("product")]
    names += [str(c["product"]) for c in document_compositions(ws) if c.get("product")]
    brief_version = ws.latest(ArtifactKind.BRIEF, "main")
    if brief_version is not None:
        brief = ProjectBrief.from_content(brief_version.content)
        names += [str(brief.value(f"products[{i}].name") or f"product {i + 1}")
                  for i in range(len(brief.groups.get("products", ())))]
    out: dict[str, str] = {}
    for name in names:
        out.setdefault(_key(name), name)
    return list(out.values())


def formulation_way(ws: Workspace, problems: Sequence[str]) -> FormulationWay | None:
    """The lever for the readiness check's formulation problems (`problems`, its detail), or None (the docstring)."""
    none = [m["study"] for p in problems if (m := _NONE.match(p))]
    named = [(m["study"], m["name"]) for p in problems if (m := _NAMED.match(p))]
    if not none and not named:
        several = list(dict.fromkeys(m["study"] for p in problems if (m := _SEVERAL.match(p))))
        return FormulationWay(way="choose", studies=tuple(several)) if several else None
    studies = tuple(dict.fromkeys([*none, *(study for study, _name in named)]))
    wanted = {_key(name) for _study, name in named}

    def first_wanted(names: list[str]) -> tuple[str, ...]:
        unique = list(dict.fromkeys(names))
        return tuple(sorted(unique, key=lambda n: _key(n) not in wanted))

    can = [p for p in _profiles(ws) if usable(p)]
    if can:               # an unnamed profile counts too: its "Use as release" is under the profiles of no product
        from modeler_project.client_review import confirmed_profiles

        # a product whose dissolution data a person confirmed first: its profile can be used now (the API refuses one
        # whose product is still to confirm), then the one a study names
        confirmed = confirmed_profiles(ws)
        ready = {str(p["key"].get("product") or "") for p in can if p["id"] in confirmed}
        named = first_wanted([str(p["key"].get("product") or "") for p in can if p["key"].get("product")])
        products = tuple(sorted(named, key=lambda n: n not in ready))
        first = products[0] if products else ""
        return FormulationWay(way="use_profile", products=products, studies=studies, ready=first in ready)
    here = products_here(ws)
    if here:
        return FormulationWay(way="add_dissolution", products=first_wanted(here), studies=studies)
    return FormulationWay(way="add_product", studies=studies)
