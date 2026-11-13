"""T-42: the sub-domain draft checklists (biologics, dermal, ocular) are well-formed and inert.

The owner's decision 2 (plan docs/plans/2026-11-12-client-data-intake-redesign.md §7.9; contract
docs/plans/2026-11-12-intake-contracts.md §8.8): each sub-domain on the roadmap has a draft checklist in
``pbpk_domain.requirement_drafts``, written as requirement-template items, that claims no PK-Sim name, path, unit or
CPF id and that nothing live reads. The test sits here, not in pbpk-domain, because it needs
``modeler_project.requirements`` (L3), which an L0 test cannot import.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from importlib import resources
from pathlib import Path
from typing import Any

import pytest
import yaml

from modeler_intake import fields
from modeler_project import requirements
from modeler_project.brief import APPLICATIONS, ROUTES, Citation, FieldStatus, ProjectBrief, empty_brief
from modeler_project.brief_ops import agent_set
from modeler_project.requirements import application_additions, client_request, derive, evaluate_when, load_templates
from pbpk_domain import parameters

pytestmark = pytest.mark.req("T-42")

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = "pbpk_domain.requirement_drafts"
FOLDER = ROOT / "packages" / "pbpk-domain" / "src" / "pbpk_domain" / "requirement_drafts"
GOLDEN = ROOT / "services" / "engine-worker" / "golden"
DRAFTS = ("biologics", "dermal", "ocular")
ID_PREFIX = {"biologics": "REQ-DRAFT-bio.", "dermal": "REQ-DRAFT-derm.", "ocular": "REQ-DRAFT-oc."}
ENGINE_SUPPORT = {
    "biologics": "PK-Sim has a large-molecule model; the harvested catalog has no FcRn entry, so nothing here can be "
                 "placed today",
    "dermal": "no hit in the harvested catalog: PK-Sim has no built-in model; an engine decision comes first",
    "ocular": "no hit in the harvested catalog: PK-Sim has no built-in model; an engine decision comes first",
}
# the role of the scientist decision 2 requires, as data (the header) and on every item (its note's opening mark)
ROLE = {
    "biologics": "a PBPK scientist experienced in large-molecule (therapeutic protein) PBPK",
    "dermal": "a PBPK scientist experienced in dermal absorption modelling",
    "ocular": "a PBPK scientist experienced in ocular pharmacokinetics",
}
MARK = {
    "biologics": "UNVERIFIED: awaiting the named large-molecule PBPK scientist (decision 2).",
    "dermal": "UNVERIFIED: awaiting the named dermal absorption scientist (decision 2).",
    "ocular": "UNVERIFIED: awaiting the named ocular pharmacokinetics scientist (decision 2).",
}
HEADER = {"id", "version", "status", "applies_to", "engine_support", "named_scientist", "scientist_role", "items"}
# the requirement-item schema of modeler_project.requirements._item: the keys every draft item carries (the ones _item
# requires, the TO_HARVEST status, who provides the item and its marked note), then the ones it may carry. Left out on
# purpose: pksim (none harvested), data_category (no client-data sheet holds these data), purpose, per, plausibility.
ALWAYS = {"id", "label", "kind", "target", "group", "criticality", "pksim_status", "default_provider", "note"}
MAY = {"unit", "conditions", "needed_for", "condition_text", "when"}
KINDS = {"parameter", "dataset", "formulation", "system"}
CRITICALITY = {"REQUIRED", "CONDITIONAL", "OPTIONAL"}
STAGES = {f"S{n}" for n in range(8)}
# the keys requirements.evaluate_when reads, less `application`: a draft names no APP code
WHEN_KEYS = {"route", "food", "bcs", "pathway", "nonlinear", "ehc"}
# a number in an item is a reference, never a value: a plan section (§6.4), MS-01, the owner's decision 2 or the S9
# fraction (needed_for's stage ids are checked against STAGES instead)
REFERENCE = re.compile(r"§\d+(?:\.\d+)*|\bMS-01\b|\bdecision 2\b|\bS9 fraction\b")
THRESHOLD_WORDS = re.compile(r"%|\b(?:two|three|four|five|ten)?-?fold\b|\bdefault\b|\bthreshold|\bacceptance\b|\bcut-?off\b",
                             re.IGNORECASE)
CITE = (Citation(doc_sha256="a" * 64, page=1, quote="quoted from the proposal"),)


def _text(name: str) -> str:
    return resources.files(PACKAGE).joinpath(f"{name}.yaml").read_text(encoding="utf-8")


def _draft(name: str) -> dict[str, Any]:
    return yaml.safe_load(_text(name))


def _items() -> list[dict[str, Any]]:
    return [item for name in DRAFTS for item in _draft(name)["items"]]


def _keys(node: Any) -> Iterator[str]:
    """Every mapping key, at any depth."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield str(key)
            yield from _keys(value)
    elif isinstance(node, list):
        for value in node:
            yield from _keys(value)


def _leaves(node: Any) -> Iterator[Any]:
    if isinstance(node, dict):
        for value in node.values():
            yield from _leaves(value)
    elif isinstance(node, list):
        for value in node:
            yield from _leaves(value)
    else:
        yield node


def _comments(name: str) -> str:
    """The file's comment lines as one text, whitespace collapsed."""
    lines = [line.lstrip("#").strip() for line in _text(name).splitlines() if line.startswith("#")]
    return re.sub(r"\s+", " ", " ".join(lines))


def _brief(*sets: tuple[str, Any]) -> ProjectBrief:
    brief = empty_brief("Exampleamide", by="u")
    for path, value in sets:
        brief = agent_set(brief, path, value=value, unit=None, citations=CITE, status=FieldStatus.EXTRACTED,
                          confidence="A", by="a1")
    return brief


def _every_application_brief() -> ProjectBrief:
    return _brief(
        ("drug.modality", "large_molecule"), ("qoi.applications", list(APPLICATIONS)),
        ("scenarios[0].route", "subcutaneous"), ("scenarios[1].route", "dermal"), ("scenarios[2].route", "other"),
        ("scenarios[3].route", "oral"), ("scenarios[3].food_state", "fed"),
    )


def _harvested_names() -> set[str]:
    """PK-Sim names from the harvested catalog that cannot be mistaken for plain words: the internal names of process,
    formulation and expression types, the multi-word parameter names of the processes and formulations, calculation
    methods, event templates and populations. Single plain words (Kd, koff, Enzyme, Human) are also biochemistry or
    English, so they are left out."""
    catalog = json.loads((GOLDEN / "catalog.json").read_text(encoding="utf-8"))
    names = set()
    for kind in ("process_types", "formulation_types"):
        for entry in catalog[kind]:
            names.add(entry["internal_name"])
            names |= {parameter["name"] for parameter in entry["parameters"]}
    names |= {entry["type"] for entry in catalog["expression_types"]}
    names |= {name for methods in catalog["calculation_methods"].values() for name in methods}
    names |= {entry["name"] for entry in catalog["event_templates"]}
    names |= {name for populations in catalog["populations"].values() for name in populations}
    return {name for name in names if re.search(r"[^A-Za-z0-9]|[a-z][A-Z]", name)}


# --- the files ---------------------------------------------------------------------------------------------------


def test_the_package_holds_exactly_the_three_drafts():
    entries = {entry.name for entry in resources.files(PACKAGE).iterdir()} - {"__pycache__"}
    assert {name for name in entries if name.endswith(".yaml")} == {f"{name}.yaml" for name in DRAFTS}
    assert entries == {"__init__.py", *(f"{name}.yaml" for name in DRAFTS)}


@pytest.mark.parametrize("name", DRAFTS)
def test_each_draft_is_yaml_with_the_draft_header(name):
    draft = _draft(name)
    assert set(draft) == HEADER
    assert draft["id"] == f"req-draft-{name}"
    assert draft["version"] == "0.1-draft"
    assert draft["status"] == "DRAFT / UNVERIFIED"
    assert draft["applies_to"] == []
    assert draft["named_scientist"] is None   # the role is stated; the person is the owner's to name
    assert draft["scientist_role"] == ROLE[name]
    assert draft["engine_support"] == ENGINE_SUPPORT[name]
    assert draft["items"]


@pytest.mark.parametrize("name", DRAFTS)
def test_each_draft_opens_with_a_comment_block_saying_it_is_an_inert_draft(name):
    assert _text(name).startswith("# DRAFT CHECKLIST, INERT")
    comments = _comments(name)
    for words in ("Why it is inert", "pbpk_domain/requirement_drafts/", "load_templates", "applies_to is empty",
                  "no APP code", "DRAFT / UNVERIFIED", "every item below is unverified", "named_scientist: null",
                  "scientist_role", "decision 2", "TO_HARVEST", "no calculator", "no default value",
                  "no acceptance threshold", "default_provider", "condition_text"):
        assert words in comments, words


# --- the items ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", DRAFTS)
def test_items_follow_the_requirement_item_schema(name):
    for item in _draft(name)["items"]:
        assert ALWAYS <= set(item), item.get("id")
        assert set(item) <= ALWAYS | MAY, item["id"]
        assert all(isinstance(item[key], str) and item[key].strip() for key in ALWAYS), item["id"]
        assert item["kind"] in KINDS and item["criticality"] in CRITICALITY, item["id"]
        assert item["pksim_status"] == "TO_HARVEST", item["id"]
        assert set(item.get("needed_for", ())) <= STAGES, item["id"]
        assert all(isinstance(c, str) and c.strip() for c in item.get("conditions", ())), item["id"]


@pytest.mark.parametrize("name", DRAFTS)
def test_every_item_is_marked_unverified_with_the_scientist_it_awaits(name):
    # the mark is in the note, so it travels with an item into a requirement matrix (RequirementItem.note)
    for item in _draft(name)["items"]:
        assert item["note"].startswith(MARK[name]), item["id"]


@pytest.mark.parametrize("name", DRAFTS)
def test_who_provides_each_item(name):
    # the client is asked for everything but the system data, which come from the engine's databases (plan §6.4; the
    # live REQ-sp.ontogeny), never from client files
    for item in _draft(name)["items"]:
        assert item["default_provider"] == ("LIBRARY" if item["kind"] == "system" else "CLIENT"), item["id"]


@pytest.mark.parametrize("name", DRAFTS)
def test_conditions_are_stated_and_a_when_only_where_the_brief_can_read_it(name):
    for item in _draft(name)["items"]:
        if item["criticality"] != "CONDITIONAL":
            assert "condition_text" not in item and "when" not in item, item["id"]
            continue
        assert item.get("condition_text", "").strip(), item["id"]
        when = item.get("when")
        if when is None:
            continue
        assert isinstance(when, dict) and set(when) <= WHEN_KEYS, item["id"]
        assert set(when.get("route", ())) <= set(ROUTES), item["id"]


def test_a_route_condition_reads_the_briefs_scenarios():
    when = {item["id"]: item.get("when") for item in _items()}["REQ-DRAFT-bio.extravascular_pk"]
    assert evaluate_when(when, _brief(("scenarios[0].route", "subcutaneous"))) is True
    assert evaluate_when(when, _brief(("scenarios[0].route", "intramuscular"))) is True
    assert evaluate_when(when, _brief(("scenarios[0].route", "oral"))) is False
    assert evaluate_when(when, _brief()) is None


def test_item_ids_are_unique_and_all_draft_ids():
    ids = [item["id"] for item in _items()]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("REQ-DRAFT-") for i in ids)
    for name in DRAFTS:
        assert all(item["id"].startswith(ID_PREFIX[name]) for item in _draft(name)["items"]), name
    live = {raw["id"] for template in load_templates() for raw in template["items"]}
    assert not live & set(ids)


@pytest.mark.parametrize("name", DRAFTS)
def test_no_pksim_name_path_or_unit_anywhere(name):
    draft = _draft(name)
    keys = set(_keys(draft))
    assert "pksim" not in keys
    assert not re.search(r"\bpksim\s*:", _text(name))   # not even commented out
    # a template's unit is the stored, engine-side unit, and none is harvested: the client's unit is kept as reported
    assert "unit" not in keys
    # PK-Sim paths are "|"-separated; no draft string holds one
    assert not [leaf for leaf in _leaves(draft) if isinstance(leaf, str) and "|" in leaf]
    # nor a harvested PK-Sim name, in the items or the comments (matched by case, as the engine spells it)
    text = _text(name)
    found = [n for n in _harvested_names() if re.search(rf"(?<![A-Za-z0-9_]){re.escape(n)}(?![A-Za-z0-9_])", text)]
    assert not found


def test_the_harvested_name_check_has_names_to_check():
    names = _harvested_names()
    assert len(names) >= 20
    assert not {"Kd", "koff", "Enzyme", "Human"} & names   # plain words stay out


@pytest.mark.parametrize("name", DRAFTS)
def test_no_default_value_or_threshold_is_given(name):
    for item in _draft(name)["items"]:
        # every value of every item is text: no number, flag or bound slipped in as a default or an acceptance threshold
        assert all(isinstance(leaf, str) for leaf in _leaves(item)), item["id"]
        # nor written as text: no number but a reference, no percentage, no fold change, no threshold word
        for key, value in item.items():
            if key == "needed_for":
                continue
            for leaf in _leaves(value):
                assert not re.search(r"\d", REFERENCE.sub("", leaf)), (item["id"], key, leaf)
                assert not THRESHOLD_WORDS.search(leaf), (item["id"], key, leaf)


def test_no_target_claims_a_cpf_id():
    rules = parameters.registry().parameters
    exact = {rule.key for rule in rules if not rule.is_family}
    families = tuple(rule.key for rule in rules if rule.is_family)
    parameter_targets = [item["target"] for item in _items() if item["kind"] == "parameter"]
    assert parameter_targets
    for item in _items():
        target = item["target"]
        # the contract asks it of parameter targets; the drafts claim no dataset class either
        assert target.startswith("draft."), item["id"]
        base = target.partition("@")[0]
        assert base not in exact and not base.startswith(families), target
        assert parameters.placement(target) is None, target
        assert fields.field(target) is None, target   # nor does the intake vocabulary take it as a field or CPF id


# --- inert -------------------------------------------------------------------------------------------------------


def test_the_live_loader_returns_the_six_templates_and_no_draft():
    templates = load_templates()
    assert len(templates) == 6
    assert not [t["id"] for t in templates if t["id"].startswith("req-draft-")]
    assert not [raw["id"] for t in templates for raw in t["items"] if raw["id"].startswith("REQ-DRAFT-")]


def test_derive_with_every_application_picked_has_no_draft_item():
    brief = _every_application_brief()
    assert {str(a).split(" ", 1)[0] for a in brief.value("qoi.applications")} == {a.split(" ", 1)[0] for a in APPLICATIONS}
    matrix = derive(brief)
    assert matrix.items
    assert any(note.startswith("large molecule") for note in matrix.notes)   # APP-16 and the modality add a note only
    assert not [i.req_id for i in matrix.items if i.req_id.startswith("REQ-DRAFT-")]
    assert not [t for t in matrix.templates if t.startswith("req-draft-")]
    assert not [line.req_id for line in client_request(matrix) if line.req_id.startswith("REQ-DRAFT-")]
    added = {label for labels in application_additions().values() for label in labels}
    assert not added & {item["label"] for item in _items()}


def test_promoted_as_they_are_the_drafts_would_ask_the_client(monkeypatch):
    # a probe, not a promotion: derive reads the three drafts as if each applied to every project, to show that the
    # live schema takes every item as written (who provides it, its condition, its UNVERIFIED mark)
    drafts = tuple({**_draft(name), "applies_to": "all"} for name in DRAFTS)
    monkeypatch.setattr(requirements, "load_templates", lambda: drafts)
    matrix = requirements.derive(_every_application_brief())
    assert {i.req_id for i in matrix.items} == {item["id"] for item in _items()}
    for item in matrix.items:
        assert item.provider == ("LIBRARY" if item.kind == "system" else "CLIENT"), item.req_id
        assert item.provider_source == "template default", item.req_id
        assert item.pksim is None and item.pksim_status == "TO_HARVEST" and item.unit is None, item.req_id
        assert item.note.startswith("UNVERIFIED: awaiting the named "), item.req_id
        assert item.applies == "yes", item.req_id   # the brief has a subcutaneous scenario; no other `when` excludes
        assert bool(item.condition_text) == (item.criticality == "CONDITIONAL"), item.req_id
    asked = {line.req_id for line in requirements.client_request(matrix)}
    assert asked == {item["id"] for item in _items() if item["kind"] != "system"}


def test_the_drafts_are_outside_every_locked_file():
    manifest = json.loads((ROOT / "docs" / "architecture" / "locked-files.json").read_text(encoding="utf-8"))
    drafts = {FOLDER / f"{name}.yaml" for name in DRAFTS} | {FOLDER / "__init__.py"}
    assert all(path.is_file() for path in drafts)
    covered = {path for entry in manifest["patterns"] for path in ROOT.glob(entry["pattern"])}
    assert not covered & drafts
    assert not {ROOT / entry["path"] for entry in manifest["files"]} & drafts


def test_engine_support_matches_the_harvested_engine():
    # what each draft's engine_support and comment block say of the harvested catalog and the reference models; a
    # re-harvest that finds FcRn, a protein drug, a skin or an eye model fails here, and the drafts are then brought up
    # to date
    text = (GOLDEN / "catalog.json").read_text(encoding="utf-8")
    catalog = json.loads(text)
    lowered = text.lower()
    assert "fcrn" not in lowered
    assert not re.search(r"\b(dermal|transdermal|topical)\b", lowered)
    assert not re.search(r"\b(ocular|eyes?|vitreous|retina|cornea)\b", lowered)
    golden = {path: path.read_text(encoding="utf-8") for path in sorted(GOLDEN.glob("**/*.json"))}
    administrations = {
        match.lower() for content in golden.values()
        for match in re.findall(r'"ApplicationType"\s*:\s*"([^"]*)"', content)
    }
    assert administrations
    assert not [a for a in administrations if re.search(r"subcut|derm|topic|ocul|eye|vitre", a)]
    # every compound harvested is a small molecule
    flags = [flag for content in golden.values() for flag in re.findall(r'"IsSmallMolecule"\s*:\s*(\w+)', content)]
    assert flags and set(flags) == {"true"}
    # the binding process and the protein expression type the biologics draft names are seen only in those models
    fixtures = {entry["name"] for entry in catalog["fixtures"]}
    seen = {entry["internal_name"]: entry["seen_in"] for entry in catalog["process_types"]
            if re.search("binding", entry["internal_name"], re.IGNORECASE)}
    seen |= {entry["type"]: entry["seen_in"] for entry in catalog["expression_types"]
             if re.search("protein", entry["type"], re.IGNORECASE)}
    assert len(seen) == 2
    assert all(set(models) <= fixtures for models in seen.values()), seen
