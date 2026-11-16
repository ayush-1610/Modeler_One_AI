"""What gives a tablet study its formulation, as the project stands (final review round 4: the step bar named "add a
product" whatever the project held, and on a project whose products had dissolution profiles it opened an empty form;
round 5: the way is read for each study, and a product's profile settles only a study it can settle).

The readiness check "formulations of solid studies" says what each tablet or capsule study lacks, one problem per study
(`pbpk_domain.cpf.formulations`: "<study>: <problem>"). Which lever settles a missing formulation depends on what is here
and on what the study names, so it is read here once, from the project, for every place that names it (the step bar and
Review & sign through `steps.inputs_step`, To do's formulation item and Products and dissolution through `inputs.todo`).
Each study has its own way (`each`):

- a study that names its formulation ("the CPF defines no formulation 'Test 10 mg'") is settled by that product only:
  `use_profile` with it when a dissolution profile of it can give a release (read as a curve, with a Weibull fit: what
  "Use this profile as the release" on a product's card takes), else `add_dissolution` with it (its dissolution data are
  added, or the client is asked). Another product's profile never settles it;
- a study that names none, while the model holds no formulation: `use_profile` when a dissolution profile here can give a
  release and is not the release of a formulation already (`products`: its product; a profile of no product counts too,
  its "Use as release" is under the profiles of no product); else `add_dissolution` with the products here (the
  delivery's with values, the dissolution register's, the sheet form's compositions, the proposal's); else
  `add_product` (no product is here at all: the product the study used is added, or the client is asked);
- a study that names none while the model holds several formulations: `choose` (a person chooses the one it used).

`products` are in this order: the products the studies name first, then those whose dissolution data a person confirmed
(their profile can be used now; "Use this profile as the release" is refused before), then the register's order. The
first is the one a link opens, and `ready` says whether its profile can be used now. The way the step bar names (the
model's own fields) is the first of `use_profile`, `add_dissolution`, `add_product` and `choose` that a study has, for the
studies it settles; `each` says every study's own (Products and dissolution says it on the study's row, and To do's "Ask
the client" asks for every study whose way offers the client: `add_dissolution`, `add_product`). None when no problem is
one of these (a formulation not complete, of a type the builder does not place, a study record not complete): the
formulation item on To do says each problem.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from modeler_project.artifacts import ArtifactKind
from modeler_project.workspace import Workspace

FormulationLever = Literal["use_profile", "add_dissolution", "add_product", "choose"]
# the order the step bar names a lever in when the studies' differ: the one done here and now first
_ORDER: tuple[FormulationLever, ...] = ("use_profile", "add_dissolution", "add_product", "choose")
# the ways that offer to ask the client (the words' "or ask the client")
ASKS: frozenset[str] = frozenset({"add_dissolution", "add_product"})

# the formulation problems a lever settles (pbpk_domain.cpf.formulations' own words, after the study's id)
_NONE = re.compile(r"^(?P<study>.+?): the study is a solid oral form but the CPF defines no formulation\b")
_NAMED = re.compile(r"^(?P<study>.+?): the CPF defines no formulation (?P<q>['\"])(?P<name>.+)(?P=q) \(")
_SEVERAL = re.compile(r"^(?P<study>.+?): the study does not name its formulation and the CPF defines several: ")


class StudyWay(BaseModel):
    """One tablet study's own lever (the module docstring): `products` in the order a link opens them, `ready` whether
    the first one's profile can be used now; `named`: the product the study names, if it names one."""

    model_config = ConfigDict(frozen=True)

    study: str
    way: FormulationLever
    products: tuple[str, ...] = ()
    ready: bool = True
    named: str | None = None


class FormulationWay(BaseModel):
    """The lever that gives a tablet study its formulation, as the project stands (the module docstring): the step bar's
    (`way`, `products`, `studies`, `ready`) and each study's own (`each`)."""

    model_config = ConfigDict(frozen=True)

    way: FormulationLever
    products: tuple[str, ...] = ()
    studies: tuple[str, ...] = ()
    # `use_profile`: the first product's profile can be used now (a person confirmed its product's dissolution data, as
    # "Use this profile as the release" asks); False: its data are confirmed first, on its card
    ready: bool = True
    each: tuple[StudyWay, ...] = ()


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


def _released(ws: Workspace) -> tuple[set[str], set[str]]:
    """What gives a release already: the dissolution profiles a formulation the model holds was made from (by id: the
    release's evidence names its profile), and the formulations the model holds (by name, as `_key` compares a
    product's)."""
    from modeler_project.evidence import EvidenceItem
    from modeler_project.inputs import current_cpf
    from modeler_project.study_requirements import formulations_held

    cpf = current_cpf(ws)
    held = formulations_held(cpf)
    used: set[str] = set()
    for name in held:
        record = cpf.get(f"form.{name}.type") if cpf is not None else None
        evidence = str(record.provenance.evidence or "") if record is not None and record.provenance is not None else ""
        found = ws.latest(ArtifactKind.EVIDENCE, evidence.split("@")[0]) if evidence else None
        if found is not None:
            # its source is "<profile id> v<version>: <label>" (`dissolution_register.propose_release_model`)
            used.add(EvidenceItem.from_content(found.content).source.locator.split(" ", 1)[0])
    return used, {_key(name) for name in held}


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


def _each(ws: Workspace, none: list[str], named: list[tuple[str, str]]) -> tuple[list[StudyWay], set[str]]:
    """Each study's way for the problems a product settles (the docstring), and the products whose profile can be used
    now (their dissolution data confirmed)."""
    from modeler_project.client_review import confirmed_profiles

    used, held = _released(ws)
    confirmed = confirmed_profiles(ws)
    # the profiles that can give a release, by their product's key ("" for a profile of no product), in the register's
    # order; a profile a formulation was made from already gives its release
    can: dict[str, list[dict[str, Any]]] = {}
    for p in _profiles(ws):
        if usable(p) and p["id"] not in used:
            can.setdefault(_key(p["key"].get("product")), []).append(p)
    names = {k: str(found[0]["key"].get("product") or "") for k, found in can.items()}
    ready = {k for k, found in can.items() if any(p["id"] in confirmed for p in found)}
    out: list[StudyWay] = []
    # a study that names its product: that product's profile, else its dissolution data; never another product's
    for study, name in named:
        key = _key(name)
        out.append(StudyWay(study=study, way="use_profile", products=(names[key] or name,), ready=key in ready, named=name)
                   if key in can else StudyWay(study=study, way="add_dissolution", products=(name,), named=name))
    if none:
        # a profile whose product the model holds a formulation of is that formulation's release already
        open_ = sorted((k for k in can if k not in held), key=lambda k: k not in ready)   # confirmed first, then the register's
        if open_:
            products = tuple(names[k] for k in open_ if names[k])
            out += [StudyWay(study=s, way="use_profile", products=products, ready=open_[0] in ready) for s in none]
        elif here := products_here(ws):
            out += [StudyWay(study=s, way="add_dissolution", products=tuple(here)) for s in none]
        else:
            out += [StudyWay(study=s, way="add_product") for s in none]
    return out, {names[k] for k in ready if names[k]}


def formulation_way(ws: Workspace, problems: Sequence[str]) -> FormulationWay | None:
    """The lever for the readiness check's formulation problems (`problems`, its detail), or None (the docstring)."""
    none = list(dict.fromkeys(m["study"] for p in problems if (m := _NONE.match(p))))
    named = list(dict.fromkeys((m["study"], m["name"]) for p in problems if (m := _NAMED.match(p))))
    several = list(dict.fromkeys(m["study"] for p in problems if (m := _SEVERAL.match(p))))
    if not none and not named and not several:
        return None
    each, ready = _each(ws, none, named) if none or named else ([], set())
    each += [StudyWay(study=s, way="choose") for s in several if s not in {e.study for e in each}]
    # in the readiness check's order of its studies
    order: dict[str, int] = {}
    for p in problems:
        if m := _NONE.match(p) or _NAMED.match(p) or _SEVERAL.match(p):
            order.setdefault(m["study"], len(order))
    each.sort(key=lambda e: order[e.study])
    way = next(w for w in _ORDER if any(e.way == w for e in each))
    mine = [e for e in each if e.way == way]
    # the studies' products together, in the docstring's order: those a study names, then those whose data are confirmed,
    # then the register's (a stable sort keeps each study's own order within)
    wanted = {_key(e.named) for e in mine if e.named}
    products = sorted(dict.fromkeys(p for e in mine for p in e.products),
                      key=lambda p: (_key(p) not in wanted, way == "use_profile" and p not in ready))
    first = products[0] if products else None
    lead = first in ready if first is not None else all(e.ready for e in mine)
    return FormulationWay(way=way, products=tuple(products), studies=tuple(dict.fromkeys(e.study for e in mine)),
                          ready=lead if way == "use_profile" else True, each=tuple(each))
