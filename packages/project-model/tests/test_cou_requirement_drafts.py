"""T-42: the requirement drafts per context of use (the owner's decision D5, 2026-11-24) are well-formed and inert.

Decision D5 of docs/plans/2026-11-24-data-story-next-phase.md: the requirement lists per context of use are drafted
from the literature as UNVERIFIED drafts, in ``pbpk_domain.requirement_drafts.context_of_use``; they become templates
only after the owner's review, and the locked templates are not changed. This test checks the drafts' format, that
every CONDITIONAL item's trigger names the core property vocabulary, that every source is one the three literature
reviews cite, that no PK-Sim name, path, unit, default or unsourced number slipped in, and that nothing live reads
them. It sits here, not in pbpk-domain, because it needs ``modeler_project.requirements`` (L3).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from importlib import resources
from pathlib import Path
from typing import Any, get_args

import pytest
import yaml

from modeler_intake.room_specs import FIELDS, TOPICS, TableKind
from modeler_project.brief import (
    APPLICATIONS,
    DATA_CATEGORIES,
    ROUTES,
    Citation,
    FieldStatus,
    ProjectBrief,
    definition_of,
    empty_brief,
)
from modeler_project.brief_ops import agent_set
from modeler_project.requirements import Provider, client_request, derive, load_templates

pytestmark = pytest.mark.req("T-42")

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = "pbpk_domain.requirement_drafts.context_of_use"
FOLDER = ROOT / "packages" / "pbpk-domain" / "src" / "pbpk_domain" / "requirement_drafts" / "context_of_use"
GOLDEN = ROOT / "services" / "engine-worker" / "golden"
REVIEWS = tuple(ROOT / "docs" / "research" / f"2026-11-24-{name}.md"
                for name in ("regulatory-data-by-context-of-use", "pbbm-absorption-inputs", "clinical-pk-data-curation"))
COU = ("ddi_victim", "ddi_perpetrator", "transporter_ddi", "food_effect", "pediatric", "organ_impairment",
       "pbbm_bridging_vbe", "acid_reducing_agents", "fih_dose_prediction", "special_populations")
FILES = ("core", *COU, "context_only")
PREFIXES = {
    "core": ("core.",), "ddi_victim": ("ddiv.",), "ddi_perpetrator": ("ddip.",), "transporter_ddi": ("tddi.",),
    "food_effect": ("fe.",), "pediatric": ("ped.",), "organ_impairment": ("ri.", "hi."), "pbbm_bridging_vbe": ("vbe.",),
    "acid_reducing_agents": ("ara.",), "fih_dose_prediction": ("fih.",), "special_populations": ("preg.", "ger.", "eth."),
    "context_only": ("ctx.",),
}
HEADER = {"id", "version", "status", "context_of_use", "applies_to", "derived_from", "items"}
EXTRA_HEADER = {"core": {"item_keys", "statuses", "trigger_grammar", "properties"},
                "organ_impairment": {"subcontexts"}, "special_populations": {"subcontexts"}}
STATUSES = ("REQUIRED", "USUALLY_NEEDED", "CONDITIONAL", "OPTIONAL", "NOT_NEEDED")
KINDS = {"parameter", "dataset", "formulation", "system", "activity"}
ALWAYS = {"id", "label", "group", "kind", "cou_status", "why", "alternatives", "room_fields", "data_category",
          "default_provider", "sources", "note"}
CONTEXT_ONLY_KEYS = {"kept_as", "trigger_request_text", "triggers_request_for", "context_for"}
CONDITION_KEYS = {"property", "equals", "in", "any_of", "above", "below", "threshold_source", "direction", "threshold"}
PROPERTY_KEYS = {"about", "type", "how", "determined_by"}
PROPERTY_MAY = {"room_fields", "brief_fields"}
ROOM_PREFIX = {"field": set(FIELDS), "table": set(get_args(TableKind)), "topic": set(TOPICS)}
SOURCE = re.compile(
    r"^(?P<pmid>.+?, PMID (?P<id>\d+)(?: \(.+\))?)$"
    r"|^(?P<doi>.+?, doi:(?P<doi_id>10\.\S+?))(?: \(.+\))?$"
    r"|^(?P<consensus>(?P<surname>[^\s,]+).* \(Consensus only\))$"
    r"|^Guidance: (?P<guidance>.+?)(?: \[recalled, verify\])?$"
    r"|^Review: (?P<review>docs/research/\S+\.md) §\d+(?:\.\d+)* \(the row cites no primary source\)$"
)
CITE = (Citation(doc_sha256="a" * 64, page=1, quote="quoted from the proposal"),)


def _text(name: str) -> str:
    return resources.files(PACKAGE).joinpath(f"{name}.yaml").read_text(encoding="utf-8")


def _draft(name: str) -> dict[str, Any]:
    return yaml.safe_load(_text(name))


def _items(*names: str) -> list[dict[str, Any]]:
    return [item for name in (names or FILES) for item in _draft(name)["items"]]


def _ids(*names: str) -> set[str]:
    return {item["id"] for item in _items(*names)}


def _leaves(node: Any) -> Iterator[Any]:
    if isinstance(node, dict):
        for value in node.values():
            yield from _leaves(value)
    elif isinstance(node, list):
        for value in node:
            yield from _leaves(value)
    else:
        yield node


def _keys(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield str(key)
            yield from _keys(value)
    elif isinstance(node, list):
        for value in node:
            yield from _keys(value)


def _conditions(trigger: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """The leaf conditions of a trigger, through any and all."""
    combinators = {"any", "all"} & set(trigger)
    if combinators:
        assert len(trigger) == 1, trigger
        (combinator,) = combinators
        assert isinstance(trigger[combinator], list) and len(trigger[combinator]) >= 2, trigger
        for part in trigger[combinator]:
            yield from _conditions(part)
    else:
        yield trigger


def _reviews() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in REVIEWS)


def _harvested_names() -> set[str]:
    """PK-Sim names from the harvested catalog that cannot be mistaken for plain words (as in test_requirement_drafts)."""
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


def test_the_sub_package_holds_exactly_the_twelve_drafts():
    entries = {entry.name for entry in resources.files(PACKAGE).iterdir()} - {"__pycache__"}
    assert entries == {"__init__.py", *(f"{name}.yaml" for name in FILES)}


@pytest.mark.parametrize("name", FILES)
def test_each_file_loads_with_the_draft_header(name):
    draft = _draft(name)
    assert set(draft) == HEADER | EXTRA_HEADER.get(name, set())
    assert draft["id"] == "cou-draft-" + name.replace("_", "-")
    assert draft["version"] == "0.1-draft"
    assert draft["status"] == "DRAFT_UNVERIFIED"
    assert draft["applies_to"] == []
    sentence = draft["context_of_use"]
    assert isinstance(sentence, str) and sentence.endswith(".") and sentence.count(". ") == 0, sentence
    assert draft["derived_from"] and all((ROOT / path).is_file() for path in draft["derived_from"].values())
    assert set(draft["derived_from"].values()) <= {str(path.relative_to(ROOT)) for path in REVIEWS}
    assert draft["items"]


@pytest.mark.parametrize("name", FILES)
def test_each_file_opens_with_a_comment_saying_where_it_came_from_and_that_it_is_inert(name):
    text = _text(name)
    assert text.startswith("# DRAFT ")
    comments = re.sub(r"\s+", " ", " ".join(line.lstrip("#").strip() for line in text.splitlines() if line.startswith("#")))
    for words in ("INERT", "D5", "UNVERIFIED", "Where it came from", "docs/research/2026-11-24-", "applies_to is empty",
                  "No PK-Sim name, path or unit", "no default value", "no acceptance threshold"):
        assert words in comments, words


def test_the_review_summary_lists_every_item():
    # the owner reviews the drafts through this summary, so it must not fall behind the files
    summary = (ROOT / "docs" / "research" / "2026-11-24-cou-requirement-drafts-for-review.md").read_text(encoding="utf-8")
    assert not [i for i in sorted(_ids()) if f"`{i}`" not in summary]
    assert not [p for p in _draft("core")["properties"] if f"`{p}`" not in summary]


def test_the_package_docstring_says_what_the_drafts_are():
    doc = re.sub(r"\s+", " ", resources.files(PACKAGE).joinpath("__init__.py").read_text(encoding="utf-8"))
    for words in ("UNVERIFIED drafts", "owner's review", "Data room may show them, labelled as drafts", "no data plan",
                  "gate or live template reads them", "load_templates", "applies_to", "test_cou_requirement_drafts.py"):
        assert words in doc, words


# --- the items ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", FILES)
def test_items_have_the_documented_keys(name):
    documented = set(_draft("core")["item_keys"])
    for item in _draft(name)["items"]:
        assert ALWAYS <= set(item) <= documented, (item.get("id"), set(item) - documented, ALWAYS - set(item))
        assert all(isinstance(item[key], str) and item[key].strip() for key in ("id", "label", "group", "why", "note"))
        assert isinstance(item["alternatives"], list) and all(isinstance(a, str) and a.strip() for a in item["alternatives"])
        assert all(isinstance(r, str) and r.strip() for r in item.get("record_with", ())), item["id"]
        assert item["kind"] in KINDS, item["id"]
        assert item["data_category"] in DATA_CATEGORIES, item["id"]
        assert item["default_provider"] in get_args(Provider), item["id"]


@pytest.mark.parametrize("name", FILES)
def test_every_item_has_a_status_a_why_sources_and_an_unverified_note(name):
    for item in _draft(name)["items"]:
        assert item["cou_status"] in STATUSES, item["id"]
        assert item["why"].strip(), item["id"]
        assert isinstance(item["sources"], list) and item["sources"], item["id"]
        assert item["note"].startswith("UNVERIFIED:"), item["id"]


@pytest.mark.parametrize("name", FILES)
def test_escalation_only_on_usually_needed_and_triggers_only_on_conditional(name):
    for item in _draft(name)["items"]:
        usually = item["cou_status"] == "USUALLY_NEEDED"
        assert ("escalates_to_required_when" in item) == usually, item["id"]
        if usually:
            assert item["escalates_to_required_when"].strip(), item["id"]
        conditional = item["cou_status"] == "CONDITIONAL"
        assert ("trigger" in item) == conditional and ("trigger_text" in item) == conditional, item["id"]
        if conditional:
            assert item["trigger_text"].strip() and isinstance(item["trigger"], dict) and item["trigger"], item["id"]


def test_ids_are_unique_and_carry_their_files_prefix():
    ids = [item["id"] for item in _items()]
    assert len(ids) == len(set(ids))
    for name in FILES:
        assert all(item["id"].startswith(PREFIXES[name]) for item in _draft(name)["items"]), name
    # never a live template's id, nor the sub-domain drafts' REQ-DRAFT- prefix
    assert not [i for i in ids if i.startswith("REQ-")]
    live = {raw["id"] for template in load_templates() for raw in template["items"]}
    assert not live & set(ids)


def test_overrides_name_core_items_and_only_cou_files_override():
    core = _ids("core")
    for name in FILES:
        for item in _draft(name)["items"]:
            if "overrides" not in item:
                continue
            assert name in COU, item["id"]
            targets = item["overrides"] if isinstance(item["overrides"], list) else [item["overrides"]]
            assert targets and set(targets) <= core, item["id"]
    # each core item is overridden at most once per sub-context of a file
    for name in COU:
        seen: dict[tuple[str | None, str], str] = {}
        for item in _draft(name)["items"]:
            targets = item.get("overrides", [])
            for target in targets if isinstance(targets, list) else [targets]:
                key = (item.get("subcontext"), target)
                assert key not in seen, (item["id"], seen.get(key))
                seen[key] = item["id"]


@pytest.mark.parametrize("name", FILES)
def test_subcontexts_split_the_two_files_that_have_them(name):
    draft = _draft(name)
    subcontexts = draft.get("subcontexts")
    if subcontexts is None:
        assert not [item["id"] for item in draft["items"] if "subcontext" in item]
        return
    assert {item.get("subcontext") for item in draft["items"]} == set(subcontexts)
    for key, prefix in zip(subcontexts, PREFIXES[name], strict=True):
        assert all(item["id"].startswith(prefix) for item in draft["items"] if item["subcontext"] == key), key


# --- triggers and the property vocabulary ------------------------------------------------------------------------


def test_the_core_defines_statuses_grammar_and_properties():
    core = _draft("core")
    assert tuple(core["statuses"]) == STATUSES and all(core["statuses"].values())
    assert core["trigger_grammar"]["conditions"] and core["trigger_grammar"]["evaluation"]
    for name, definition in core["properties"].items():
        assert re.fullmatch(r"[a-z][a-z0-9_]*", name), name
        assert PROPERTY_KEYS <= set(definition) <= PROPERTY_KEYS | PROPERTY_MAY, name
        assert definition["about"] in {"compound", "product", "question", "population"}, name
        assert definition["how"] in {"code", "brief", "ask"}, name
        assert all(isinstance(definition[key], str) and definition[key].strip() for key in PROPERTY_KEYS), name
        assert definition.get("room_fields") or definition.get("brief_fields"), name
        for path in definition.get("brief_fields", ()):
            group, _, field = path.partition(".")
            definition_of(f"{group}[0].{field}" if group in ("products", "scenarios", "populations") else path)


def test_every_conditional_trigger_names_the_core_vocabulary_in_the_grammar():
    properties = _draft("core")["properties"]
    used: set[str] = set()
    for item in _items():
        if item["cou_status"] != "CONDITIONAL":
            continue
        for condition in _conditions(item["trigger"]):
            assert set(condition) <= CONDITION_KEYS and "property" in condition, (item["id"], condition)
            assert condition["property"] in properties, (item["id"], condition["property"])
            used.add(condition["property"])
            tests = set(condition) & {"equals", "in", "any_of", "above", "below", "threshold"}
            assert len(tests) == 1, (item["id"], condition)
            (test,) = tests
            if test in ("in", "any_of"):
                assert isinstance(condition[test], list) and condition[test], (item["id"], condition)
            if test in ("above", "below"):
                # a number only where a cited source states it, and the source is named
                assert isinstance(condition[test], int | float) and condition.get("threshold_source", "").strip()
                assert "direction" not in condition, item["id"]
            if test == "threshold":
                # no number in the sources: the SME sets it, and the item's words say so
                assert condition["threshold"] == "SME" and condition.get("direction") in ("above", "below"), item["id"]
                assert "threshold_source" not in condition, item["id"]
                assert "SME" in item["trigger_text"], item["id"]
            if test == "equals":
                assert isinstance(condition["equals"], bool | str), (item["id"], condition)
    # every property defined is used by a trigger, so the vocabulary carries nothing idle
    assert used == set(properties)


def test_a_bcs_trigger_uses_the_briefs_bcs_classes():
    bcs = set(definition_of("drug.bcs_class").options) - {"unknown"}
    for item in _items():
        if item["cou_status"] == "CONDITIONAL":
            for condition in _conditions(item["trigger"]):
                if condition["property"] == "bcs_class":
                    assert set(condition["in"]) <= bcs, item["id"]


# --- the Data room vocabulary ------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", FILES)
def test_room_fields_name_the_data_rooms_vocabulary(name):
    draft = _draft(name)
    entries = [(item["id"], entry) for item in draft["items"] for entry in item["room_fields"]]
    entries += [(prop, entry) for prop, d in draft.get("properties", {}).items() for entry in d.get("room_fields", ())]
    for owner, entry in entries:
        prefix, _, value = entry.partition(":")
        assert prefix in ROOM_PREFIX and value in ROOM_PREFIX[prefix], (owner, entry)
    for item in draft["items"]:
        if item["kind"] in ("system", "activity"):
            # never from a delivery: nothing in the room satisfies it, and that is not a gap
            assert item["room_fields"] == [] and item.get("room_gap") is False, item["id"]
        elif not item["room_fields"]:
            assert item.get("room_gap") is True, item["id"]
        else:
            assert item.get("room_gap", True) is True, item["id"]   # absent, or true for a partial cover


# --- sources -----------------------------------------------------------------------------------------------------


def test_every_source_is_one_the_reviews_cite():
    reviews = _reviews()
    for item in _items():
        for source in item["sources"]:
            match = SOURCE.match(source)
            assert match, (item["id"], source)
            if match["id"]:
                assert re.search(rf"PMID {match['id']}\b", reviews), (item["id"], source)
            elif match["doi_id"]:
                assert match["doi_id"] in reviews, (item["id"], source)
            elif match["consensus"]:
                # the review lists it as a Consensus record (its link, or the word), on the line that names the author
                surname = re.escape(match["surname"])
                assert re.search(rf"{surname}[^\n]*(?i:consensus)|(?i:consensus)[^\n]*{surname}", reviews), (item["id"], source)
            elif match["guidance"]:
                assert match["guidance"] in reviews, (item["id"], source)
            else:
                assert (ROOT / match["review"]).is_file(), (item["id"], source)


def test_a_pmid_is_cited_under_the_authors_name_the_reviews_give_it():
    reviews = _reviews()
    for item in _items():
        for source in item["sources"]:
            match = re.match(r"^(?P<surname>.+?) (?:[A-Z] )?\d{4}, PMID (?P<id>\d+)", source)
            if match:
                surname = match["surname"].split()[0]
                lines = [line for line in reviews.splitlines() if f"PMID {match['id']}" in line]
                assert any(surname in line for line in lines), (item["id"], source)


# --- the context-only list ---------------------------------------------------------------------------------------


def test_context_only_items_are_kept_as_context_and_trigger_requests_for_real_items():
    cou_ids = _ids(*COU)
    for item in _items("context_only"):
        assert CONTEXT_ONLY_KEYS <= set(item), item["id"]
        assert item["cou_status"] == "NOT_NEEDED" and item["kept_as"] == "context", item["id"]
        assert item["trigger_request_text"].strip(), item["id"]
        assert item["triggers_request_for"] and set(item["triggers_request_for"]) <= cou_ids, item["id"]
        assert item["context_for"] and set(item["context_for"]) <= set(COU), item["id"]
    for item in _items(*(name for name in FILES if name != "context_only")):
        assert not CONTEXT_ONLY_KEYS & set(item), item["id"]


def test_context_only_holds_what_the_pbbm_review_names():
    labels = " ".join(item["label"].lower() for item in _items("context_only"))
    for words in ("manufacturing process", "hardness", "full excipient list", "f2"):
        assert words in labels, words


# --- no PK-Sim names, paths, units, defaults or thresholds -------------------------------------------------------


@pytest.mark.parametrize("name", FILES)
def test_no_pksim_name_path_or_unit_anywhere(name):
    draft = _draft(name)
    keys = set(_keys(draft))
    assert not {"pksim", "unit", "pksim_status", "default", "default_value"} & keys
    assert not re.search(r"\bpksim\s*:", _text(name))
    # PK-Sim paths are "|"-separated; no string holds one
    assert not [leaf for leaf in _leaves(draft) if isinstance(leaf, str) and "|" in leaf]
    text = _text(name)
    found = [n for n in _harvested_names() if re.search(rf"(?<![A-Za-z0-9_]){re.escape(n)}(?![A-Za-z0-9_])", text)]
    assert not found


@pytest.mark.parametrize("name", FILES)
def test_no_number_but_a_sourced_trigger_cut_off_and_no_acceptance_wording(name):
    for item in _draft(name)["items"]:
        for key, value in item.items():
            if key == "trigger":
                continue
            for leaf in _leaves(value):
                # room_gap is the one flag; every other value is text
                assert isinstance(leaf, str) or (key == "room_gap" and isinstance(leaf, bool)), (item["id"], key, leaf)
                if key not in ("sources", "room_gap"):
                    assert "%" not in leaf and not re.search(r"\bfold\b|-fold\b", str(leaf), re.IGNORECASE), (item["id"], leaf)
                    assert not re.search(r"\bacceptance (?:criteri|limit|threshold)", str(leaf), re.IGNORECASE), (item["id"], leaf)
        # in a trigger, the only numbers are the sourced cut-offs (one per above / below condition)
        trigger = item.get("trigger", {})
        numbers = [leaf for leaf in _leaves(trigger) if isinstance(leaf, int | float) and not isinstance(leaf, bool)]
        cut_offs = [c for c in _conditions(trigger) if {"above", "below"} & set(c)] if trigger else []
        assert len(numbers) == len(cut_offs), item["id"]


# --- inert -------------------------------------------------------------------------------------------------------


def test_the_live_loader_does_not_see_these_drafts():
    templates = load_templates()
    assert len(templates) == 6
    assert not [t["id"] for t in templates if t["id"].startswith("cou-draft-")]
    assert not _ids() & {raw["id"] for t in templates for raw in t["items"]}


def test_derive_with_every_application_and_route_has_no_draft_item():
    brief: ProjectBrief = empty_brief("Exampleamide", by="u")
    sets = [("qoi.applications", list(APPLICATIONS))]
    sets += [(f"scenarios[{i}].route", route) for i, route in enumerate(ROUTES)]
    sets += [("scenarios[0].food_state", "fed"), ("drug.bcs_class", "II")]
    for path, value in sets:
        brief = agent_set(brief, path, value=value, unit=None, citations=CITE, status=FieldStatus.EXTRACTED,
                          confidence="A", by="a1")
    matrix = derive(brief)
    assert matrix.items
    ids = _ids()
    assert not [i.req_id for i in matrix.items if i.req_id in ids or i.req_id.partition("@")[0] in ids]
    assert not [t for t in matrix.templates if t.startswith("cou-draft-")]
    assert not [line.req_id for line in client_request(matrix) if line.req_id in ids]


def test_the_drafts_are_outside_every_locked_file():
    manifest = json.loads((ROOT / "docs" / "architecture" / "locked-files.json").read_text(encoding="utf-8"))
    drafts = {FOLDER / f"{name}.yaml" for name in FILES} | {FOLDER / "__init__.py"}
    assert all(path.is_file() for path in drafts)
    covered = {path for entry in manifest["patterns"] for path in ROOT.glob(entry["pattern"])}
    assert not covered & drafts
    assert not {ROOT / entry["path"] for entry in manifest["files"]} & drafts
