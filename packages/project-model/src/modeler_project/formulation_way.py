"""What gives a tablet study its formulation, as the project stands (final review round 4: the step bar named "add a
product" whatever the project held, and on a project whose products had dissolution profiles it opened an empty form;
round 5: the way is read for each study, and a product's profile settles only a study it can settle; round 6: a study
whose own client data name its product is a study that names it).

The readiness check "formulations of solid studies" says what each tablet or capsule study lacks, one problem per study
(`pbpk_domain.cpf.formulations`: "<study>: <problem>"). Which lever settles a missing formulation depends on what is here
and on what the study names, so it is read here once, from the project, for every place that names it (the step bar and
Review & sign through `steps.inputs_step`, To do's formulation item and Products and dissolution through `inputs.todo`).
Each study has its own way (`each`):

- a study that names its product is settled by that product only: one whose record names its formulation ("the CPF
  defines no formulation 'Test 10 mg'"), or (round 6) one whose own client data name its product (`file_products`: the
  client template's Studies.product, read with the sheet form, and the delivery's values of the study that name a
  product, the link a product's card shows as "Role Test · study CL-02"; the usual way a study names its product, which
  the study record does not carry). `use_profile` with that product when a dissolution profile of it can give a release
  (read as a curve, with a Weibull fit: what "Use this profile as the release" on a product's card takes), whether or
  not a formulation of another name was made from it already (used again, it gives the formulation the study names),
  else `add_dissolution` with it (its dissolution data are added, or the client is asked). Another product's profile
  never settles it: a study whose file names Test 10 mg is never offered Brand 10 mg's profile. Names are compared as
  the cards compare them (`_key`: "Product Test 10 MG" is Test 10 mg); a file that names no product names none, and a
  name no product here has is the study's all the same (its dissolution data are added, or the client is asked);
- a study that names none, while the model holds no formulation: `use_profile` when a dissolution profile here can give a
  release and is not the release of a formulation already (`products`: its product; a profile of no product counts too,
  its "Use as release" is under the profiles of no product); else `add_dissolution` with the products here (the
  delivery's with values, the dissolution register's, the sheet form's compositions, the proposal's); else
  `add_product` (no product is here at all: the product the study used is added, or the client is asked);
- a study that names none while the model holds several formulations: `choose` (a person chooses the one it used; round
  7: `named` is the product its own client data name, if they name one, so its choice lists that product's formulation
  first and preselects none).

Round 7 (round 6's skeptic): a tablet study the readiness check passes may still use another product's release. A study
whose record names no formulation uses the model's only one (`resolve_formulation_name`), whatever product its own file
names, so in a bioequivalence project (the Test study's file names Test 10 mg, the Reference study's Brand 10 mg, and only
Brand 10 mg has a usable profile) using Brand 10 mg's profile for the Reference study would settle the Test study with the
reference's release. Whether the build should tie such a study to its named product is the owner's question; it is not
changed here. With `rows` (the study catalog's, To do's), each tablet study that names no formulation while the model
holds exactly one, and whose own client data name a product that formulation is not (by its name, or by the product of
the dissolution profile its release was made from), keeps a way of its own as a study that names its product (above),
with `uses`, the formulation the model would use for it: To do keeps its formulation item open for it and asks the client
for its product's data, and its row says so. The step bar and Review & sign read the readiness check only.

`products` are in this order: the products the studies name first, then those whose dissolution data a person confirmed
(their profile can be used now; "Use this profile as the release" is refused before), then the register's order. The
first is the one a link opens, and `ready` says whether its profile can be used now (round 6: a study's own `ready` is
its first product's too, never that of a profile of no product listed before it). The way the step bar names (the
model's own fields) is the first of `use_profile`, `add_dissolution`, `add_product` and `choose` that a study has, for
the studies it settles; `each` says every study's own (Products and dissolution says it on the study's row, and To do's
"Ask the client" asks for every study whose way offers the client: `add_dissolution`, `add_product`; a study that names
its product, for that product's data). None when no problem is one of these (a formulation not complete, of a type the
builder does not place, a study record not complete): the formulation item on To do says each problem.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict

from modeler_project.artifacts import ArtifactKind
from modeler_project.workspace import Workspace

if TYPE_CHECKING:
    from modeler_project.ledger_view import LedgerView
    from pbpk_domain.cpf.models import CPF

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
    the first one's profile can be used now; `named`: the product the study names (its record's formulation, or the
    product its own client data name), if it names one; `uses` (round 7): the formulation the model would use for it
    while that is another product's (the model's only formulation), else None."""

    model_config = ConfigDict(frozen=True)

    study: str
    way: FormulationLever
    products: tuple[str, ...] = ()
    ready: bool = True
    named: str | None = None
    uses: str | None = None


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


def _study(name: Any) -> str:
    """A study's id as the ledger compares labels (`ledger_entities.label_key`: case, spaces and punctuation aside, the
    digit runs a label writes apart kept apart)."""
    from modeler_project.ledger_entities import label_key

    return label_key(str(name or ""))


def usable(profile: dict[str, Any]) -> bool:
    """A dissolution profile that can give a formulation's release on its product's card: read as a curve, with a
    Weibull fit (the card's "Use this profile as the release"; a plateau below complete release is a table)."""
    return profile.get("release_model") != "Table" and (profile.get("fit") or {}).get("t50_min") is not None


def _profiles(ws: Workspace) -> list[dict[str, Any]]:
    from modeler_project.dissolution_register import profiles

    return profiles(ws)


def _release_profile(ws: Workspace, cpf: CPF | None, name: str) -> str | None:
    """The dissolution profile a formulation's release was made from (by id: the release's evidence names its profile),
    or None (a release from elsewhere, or none)."""
    from modeler_project.evidence import EvidenceItem

    record = cpf.get(f"form.{name}.type") if cpf is not None else None
    evidence = str(record.provenance.evidence or "") if record is not None and record.provenance is not None else ""
    found = ws.latest(ArtifactKind.EVIDENCE, evidence.split("@")[0]) if evidence else None
    # its source is "<profile id> v<version>: <label>" (`dissolution_register.propose_release_model`)
    return EvidenceItem.from_content(found.content).source.locator.split(" ", 1)[0] if found is not None else None


def _released(ws: Workspace) -> tuple[set[str], set[str]]:
    """What gives a release already: the dissolution profiles a formulation the model holds was made from (by id: the
    release's evidence names its profile), and the formulations the model holds (by name, as `_key` compares a
    product's)."""
    from modeler_project.inputs import current_cpf
    from modeler_project.study_requirements import formulations_held

    cpf = current_cpf(ws)
    held = formulations_held(cpf)
    used = {found for name in held if (found := _release_profile(ws, cpf, name)) is not None}
    return used, {_key(name) for name in held}


class _LedgerNames(NamedTuple):
    """What the ledger names that the ways read: the delivery's products with values (by label, in the ledger's order),
    and each product a study's values name (the study's or its arm's id as its dataset is named, the product's label),
    in the ledger's order."""

    products: tuple[str, ...]
    studies: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class _Read:
    """What a kept reading is kept by (round 7): where it was read from and the signature of what it read; the workspace
    it is read through is carried, not compared (a request's own), so a later request with the same signature finds it."""

    where: str
    signature: tuple[Any, ...]
    ws: Workspace = field(compare=False, hash=False)


def _signature(path: Path | None) -> tuple[int, int] | None:
    try:
        found = path.stat() if path is not None else None
    except FileNotFoundError:
        return None
    return (found.st_size, found.st_mtime_ns) if found is not None else None


def _ledger_names(ws: Workspace) -> _LedgerNames:
    """`_LedgerNames`, read again only when the ledger changed (round 7: a fold of the ledger on every GET /inputs and GET
    /steps cost about 0.08 s on the review data while a tablet study lacked a formulation). The fold reads the ledger's two
    logs (and the extracts they name, written once), mappings.jsonl and review.jsonl, all append-only: their sizes and
    modification times say whether anything was written since, read before the fold so a write during it is read next
    time. Kept in this process only (`lru_cache`, as the other read caches): a reading, never a job's state (C8), right in
    any process because it is keyed by what it read."""
    from modeler_project.intake_store import IntakeStore

    store = IntakeStore(ws)
    if not store.available:
        return _LedgerNames((), ())
    signature = tuple(_signature(log.path) for log in (store.facts, store.entities, store.mappings, store.review))
    return _ledger_names_read(_Read(str(store.base), signature, ws))


@lru_cache(maxsize=64)
def _ledger_names_read(read: _Read) -> _LedgerNames:
    from modeler_project.client_data import _arm_id
    from modeler_project.ledger_view import LedgerView

    reader = LedgerView(read.ws)
    products = tuple(e.label for e in reader.entities("product") if reader.values(product=e.id))
    arms: dict[str, list[str]] = {}
    for arm in reader.entities("arm"):
        if arm.parent:
            arms.setdefault(arm.parent, []).append(arm.label)
    studies: list[tuple[str, str]] = []
    for study in reader.entities("study"):
        for value in reader.values(study=study.id):
            product = reader.entity(value.entity.product) if value.entity.product else None
            if product is None:
                continue
            arm = reader.entity(value.entity.arm) if value.entity.arm else None
            studies += [(label, product.label) for label in ([_arm_id(study.label, arm.label)] if arm is not None
                                                              else [_arm_id(study.label, a) for a in arms.get(study.id, [])])]
            studies.append((study.label, product.label))
    return _LedgerNames(products, tuple(studies))


def products_here(ws: Workspace, reader: LedgerView | None = None) -> list[str]:
    """The products the project holds, each once, in this order: the delivery's products with values, the products of
    the dissolution profiles and of the compositions the sheet form read, and the products the proposal names. (`reader`
    is no longer read: the ledger's names are kept between requests while it is unchanged, round 7.)"""
    from modeler_project.brief import ProjectBrief
    from modeler_project.client_data import document_compositions

    names: list[str] = list(_ledger_names(ws).products)
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


def _sheets_signature(ws: Workspace) -> tuple[tuple[str, int], ...] | None:
    """Whether the client files' records changed (round 7): each record's folder and its modification time (a version is
    written once, as a new file in its record's folder), or None where the project store keeps no files (read each time)."""
    root = getattr(ws.store, "root", None)
    base = (Path(root) / ws.tenant_id / "projects" / ws.project_id / "artifacts" / ArtifactKind.CLIENT_SUBMISSION.value
            if root is not None else None)
    try:
        return tuple(sorted((d.name, d.stat().st_mtime_ns) for d in base.iterdir())) if base is not None else None
    except FileNotFoundError:
        return None


def file_products(ws: Workspace, reader: LedgerView | None = None) -> dict[str, tuple[str, ...]]:
    """The products each study's own client data name (round 6), by the study's id as `_study` compares it (the id the
    readiness check says, the dataset's): the client template's Studies.product of its row (the sheet form keeps the rows,
    `client_data`; an arm's row by `<study>-<treatment>`, as its dataset is named), and the delivery's values of the study
    that name a product (the study's label; an arm's value by `<label>-<arm>` and the label, a value of the whole study by
    the label and each of its arms, as the delivery's datasets are named). Each name once, as `_key` compares names, in
    the files' order. A study whose files name no product is not here: no link is made up.

    Round 7 (speed): read again only when the client files' records or the ledger changed (`_sheets_signature`,
    `_ledger_names`), so the step bar and To do add no time to each request; `reader` is no longer read."""
    sheets, ledger = _sheets_signature(ws), _ledger_names(ws)
    if sheets is None:
        return dict(_file_products_read(_Read("", (), ws), ledger))
    where = f"{getattr(ws.store, 'root', '')}|{ws.tenant_id}|{ws.project_id}"
    return dict(_file_products_kept(_Read(where, sheets, ws), ledger))


def _file_products_read(read: _Read, ledger: _LedgerNames) -> tuple[tuple[str, tuple[str, ...]], ...]:
    from modeler_project.client_data import _arm_id, submissions

    out: dict[str, dict[str, str]] = {}

    def add(study: Any, product: Any) -> None:
        name = " ".join(str(product or "").split())
        if str(study or "").strip() and name:
            out.setdefault(_study(study), {}).setdefault(_key(name), name)

    for sub in submissions(read.ws):
        if sub.get("template"):
            for row in sub.get("studies", []):
                values = row.get("values", {})
                add(_arm_id(str(values.get("study_id") or ""), str(values.get("treatment") or "")), values.get("product"))
    for study, product in ledger.studies:
        add(study, product)
    return tuple((study, tuple(names.values())) for study, names in out.items())


# kept while the client files' records and the ledger's names are unchanged (a store with no files is read each time)
_file_products_kept = lru_cache(maxsize=64)(_file_products_read)


def _elsewhere(ws: Workspace, rows: Sequence[dict[str, Any]], cpf: CPF | None,
               said: dict[str, tuple[str, ...]] | None) -> tuple[str | None, list[tuple[str, tuple[str, ...]]]]:
    """Round 7 (the module docstring): the model's only formulation, and each tablet study of `rows` that names no
    formulation (so would use it) while its own client data name only products it is not, with those products. ([] while
    the model holds none or several: the readiness check names those studies.)"""
    from modeler_project.inputs import SOLID
    from pbpk_domain.cpf.formulations import formulation_names

    names = formulation_names(cpf) if cpf is not None else ()
    loose = [str(r["study_id"]) for r in rows if r.get("formulation") in SOLID and not r.get("formulation_name")]
    if len(names) != 1 or not loose:
        return None, []
    said = said if said is not None else file_products(ws)
    if not any(said.get(_study(s)) for s in loose):
        return None, []
    only = names[0]
    # what the formulation is: its name, and the product of the profile its release was made from
    profile = _release_profile(ws, cpf, only)
    theirs = {_key(only)} | {_key(p["key"].get("product")) for p in _profiles(ws) if profile and p["id"] == profile
                             and p["key"].get("product")}
    return only, [(s, said[_study(s)]) for s in loose
                  if said.get(_study(s)) and not any(_key(n) in theirs for n in said[_study(s)])]


def _each(ws: Workspace, none: list[str], named: list[tuple[str, tuple[str, ...]]]) -> tuple[list[StudyWay], set[str]]:
    """Each study's way for the problems a product settles (the docstring), and the products whose profile can be used
    now (their dissolution data confirmed)."""
    from modeler_project.client_review import confirmed_profiles

    used, held = _released(ws)
    confirmed = confirmed_profiles(ws)
    # the profiles that can give a release, by their product's key ("" for a profile of no product), in the register's
    # order; for a study that names none, a profile a formulation was made from already gives that formulation's release
    # (`open_`), while a study that names its product may use its product's again (`mine`)
    mine: dict[str, list[dict[str, Any]]] = {}
    for p in _profiles(ws):
        if usable(p):
            mine.setdefault(_key(p["key"].get("product")), []).append(p)
    names = {k: str(found[0]["key"].get("product") or "") for k, found in mine.items()}
    ready = {k for k, found in mine.items() if any(p["id"] in confirmed for p in found)}
    out: list[StudyWay] = []
    # a study that names its product: that product's profile, else its dissolution data; never another product's (a
    # product it names that has a card or a profile here is said as it is named there)
    known = {_key(n): n for n in products_here(ws)} if named else {}
    for study, said in named:
        keys = list(dict.fromkeys(_key(n) for n in said))
        spelled = {_key(n): names.get(_key(n)) or known.get(_key(n)) or n for n in said}
        profiled = [k for k in keys if k in mine]
        out.append(StudyWay(study=study, way="use_profile", products=tuple(spelled[k] for k in profiled),
                            ready=profiled[0] in ready, named=spelled[keys[0]])
                   if profiled else StudyWay(study=study, way="add_dissolution", products=tuple(spelled[k] for k in keys),
                                             named=spelled[keys[0]]))
    if none:
        # a profile whose product the model holds a formulation of is that formulation's release already
        can = {k: [p for p in found if p["id"] not in used] for k, found in mine.items() if k not in held}
        open_ = sorted((k for k, found in can.items() if found),
                       key=lambda k: not any(p["id"] in confirmed for p in can[k]))   # confirmed first, then the register's
        if open_:
            products = tuple(names[k] for k in open_ if names[k])
            # its `ready` is its first product's (round 6: it was the first profile's, of no product perhaps)
            first = next((k for k in open_ if names[k]), open_[0])
            now = any(p["id"] in confirmed for p in can[first])
            out += [StudyWay(study=s, way="use_profile", products=products, ready=now) for s in none]
        elif here := products_here(ws):
            out += [StudyWay(study=s, way="add_dissolution", products=tuple(here)) for s in none]
        else:
            out += [StudyWay(study=s, way="add_product") for s in none]
    return out, {names[k] for k in ready if names[k]}


def formulation_way(ws: Workspace, problems: Sequence[str], *, rows: Sequence[dict[str, Any]] | None = None,
                    cpf: CPF | None = None) -> FormulationWay | None:
    """The lever for the readiness check's formulation problems (`problems`, its detail), or None (the docstring). With
    `rows` (the study catalog's) and `cpf` (the model's inputs), round 7: also each tablet study that would use another
    product's release (`_elsewhere`), after the readiness check's studies, its `uses` set."""
    none = list(dict.fromkeys(m["study"] for p in problems if (m := _NONE.match(p))))
    named = list(dict.fromkeys((m["study"], (m["name"],)) for p in problems if (m := _NAMED.match(p))))
    several = list(dict.fromkeys(m["study"] for p in problems if (m := _SEVERAL.match(p))))
    # a study whose own client data name its product names it (round 6): the readiness check reads the study record,
    # which does not carry it (read once, and only where a study may need it)
    said = file_products(ws) if none or several else None
    only, elsewhere = _elsewhere(ws, rows, cpf, said) if rows is not None else (None, [])
    if not none and not named and not several and not elsewhere:
        return None
    if none:
        named += [(s, said[_study(s)]) for s in none if said.get(_study(s))]
        none = [s for s in none if not said.get(_study(s))]
    named += elsewhere
    each, ready = _each(ws, none, named) if none or named else ([], set())
    uses = {s for s, _names in elsewhere}
    each = [e.model_copy(update={"uses": only}) if e.study in uses else e for e in each]
    # a study that names none and chooses among several: the product its own file names, if any, so its choice lists that
    # product's formulation first and preselects none (round 7)
    each += [StudyWay(study=s, way="choose", named=said[_study(s)][0] if said and said.get(_study(s)) else None)
             for s in several if s not in {e.study for e in each}]
    # in the readiness check's order of its studies, then the studies that would use another product's release
    order: dict[str, int] = {}
    for p in problems:
        if m := _NONE.match(p) or _NAMED.match(p) or _SEVERAL.match(p):
            order.setdefault(m["study"], len(order))
    for s, _names in elsewhere:
        order.setdefault(s, len(order))
    each.sort(key=lambda e: order[e.study])
    way = next(w for w in _ORDER if any(e.way == w for e in each))
    mine = [e for e in each if e.way == way]
    # the studies' products together, in the docstring's order: those a study names, then those whose data are confirmed,
    # then the register's (a stable sort keeps each study's own order within)
    wanted = {_key(p) for e in mine if e.named for p in e.products}
    products = sorted(dict.fromkeys(p for e in mine for p in e.products),
                      key=lambda p: (_key(p) not in wanted, way == "use_profile" and p not in ready))
    first = products[0] if products else None
    lead = first in ready if first is not None else all(e.ready for e in mine)
    return FormulationWay(way=way, products=tuple(products), studies=tuple(dict.fromkeys(e.study for e in mine)),
                          ready=lead if way == "use_profile" else True, each=tuple(each))


def elsewhere_problem(e: StudyWay) -> str:
    """A study that would use another product's release, as the formulation item's problem (round 7), in the readiness
    check's manner ("<study>: …"; the page says it in words): what its file names, and the formulation the model would use."""
    return (f"{e.study}: its file names {e.named}, but the CPF's only formulation '{e.uses}' would be used (the study names "
            "no formulation)")
