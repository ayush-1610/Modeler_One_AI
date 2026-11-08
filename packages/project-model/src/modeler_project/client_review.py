"""Client data confirmed inline (docs/plans/2026-11-03-inputs-and-client-data.md §3.3–3.5; the owner, 2026-11-03).

What the client's files gave is shown where it belongs, in groups: a clinical study (its datasets and their facts), a
product (its dissolution profiles), or the compound values read from one file. A group waits, "to confirm", until a
person confirms it. Only then does it load: its datasets and values are accepted and count in the inputs (until then
`sources.included` and `inputs.usable_dataset` leave them out). Literature and published-model values are not confirmed
here: they keep D-27 and are reviewed at the MAP signature.

A conflict or a question on a group blocks its confirmation until settled, so a group confirm never waves one through.
The person selects an option and confirms the selection; no reason is asked (the audit keeps who, when, the options
and the one selected). A settled conflict stays shown with its final value and its alternatives, and can be changed
until the group is confirmed. The rules for what counts as a contradiction are provisional
(`client_reconciliation.yaml`, UNVERIFIED for the SME). Nothing is averaged, guessed or resolved silently.

The record of selections and confirmations is the CLIENT_SUBMISSION artifact `review`, versioned and audited like any
other. A file sent again brings new proposed items, and only those return the group to "to confirm".

Across files (build I3, plan §3.4 stage 4–5): one study is often in several files under several names. Ids that differ
only in case, spaces or punctuation are one study; a file tagged at upload with a study name its sheet does not use asks
whether the two are the same (the person's answer links them, and the datasets take the study's name when the group is
confirmed). Two files giving one study's profile are compared point by point: within the rule's tolerance they are a
duplicate and load once, with both files named; beyond it they are a conflict on the card (one file's profile, the
other's, or two arms kept under their own ids). A dissolution profile two files give is compared the same way on its
product's card, and the file a person keeps is the one the register builds from.

Documents (build I4): the facts the reading agent quoted from a client's PDF or Word file (a protocol's dose, route,
food state, n) join the comparison of their study's facts, so a protocol and a PK sheet that disagree are a conflict
on the card; a fact the datasets lack is shown with its page and quote and fills them when the group is confirmed. A
study only a document describes is a group of its facts. A document that says two names are one study ("Protocol
EXZ-101 (Study 101)") asks whether they are, with the quote.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import UTC, datetime
from functools import lru_cache
from importlib import resources
from typing import Any, Literal

import yaml

from modeler_project.client_data import review_record, update_review
from modeler_project.datasets import ObservedDataset, Origin
from modeler_project.evidence import EvidenceItem, EvidenceState, Extraction
from modeler_project.workspace import Workspace

GroupKind = Literal["study", "product", "compound", "sheet"]
TAB: dict[str, str] = {"study": "studies", "product": "formulations", "compound": "compound", "sheet": "studies"}
# what a draft's answer sets, by what a document's fact for the study sets (build C2: offered, never applied unasked)
_OFFERED = {"n": "n", "dose": "dose_mg", "formulation": "formulation", "food_state": "food_state", "route": "route"}
FACT_LABEL = {"dose_mg": "Dose (mg)", "route": "Route", "food_state": "Food state", "formulation": "Formulation",
              "n": "Subjects (n)", "lloq": "LLOQ"}
DEMOGRAPHIC_LABEL = {"age_mean": ("Age (years), mean", "age_years"), "age_min": ("Age (years), youngest", "age_min"),
                     "age_max": ("Age (years), oldest", "age_max"), "weight_mean": ("Weight (kg), mean", "weight_kg"),
                     "height_mean": ("Height (cm), mean", "height_cm")}
HINT_LABEL = {"females": "Women (n)", "female_percent": "Women (%)", "ethnicity": "Ethnicity, as written"}
ALIASES = {"link": "aliases", "plink": "product_aliases", "blink": "batch_aliases"}   # by link issue: the record's alias list
FORMULATION_LABEL = {"ir_tablet": "Tablet (immediate release)", "ir_capsule": "Capsule (immediate release)",
                     "solution": "Solution", "suspension": "Suspension", "mr": "Modified release", "other": "Other"}
CONFIRMED_REASON = "confirmed on Inputs with its group"


class ReviewError(ValueError):
    """A selection or a confirmation the rules refuse (an unknown option, a group with something still open)."""


@lru_cache
def rule() -> dict[str, Any]:
    return yaml.safe_load(resources.files("modeler_project").joinpath("client_reconciliation.yaml").read_text(encoding="utf-8"))


def _normal(field: str, value: Any) -> Any:
    if value is None:
        return None
    if field in rule()["categorical"]["fields"]:
        text = " ".join(str(value).strip().lower().split())
        return rule()["categorical"]["synonyms"].get(text, text)
    if isinstance(value, int | float):
        return round(float(value), 9)
    return value


def _client_evidence(item: EvidenceItem) -> bool:
    """Read from a client file (a release model computed from a profile is the product's, not a value to confirm)."""
    return item.provider == "CLIENT" and item.extraction not in (Extraction.MANUAL, Extraction.COMPUTED)


def _client_dataset(dataset: ObservedDataset) -> bool:
    return dataset.origin is Origin.CLIENT and dataset.extraction != "MANUAL"


# --- the record ---------------------------------------------------------------------------------------------------


def record(ws: Workspace) -> dict[str, Any]:
    return review_record(ws)


# --- the groups ---------------------------------------------------------------------------------------------------


def _source(source: Any, quote: str = "") -> dict[str, Any]:
    return {"doc_sha256": source.doc_sha256, "page": source.page, "locator": source.locator, "title": source.title,
            "quote": quote[:600]}


def _shown(value: Any, unit: str | None = None) -> str:
    text = f"{value:g}" if isinstance(value, float) else str(value)
    return f"{text} {unit}".strip() if unit else text


def _key(study_id: Any) -> str:
    """A study id as code compares it: case, spaces and punctuation do not make another study."""
    return re.sub(r"[^A-Z0-9]", "", str(study_id).upper())


def _tagged_studies(ws: Workspace) -> dict[str, str]:
    """The study each clinical file was tagged with at upload, by the file's hash (plan §3.1)."""
    from modeler_project.documents import DocumentLibrary

    library = DocumentLibrary(ws)
    if not library.has_record:
        return {}
    return {sha: e.tag.study for sha, e in library.entries().items() if e.tag and e.tag.kind == "clinical" and e.tag.study}


def _canonical(raw_ids: list[str], aliases: dict[str, str]) -> dict[str, str]:
    """Each study id the files use, mapped to the one name its study goes by: a name a person linked it to, else the
    first spelling of the same id."""
    first: dict[str, str] = {}
    for target in sorted(set(aliases.values())):
        first.setdefault(_key(target), target)
    out = {}
    for raw in sorted(raw_ids):
        target = aliases.get(raw, raw)
        out[raw] = first.setdefault(_key(target), target)
    return out


def _file(d: ObservedDataset) -> str:
    return d.source.doc_sha256 or d.source.title or d.id


def _profile_difference(a: ObservedDataset, b: ObservedDataset) -> float | None:
    """The largest relative difference between two profiles at the times both give, series by series (by name, or the
    one series each has); None when they cannot be compared (other units, times or subjects)."""
    if (a.unit or "").lower() != (b.unit or "").lower() or a.time_unit != b.time_unit:
        return None
    named_a, named_b = {s.name: s for s in a.series}, {s.name: s for s in b.series}
    pairs = [(named_a[n], named_b[n]) for n in named_a if n in named_b]
    if not pairs and len(a.series) == 1 and len(b.series) == 1:
        pairs = [(a.series[0], b.series[0])]
    differences = []
    for x, y in pairs:
        at = dict(zip(y.times, y.values, strict=True))
        for time, value in zip(x.times, x.values, strict=True):
            other = at.get(time)
            if value is None or other is None or max(abs(value), abs(other)) == 0:
                continue
            differences.append(abs(value - other) / max(abs(value), abs(other)))
    return max(differences) if differences else None


def _doc_source(fact: dict[str, Any]) -> dict[str, Any]:
    return {"doc_sha256": fact["doc_sha256"], "page": fact["page"], "locator": fact.get("locator") or f"p. {fact['page']}",
            "title": fact["file"], "quote": str(fact.get("quote", ""))[:600]}


def _lloq_in(value: float, unit: str, target: str) -> float | None:
    """A document's LLOQ in a dataset's unit, when both are mass or both molar concentrations (else None: not compared)."""
    from pbpk_domain.units import UnitError, is_molar, umol_per_l_per

    try:
        if is_molar(unit) != is_molar(target):
            return None
        return value * umol_per_l_per(unit, 1.0) / umol_per_l_per(target, 1.0)
    except UnitError:
        return None


def _givers(field: str, members: list[ObservedDataset], duplicate_of: dict[str, str],
            facts: list[dict[str, Any]]) -> list[tuple[Any, dict[str, Any], list[str], str]]:
    """Who gives a study fact, as (value, source, datasets, as shown): each document fact first (build I4: its quote
    states the value), then each dataset (a duplicate file's copy last). A document's LLOQ is compared in the datasets'
    unit when they share one."""
    out: list[tuple[Any, dict[str, Any], list[str], str]] = []
    units = {d.unit for d in members}
    for f in facts:
        value = f["sets"].get(field)
        if value is None:
            continue
        shown = _shown(value)
        if field == "lloq":
            if len(units) > 1:
                continue
            if units:
                value = _lloq_in(float(value), f["sets"].get("lloq_unit", ""), next(iter(units)))
                if value is None:
                    continue
                value = round(value, 9)
            shown = f"{_shown(value)} {next(iter(units)) if units else f['sets'].get('lloq_unit', '')}".strip()
        out.append((value, _doc_source(f), [], shown))
    ordered = [d for d in members if d.id not in duplicate_of] + [d for d in members if d.id in duplicate_of]
    out += [(d.study[field], _source(d.source, d.quote), [d.id],
             f"{_shown(d.study[field])} {d.unit}" if field == "lloq" else _shown(d.study[field]))
            for d in ordered if d.study.get(field) is not None]
    return out


def _demographics(gid: str, members: list[ObservedDataset], study_facts: list[dict[str, Any]], facts: list[dict[str, Any]],
                  selections: dict[str, Any]) -> list[dict[str, Any]]:
    """A document's demographics of the study's subjects (D-29): its numbers shown as facts (two documents that differ
    are a conflict), and, for the study's datasets with no individual yet, the person's choice of its PK-Sim population
    and sex (with what the document says), and its mean age when no document states it. Confirming sets the individual
    as entered (`confirm`)."""
    from modeler_project.datasets import HUMAN_POPULATIONS

    issues = []
    lacking = [d.id for d in members if not d.study.get("demographics") and d.demographics_choice != "healthy_adult_default"]
    hints: dict[str, tuple[Any, dict[str, Any]]] = {}
    for field in (*DEMOGRAPHIC_LABEL, *HINT_LABEL):
        given = [(f["sets"][field], _doc_source(f)) for f in study_facts if field in f["sets"]]
        distinct: dict[Any, tuple[Any, dict[str, Any]]] = {}
        for value, source in given:
            distinct.setdefault(str(value).strip().lower() if field == "ethnicity" else round(float(value), 9), (value, source))
        if not distinct:
            continue
        label = DEMOGRAPHIC_LABEL[field][0] if field in DEMOGRAPHIC_LABEL else HINT_LABEL[field]
        if len(distinct) > 1 and field in DEMOGRAPHIC_LABEL:
            issues.append(_issue(gid, f"demographics:{field}", "conflict",
                                 f"{label}: the client's files give {len(distinct)} values",
                                 [{"id": f"v{i}", "label": _shown(v), "value": v, "source": src, "datasets": lacking}
                                  for i, (v, src) in enumerate(distinct.values())], selections))
            continue
        value, source = next(iter(distinct.values()))
        hints[field] = (value, source)
        facts.append({"field": f"demographics.{field}", "label": label, "value": _shown(value), "source": source,
                      "stored": value, "fills": lacking if field in DEMOGRAPHIC_LABEL else []})
    if not lacking or not any(f in hints or f"{gid}|demographics:{f}" in (i["id"] for i in issues) for f in DEMOGRAPHIC_LABEL):
        return issues
    said = (f": {hints['ethnicity'][1]['title']} says “{hints['ethnicity'][0]}”" if "ethnicity" in hints else
            ": the client's files do not say")
    issues.append(_issue(gid, "demographics:population", "question",
                         f"The study's individual: which PK-Sim population database{said}",
                         [{"id": p, "label": p.replace("_", " "), "value": p, "source": None, "datasets": lacking}
                          for p in HUMAN_POPULATIONS], selections))
    women = (f"{hints['females'][0]} women" if "females" in hints else
             f"{hints['female_percent'][0]:g} % women" if "female_percent" in hints else "")
    issues.append(_issue(gid, "demographics:sex", "question",
                         "The study's individual: male or female" + (f" ({women}, as the client's files say)" if women else ""),
                         [{"id": "MALE", "label": "Male", "value": "MALE", "source": None, "datasets": lacking},
                          {"id": "FEMALE", "label": "Female", "value": "FEMALE", "source": None, "datasets": lacking}],
                         selections))
    if "age_mean" not in hints and f"{gid}|demographics:age_mean" not in (i["id"] for i in issues):
        issues.append(_issue(gid, "demographics:age_years", "question",
                             "The study's individual: the subjects' mean age (years), which the client's files do not state",
                             [], selections, answer=True))
    return issues


def _study_groups(ws: Workspace, selections: dict[str, Any]) -> list[dict[str, Any]]:
    from modeler_project.client_data import document_facts, document_links
    from modeler_project.dataset_register import datasets

    content = record(ws)
    aliases = content.get("aliases", {})
    tagged = _tagged_studies(ws)
    tolerance = float(rule()["relative_tolerance"])
    from modeler_project.sheet_intake import drafts

    client = [d for d in datasets(ws) if _client_dataset(d) and d.state is not EvidenceState.REJECTED]
    doc_facts = document_facts(ws)
    waiting = [d for d in drafts(ws) if d["kind"] == "concentration_time" and d["study_id"]]
    # what a waiting sheet lacks, offered from the project's documents, Start and the data plan (build L)
    from modeler_project.study_offers import context as offer_context

    offer_ctx = offer_context(ws) if waiting else None
    canon = _canonical([*(str(d.study.get("study_id", d.id)) for d in client), *(str(f["study_id"]) for f in doc_facts),
                        *(d["study_id"] for d in waiting)], aliases)
    by_study: dict[str, list[ObservedDataset]] = defaultdict(list)
    for d in client:
        by_study[canon[str(d.study.get("study_id", d.id))]].append(d)
    facts_by_study: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for f in doc_facts:
        facts_by_study[canon[str(f["study_id"])]].append(f)
    drafts_by_study: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for d in waiting:
        drafts_by_study[canon[d["study_id"]]].append(d)
    # a document saying two names are one study (build I4): asked on the group whose data use the name, linking it to
    # the other name; once a person answered, the alias stands
    data_names = {str(d.study.get("study_id")) for d in client}
    linked_by_doc: dict[str, dict[str, Any]] = {}
    for link in document_links(ws):
        a, b = str(link["names"][0]), str(link["names"][1])
        raw, named = (b, a) if b in data_names and a not in data_names else (a, b)
        linked_by_doc.setdefault(raw, {**link, "named": named})
    groups = []
    for study_id in sorted(set(by_study) | set(facts_by_study) | set(drafts_by_study)):
        members, study_facts = by_study.get(study_id, []), facts_by_study.get(study_id, [])
        gid = f"study:{study_id}"
        members = sorted(members, key=lambda d: (d.source.title or "", d.id))
        raw_names = {str(d.study.get("study_id")) for d in members} | {str(f["study_id"]) for f in study_facts}
        notes: list[str] = []
        names = sorted(raw_names - {study_id})
        if names:
            notes.append(f"Also called {', '.join(names)} in the client's files: one study, {study_id}")
        if not members and not drafts_by_study.get(study_id):
            notes.append("No concentration data from the client for this study yet: its facts are read from "
                         f"{', '.join(sorted({f['file'] for f in study_facts}))}")
        duplicate_of: dict[str, str] = {}
        issues: list[dict[str, Any]] = []
        profiles = [d for d in members if d.kind == "profile"]
        for i, d in enumerate(profiles):
            # only another file's profile of the same analyte and matrix is a rival: one file's datasets of a study are
            # different things (individual and mean, parent and metabolite)
            rivals = [e for e in profiles[:i] if e.id not in duplicate_of and (e.analyte, e.matrix) == (d.analyte, d.matrix)
                      and _file(e) != _file(d)]
            if not rivals:
                continue
            same = next((e for e in rivals if (x := _profile_difference(e, d)) is not None and x <= tolerance), None)
            anchor = same or rivals[0]
            difference = _profile_difference(anchor, d)
            file_a, file_b = anchor.source.title or anchor.id, d.source.title or d.id
            if same is not None:
                duplicate_of[d.id] = anchor.id
                notes.append(f"{file_b} gives the same profile as {file_a} (within {tolerance:.0%}): it loads once, "
                             "with both files named")
                continue
            what = (f"The profiles in {file_a} and {file_b} differ by up to {difference:.0%} (more than {tolerance:.0%})"
                    if difference is not None else f"The profiles in {file_a} and {file_b} cannot be compared (other units, "
                    "times or subjects)")
            issues.append(_issue(gid, f"profile:{d.id}", "conflict", what, [
                {"id": "first", "label": f"{file_a}'s profile", "value": anchor.id, "source": _source(anchor.source, anchor.quote),
                 "datasets": [anchor.id]},
                {"id": "second", "label": f"{file_b}'s profile", "value": d.id, "source": _source(d.source, d.quote),
                 "datasets": [d.id]},
                {"id": "both", "label": "Different arms or cohorts: keep both, each under its own id", "value": None,
                 "source": None, "datasets": []}], selections))
        items = [{"id": d.id, "kind": "dataset", "label": f"{d.kind} · {len(d.series) or len(d.reported)} "
                  f"{'series' if d.kind == 'profile' else 'PK parameters'} · {d.analyte}, {d.matrix}",
                  "value": f"{d.unit}, time in {d.time_unit}", "state": d.state.value,
                  "note": f"the same as {next(m.source.title for m in members if m.id == duplicate_of[d.id])}: loads once"
                  if d.id in duplicate_of else "", "duplicate_of": duplicate_of.get(d.id),
                  "source": _source(d.source, d.quote)} for d in members]
        for raw in sorted(raw_names):
            named = next((tagged[d.source.doc_sha256] for d in members if str(d.study.get("study_id")) == raw
                          and d.source.doc_sha256 in tagged), None)
            said = linked_by_doc.get(raw) if not named else None
            named = named or (said["named"] if said else None)
            if not named or _key(named) == _key(raw):
                continue
            if said:
                text = (f"{said['file']} (p. {said['page']}) says “{said['quote'][:200]}”: is {raw} the same study as "
                        f"{named}?")
                source = _doc_source(said)
            else:
                file = next(d.source.title for d in members if str(d.study.get("study_id")) == raw)
                text = f"{file} was tagged at upload as study {named}; its sheet calls the study {raw}. Are they the same study?"
                source = None
            issues.append(_issue("link", raw, "link", text,
                                 [{"id": "same", "label": f"Yes: {raw} is {named}", "value": named, "source": source,
                                   "datasets": []},
                                  {"id": "different", "label": f"No: {raw} is another study", "value": None,
                                   "source": None, "datasets": []}], selections))
        facts = []
        for field, label in FACT_LABEL.items():
            given = _givers(field, members, duplicate_of, study_facts)
            distinct: dict[Any, list[tuple[Any, dict[str, Any], list[str], str]]] = defaultdict(list)
            for giver in given:
                distinct[_normal(field, giver[0])].append(giver)
            if len(distinct) > 1:
                explainable = field in rule()["explainable"]["fields"]
                options = [{"id": f"v{i}", "label": gs[0][3], "value": gs[0][0], "source": gs[0][1],
                            "datasets": [d for g in gs for d in g[2]]}
                           for i, (_v, gs) in enumerate(distinct.items())]
                options.append({"id": "explained" if explainable else "different",
                                "label": "Explained: dosed and PK-evaluable counts differ" if explainable
                                else "They are different things: each file keeps its own value",
                                "value": None, "source": None, "datasets": []})
                issues.append(_issue(gid, field, "difference" if explainable else "conflict",
                                     f"{label}: the client's files give {len(distinct)} values", options, selections))
            elif given:
                value, source, _ds, shown = given[0]
                lacking = [d.id for d in members if d.study.get(field) is None]   # a document's fact fills them on confirm
                facts.append({"field": field, "label": label, "value": shown, "source": source, "stored": value,
                              "fills": lacking if any(not g[2] for g in given) else []})
        issues += _demographics(gid, members, study_facts, facts, selections)
        given_by_doc = {k for f in study_facts for k in f["sets"]}
        for d in members:
            if d.study.get("route") == "oral" and not d.study.get("food_state") and "food_state" not in given_by_doc:
                issues.append(_issue(gid, f"food_state:{d.id}", "question", "Oral study with no food state: fasted or fed?",
                                     [{"id": "fasted", "label": "Fasted", "value": "fasted", "source": None, "datasets": [d.id]},
                                      {"id": "fed", "label": "Fed", "value": "fed", "source": None, "datasets": [d.id]}],
                                     selections))
            if d.study.get("route") == "oral" and not d.study.get("formulation") and "formulation" not in given_by_doc:
                issues.append(_issue(gid, f"formulation:{d.id}", "question", "Oral study with no dosage form: which one?",
                                     [{"id": v, "label": FORMULATION_LABEL[v], "value": v, "source": None, "datasets": [d.id]}
                                      for v in FORMULATION_LABEL], selections))
            if (d.kind == "profile" and d.study.get("lloq") is None and "lloq" not in given_by_doc
                    and any(v is None for s in d.series for v in s.values)):
                issues.append(_issue(gid, f"lloq:{d.id}", "question",
                                     f"Values below the LLOQ, and no LLOQ stated: give it in {d.unit}",
                                     [], selections, answer=True))
        items += [_draft_item(d, study_facts, offer_ctx) for d in drafts_by_study.get(study_id, [])]
        groups.append(_group(gid, "study", f"Study {study_id}", items, facts, issues, ws, notes=notes))
    return groups


def _draft_item(d: dict[str, Any], study_facts: list[dict[str, Any]], offer_ctx: Any = None) -> dict[str, Any]:
    """A sheet read by code and not saved yet (build C2), on its study's card: what it needs, and for each need the
    values the project holds, each with where it comes from: a document's fact for the same study (the reading agent's
    or the template's), then what code finds in the documents, on Start and in the data plan (build L, the owner,
    2026-11-08). One is pre-filled when it can be told apart (`study_offers.preselect`); the person reads the sheet."""
    from modeler_project.sheet_intake import NEED_LABEL
    from modeler_project.study_offers import offers as project_offers
    from modeler_project.study_offers import preselect

    found = project_offers(offer_ctx, d["study_id"], d["needs"], d.get("points")) if offer_ctx is not None else {}
    offers: dict[str, list[dict[str, Any]]] = {}
    for need in d["needs"]:
        field = _OFFERED.get(need)
        given = [(f["sets"][field], f) for f in study_facts if field and f["sets"].get(field) is not None]
        listed = [{"value": str(v), "label": f"{_shown(v)} · {f['file']}, p. {f['page']}", "source": _doc_source(f),
                   "document": True} for v, f in given]
        listed += [o for o in found.get(need, []) if o["value"] not in {x["value"] for x in listed}]
        if listed:
            offers[need] = listed
    prefill = {need: value for need, listed in offers.items() if (value := preselect(listed)) is not None}
    points = d.get("points") or {}
    series = points.get("series") or []
    shown = f"{len(series)} series · {len({t for s in series for t in s['times']})} times" if series else "read by code"
    return {"id": f"draft|{d['sid']}|{d['sheet']}", "kind": "draft", "label": f"{d['sheet']} · {d['file']}",
            "value": shown, "state": "DRAFT",
            "note": f"read by {'code' if d['by'] == 'code' else 'the reading agent'}; loads once its facts are given and "
                    "the study is confirmed",
            "source": {"doc_sha256": d["sha256"], "page": None, "locator": d["sheet"], "title": d["file"], "quote": ""},
            "draft": {"sid": d["sid"], "sheet": d["sheet"], "kind": d["kind"], "needs": d["needs"],
                      "labels": {n: NEED_LABEL.get(n, n) for n in d["needs"]}, "answers": d["answers"],
                      "problems": d["problems"], "notes": d["notes"], "offers": offers, "prefill": prefill,
                      "points": d.get("points"),
                      # who read it, and what the reading left out and changed (build F: "nothing silently")
                      "by": d["by"], "cleaning": d.get("cleaning", [])}}


def _sheet_groups(ws: Workspace) -> list[dict[str, Any]]:
    """Sheets read by code that no study or product holds yet (a dissolution sheet, a sheet naming no study): one card
    each, on the tab of its data, asking what it needs."""
    from modeler_project.sheet_intake import drafts

    out = []
    for d in drafts(ws):
        if d["kind"] == "concentration_time" and d["study_id"]:
            continue
        group = _group(f"sheet:{d['sid']}|{d['sheet']}", "sheet", f"{d['sheet']} · {d['file']}", [_draft_item(d, [])],
                       [], [], ws, notes=d["notes"])
        group["tab"] = "formulations" if d["kind"] == "dissolution" else "studies"
        out.append(group)
    return out


def _compound_groups(ws: Workspace, selections: dict[str, Any]) -> list[dict[str, Any]]:
    from modeler_project.evidence_register import items as evidence_items
    from modeler_project.sources import included
    from modeler_project.sources import rule as selection_rule

    everything = evidence_items(ws)
    others = [e for e in everything if not _client_evidence(e) and included(e)]
    by_file: dict[str, list[EvidenceItem]] = defaultdict(list)
    for e in everything:
        if _client_evidence(e) and e.state is not EvidenceState.REJECTED:
            by_file[e.source.doc_sha256 or e.source.title or "client"].append(e)
    fold = float(rule()["conflict_fold"])
    groups = []
    for key, members in sorted(by_file.items()):
        gid = f"compound:{key[:12]}"
        title = members[0].source.title or "the client's file"
        items, issues = [], []
        for e in members:
            label = e.target
            note = ""
            peers = [o for o in others if o.target == e.target and isinstance(o.value_pksim, int | float) and o.value_pksim]
            if isinstance(e.value_pksim, int | float) and e.value_pksim and peers:
                far = [o for o in peers if max(o.value_pksim, e.value_pksim) / min(o.value_pksim, e.value_pksim) > fold]
                near = [o for o in peers if abs(o.value_pksim - e.value_pksim) <= selection_rule().agreement_relative * abs(o.value_pksim)]
                if far:
                    ratio = max(max(o.value_pksim, e.value_pksim) / min(o.value_pksim, e.value_pksim) for o in far)
                    options = [{"id": "client", "label": f"The client's value, {_shown(e.value, e.unit)}", "value": e.id,
                                "source": _source(e.source, e.quote), "datasets": []}]
                    options += [{"id": o.id, "label": f"{o.source.title or o.source_type.value.lower()}, {_shown(o.value, o.unit)}",
                                 "value": o.id, "source": _source(o.source, o.quote), "datasets": []} for o in far]
                    issues.append(_issue(gid, f"value:{e.id}", "conflict",
                                         f"{label}: the client's value and the literature are {ratio:.1f}-fold apart "
                                         "(compared in the PK-Sim unit)", options, selections))
                elif near:
                    note = f"agrees within {selection_rule().agreement_relative:.0%} with {len(near)} other source" + ("s" if len(near) > 1 else "")
            if isinstance(e.value, int | float) and e.value_pksim is None:
                issues.append(_issue(gid, f"convert:{e.id}", "question",
                                     f"{label}: {_shown(e.value, e.unit)} has no automatic conversion: give it in the PK-Sim unit",
                                     [], selections, answer=True))
            items.append({"id": e.id, "kind": "value", "label": label, "target": e.target,
                          "value": _shown(e.value, e.unit), "state": e.state.value, "note": note,
                          "conditions": dict(e.conditions), "source": _source(e.source, e.quote)})
        groups.append(_group(gid, "compound", f"Client values · {title}", items, [], issues, ws))
    return groups


def _dissolution_difference(a: Any, b: Any) -> float | None:
    """The largest relative difference between two dissolution profiles' means at the times both give, where at least
    10 % has dissolved (below that a relative difference says nothing); None when no time is shared."""
    at = dict(zip(b.times_min, b.mean, strict=True))
    differences = [abs(m - at[t]) / max(m, at[t]) for t, m in zip(a.times_min, a.mean, strict=True)
                   if t in at and max(m, at[t]) >= 10]
    return max(differences) if differences else None


def _points(profile: Any) -> str:
    return ", ".join(f"{m:.0f} % at {t:g} min" for t, m in list(zip(profile.times_min, profile.mean, strict=True))[1:4])


def _link_targets(links: list[dict[str, Any]], used: set[str]) -> dict[str, dict[str, Any]]:
    """A document's pairs of names, each asked on the name the data use, linking it to the other name."""
    out: dict[str, dict[str, Any]] = {}
    for link in links:
        a, b = str(link["names"][0]), str(link["names"][1])
        raw, named = (b, a) if b in used and a not in used else (a, b)
        out.setdefault(raw, {**link, "named": named})
    return out


def _link_issue(scope: str, raw: str, said: dict[str, Any], what: str,
                shown: str | None = None) -> tuple[str, str, str, str, list[dict[str, Any]]]:
    """A "same product?" or "same batch?" question; `raw` is the key its answer is kept under, `shown` the name."""
    name = shown or raw
    text = f"{said['file']} (p. {said['page']}) says “{said['quote'][:200]}”: is {name} the same {what} as {said['named']}?"
    return scope, raw, "link", text, [
        {"id": "same", "label": f"Yes: {name} is {said['named']}", "value": said["named"], "source": _doc_source(said),
         "datasets": []},
        {"id": "different", "label": f"No: {name} is another {what}", "value": None, "source": None, "datasets": []}]


def _product_groups(ws: Workspace, selections: dict[str, Any]) -> list[dict[str, Any]]:
    from modeler_project.client_data import document_compositions, document_links
    from modeler_project.dissolution_register import batch_alias_key, by_file, profile_id, profiles

    tolerance = float(rule()["relative_tolerance"])
    content = record(ws)
    files_of = {profile_id(key): files for key, files in by_file(ws).items()}
    given = {pid: files for pid, files in files_of.items() if len(files) > 1}
    found, compositions = profiles(ws), document_compositions(ws)
    raw_of = {p["id"]: str(p["key"].get("product") or "product") for p in found}
    spellings = {pid: {str(prof.key.product or "product") for prof, _s, _n in files} for pid, files in files_of.items()}
    canon = _canonical([*raw_of.values(), *(n for names in spellings.values() for n in names),
                        *(str(c["product"]) for c in compositions)], content.get("product_aliases", {}))
    by_product: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in found:
        by_product[canon[raw_of[p["id"]]]].append(p)
    composed: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in compositions:
        composed[canon[str(c["product"])]].append(c)
    product_links = _link_targets(document_links(ws, "product"), {n for names in spellings.values() for n in names})
    batch_links = _link_targets(document_links(ws, "batch"), {str(prof.key.batch or "") for files in files_of.values()
                                                              for prof, _s, _n in files})
    groups = []
    for product in sorted(set(by_product) | set(composed)):
        members, comps = by_product.get(product, []), composed.get(product, [])
        gid = f"product:{product}"
        notes: list[str] = []
        issues: list[dict[str, Any]] = []
        items = []
        names = sorted({raw_of[p["id"]] for p in members} | {n for p in members for n in spellings.get(p["id"], ())}
                       | {str(c["product"]) for c in comps})
        if len(names) > 1 or names[0] != product:
            notes.append(f"Also called {', '.join(n for n in names if n != product)} in the client's files: one product, {product}")
        for raw in names:
            if raw in product_links and _key(product_links[raw]["named"]) != _key(raw):
                issues.append(_issue(*_link_issue("plink", raw, product_links[raw], "product"), selections))
        batches = {str(p["key"].get("batch") or "") for p in members} | {
            str(prof.key.batch or "") for p in members for prof, _s, _n in files_of.get(p["id"], [])}
        for raw in sorted(batches):
            if raw in batch_links and _key(batch_links[raw]["named"]) != _key(raw):   # linked within this product only
                issues.append(_issue(*_link_issue("blink", batch_alias_key(_key(product), raw), batch_links[raw], "batch",
                                                  shown=raw), selections))
        for p in members:
            note = "; ".join(p.get("flags", []))
            files = given.get(p["id"], [])
            if files:
                first = files[0][0]
                worst = max((d for later, _s, _n in files[1:] if (d := _dissolution_difference(first, later)) is not None),
                            default=None)
                names_given = [name for _p, _s, name in files]
                if worst is not None and worst <= tolerance:
                    notes.append(f"{p['label']}: given by {', '.join(names_given)} (within {tolerance:.0%}): kept once")
                else:
                    what = (f"{p['label']}: {', '.join(names_given)} differ by up to {worst:.0%} (more than {tolerance:.0%})"
                            if worst is not None else f"{p['label']}: {', '.join(names_given)} share no time to compare")
                    issues.append(_issue(gid, f"profile:{p['id']}", "conflict", what, [
                        {"id": sid, "label": f"{name}: {_points(prof)}", "value": sid, "source": None,
                         "datasets": []} for prof, sid, name in files], selections))
            items.append({"id": p["id"], "kind": "profile", "label": p["label"],
                          "value": f"{len(p['times_min'])} times to {max(p['times_min'], default=0):g} min · n = {p['n']}",
                          "state": "PROPOSED", "note": note,
                          "source": {"doc_sha256": None, "page": None, "locator": ", ".join(p.get("cells", [])[:3]),
                                     "title": ", ".join(p.get("files", [])), "quote": ""}})
        facts = [{"field": f"composition.{line['name']}", "label": line["name"],
                  "value": f"{line['amount']:g} {line['unit']}" + (f" ({line['function']})" if line.get("function") else ""),
                  "source": {"doc_sha256": c["doc_sha256"], "page": c["page"], "locator": f"p. {c['page']}", "title": c["file"],
                             "quote": line["quote"]}, "stored": None, "fills": []}
                 for c in comps for line in c["components"]]
        if comps:
            notes.append(f"Composition as {', '.join(sorted({c['file'] for c in comps}))} reports it: shown for the "
                         "reviewer and the report, not used by the model")
        groups.append(_group(gid, "product", product, items, facts, issues, ws,
                             versions={p["id"]: p["version"] for p in members}, notes=notes))
    return groups


def _issue(gid: str, key: str, kind: str, text: str, options: list[dict[str, Any]], selections: dict[str, Any], *,
           answer: bool = False) -> dict[str, Any]:
    iid = f"{gid}|{key}"
    chosen = selections.get(iid)
    return {"id": iid, "kind": kind, "text": text, "options": options, "answer": answer,
            "selected": chosen.get("option") if chosen else None, "answered": chosen.get("answer") if chosen else None,
            "selected_by": chosen.get("by") if chosen else None, "selected_at": chosen.get("at") if chosen else None}


def _fact_list(facts: list[dict[str, Any]]) -> list[list[str]]:
    return [[f["field"], f["value"]] for f in facts]


def _group(gid: str, kind: GroupKind, title: str, items: list[dict[str, Any]], facts: list[dict[str, Any]],
           issues: list[dict[str, Any]], ws: Workspace, versions: dict[str, int] | None = None,
           notes: list[str] | None = None) -> dict[str, Any]:
    confirmation = record(ws)["confirmations"].get(gid)
    if kind == "product":
        confirmed = confirmation is not None and all(confirmation.get("versions", {}).get(i["id"]) == v
                                                     for i, v in ((i, (versions or {})[i["id"]]) for i in items)) \
            and confirmation.get("facts", []) == _fact_list(facts)
        for i in items:
            i["state"] = "ACCEPTED" if confirmed else "PROPOSED"
    elif not items:     # a study only a document's facts describe (I4): confirmed while they are the facts confirmed
        confirmed = confirmation is not None and confirmation.get("facts") == _fact_list(facts)
    else:               # a sheet still to finish (build C2) keeps its study to confirm
        confirmed = not any(i["state"] in (EvidenceState.PROPOSED.value, "DRAFT") for i in items)
    if confirmed and confirmation:   # as they were settled, in their order; anything new after them
        recorded = confirmation.get("issues", [])
        known = {i["id"] for i in recorded}
        issues = recorded + [i for i in issues if i["id"] not in known]
        notes = list(dict.fromkeys([*confirmation.get("notes", []), *(notes or [])]))
    open_issues = [i for i in issues if i["selected"] is None and i["answered"] is None]
    drafting = sum(1 for i in items if i["kind"] == "draft")
    return {"id": gid, "kind": kind, "tab": TAB[kind], "title": title, "items": items, "facts": facts, "issues": issues,
            "notes": notes or [], "state": "confirmed" if confirmed else "to_confirm", "open": len(open_issues) + drafting,
            "confirmed_by": confirmation.get("by") if confirmation and confirmed else None,
            "confirmed_at": confirmation.get("at") if confirmation and confirmed else None}


def groups(ws: Workspace) -> list[dict[str, Any]]:
    """Every group of client data, with its items, its facts, and its conflicts and questions (settled or open)."""
    selections = record(ws)["selections"]
    return (_study_groups(ws, selections) + _product_groups(ws, selections) + _sheet_groups(ws)
            + _compound_groups(ws, selections))


def to_confirm(ws: Workspace) -> list[dict[str, Any]]:
    return [g for g in groups(ws) if g["state"] == "to_confirm"]


def _find(ws: Workspace, gid: str) -> dict[str, Any]:
    group = next((g for g in groups(ws) if g["id"] == gid), None)
    if group is None:
        raise KeyError(f"no client data group {gid}")
    return group


# --- what a person does -------------------------------------------------------------------------------------------


def select(ws: Workspace, gid: str, issue_id: str, *, by: str, option: str | None = None,
           answer: float | None = None) -> dict[str, Any]:
    """Confirm the selection on one conflict or question: an option, or the answer a question asks for. Kept until the
    group is confirmed, and changeable until then."""
    group = _find(ws, gid)
    issue = next((i for i in group["issues"] if i["id"] == issue_id), None)
    if issue is None:
        raise KeyError(f"no issue {issue_id} on {gid}")
    if group["state"] == "confirmed":
        raise ReviewError(f"{group['title']} is confirmed already")
    if issue["answer"]:
        if answer is None or not answer > 0:
            raise ReviewError("give the value (a positive number)")
        chosen = {"answer": float(answer)}
    else:
        if option not in {o["id"] for o in issue["options"]}:
            raise ReviewError(f"choose one of the options: {', '.join(o['id'] for o in issue['options'])}")
        chosen = {"option": option}
    shown = chosen.get("option") or chosen.get("answer")
    linked = _linked(issue, chosen)

    def change(content: dict[str, Any]) -> tuple[dict[str, Any], str]:
        new = {**content, "selections": {**content["selections"], issue_id: {
            **chosen, "group": gid, "by": by, "at": datetime.now(UTC).isoformat()}}}
        if issue["kind"] == "link":   # a link regroups at once: the study's datasets join the study they are
            scope, raw = issue_id.split("|", 1)
            key = ALIASES[scope]
            aliases = {k: v for k, v in content.get(key, {}).items() if k != raw}
            new[key] = {**aliases, **({raw: linked} if linked else {})}
        return new, f"{issue['text']}: selected {shown}"

    update_review(ws, change, by=by)
    return _after_link(ws, gid, issue_id, linked, by=by)


def _after_link(ws: Workspace, gid: str, issue_id: str, linked: str | None, *, by: str) -> dict[str, Any]:
    """The group after a selection: a product or batch link rebuilds the dissolution register (the two names' profiles
    become one), and a link may move the group under the linked name."""
    scope = issue_id.split("|", 1)[0]
    if scope in ("plink", "blink"):
        from modeler_project.dissolution_register import rebuild

        rebuild(ws, by=by)
    found = {g["id"]: g for g in groups(ws)}
    target = f"{'study' if scope == 'link' else 'product'}:{linked}" if linked and scope != "blink" else gid
    return found.get(gid) or found.get(target) or _find(ws, gid)


def _linked(issue: dict[str, Any], chosen: dict[str, Any]) -> str | None:
    """The study a link question's answer names, when the answer is "the same study"."""
    if issue["kind"] != "link":
        return None
    option = next((o for o in issue["options"] if o["id"] == chosen.get("option")), None)
    return str(option["value"]) if option and option["value"] else None


def reopen(ws: Workspace, gid: str, issue_id: str, *, by: str) -> dict[str, Any]:
    """Change a settled conflict or question before the group is confirmed."""
    group = _find(ws, gid)
    if group["state"] == "confirmed":
        raise ReviewError(f"{group['title']} is confirmed already")
    def change(content: dict[str, Any]) -> tuple[dict[str, Any], str] | None:
        if issue_id not in content["selections"]:
            return None
        new = {**content, "selections": {k: v for k, v in content["selections"].items() if k != issue_id}}
        scope, _, raw = issue_id.partition("|")
        if scope in ALIASES:
            new[ALIASES[scope]] = {k: v for k, v in content.get(ALIASES[scope], {}).items() if k != raw}
        return new, f"{issue_id}: selection reopened"

    update_review(ws, change, by=by)
    if issue_id.split("|", 1)[0] in ("plink", "blink"):
        from modeler_project.dissolution_register import rebuild

        rebuild(ws, by=by)
    return next((g for g in groups(ws) if g["id"] == gid), None) or group


def edit_fact(ws: Workspace, gid: str, field: str, value: Any, *, by: str) -> dict[str, Any]:
    """An item-level edit before the group is confirmed: one fact of every dataset of the study (the audit keeps the
    facts before and after; no reason is asked)."""
    from modeler_project.dataset_register import set_study_facts

    group = _find(ws, gid)
    if group["kind"] != "study" or field not in FACT_LABEL:
        raise ReviewError(f"only a study's facts are edited here ({', '.join(FACT_LABEL)})")
    if group["state"] == "confirmed":
        raise ReviewError(f"{group['title']} is confirmed already")
    for item in group["items"]:
        set_study_facts(ws, item["id"], changes={field: value}, by=by)
    return _find(ws, gid)


def confirm(ws: Workspace, gid: str, *, by: str) -> dict[str, Any]:
    """Confirm a group: its selections are applied, then its datasets and values are accepted and load into the
    inputs, in one audited record. Refused while any conflict or question of the group is open."""
    from modeler_project.dataset_register import decide_dataset, rename_study, set_study_facts
    from modeler_project.evidence_register import choose, decide

    group = _find(ws, gid)
    if group["state"] == "confirmed":
        return group
    if group["open"]:
        raise ReviewError(f"{group['title']}: settle {group['open']} open item{'s' if group['open'] > 1 else ''} first")
    content = record(ws)
    accepted_value: dict[str, float] = {}
    rejected: set[str] = set()
    kept: set[str] = set()
    arms: list[str] = []
    profile_sources: dict[str, str] = {}
    demographics: dict[str, Any] = {}
    study_id = gid.split(":", 1)[1]
    for issue in group["issues"]:
        chosen = content["selections"][issue["id"]]
        key = issue["id"].split("|", 1)[1]
        if issue["kind"] == "link":
            continue                      # applied when it was selected: the datasets are in this group already
        if key.startswith("demographics:"):
            what = key.split(":", 1)[1]
            option = next((o for o in issue["options"] if o["id"] == chosen.get("option")), None)
            demographics[DEMOGRAPHIC_LABEL[what][1] if what in DEMOGRAPHIC_LABEL else what] = (
                chosen["answer"] if chosen.get("answer") is not None else option["value"] if option else None)
            continue
        if group["kind"] == "study" and key.startswith("profile:"):
            other = key.split(":", 1)[1]
            first = next(o["value"] for o in issue["options"] if o["id"] == "first")
            if chosen["option"] == "both":
                arms.append(other)
                continue
            dropped = other if chosen["option"] == "first" else first
            kept_id = first if dropped == other else other
            if dropped not in rejected:   # one file's profile may lose to two others
                decide_dataset(ws, dropped, state=EvidenceState.REJECTED, by=by,
                               reason=f"on Inputs, the profile of {kept_id} was selected over this one (they differ)")
                rejected.add(dropped)
            continue
        if group["kind"] == "product":
            profile_sources[key.split(":", 1)[1]] = chosen["option"]
            continue
        if group["kind"] == "study":
            field, _, only = key.partition(":")
            if chosen.get("answer") is not None:
                set_study_facts(ws, only, changes={field: chosen["answer"]}, by=by)
                continue
            option = next(o for o in issue["options"] if o["id"] == chosen["option"])
            if option["value"] is not None:
                for item in (group["items"] if not only else [{"id": only}]):
                    set_study_facts(ws, item["id"], changes={field: option["value"]}, by=by)
        elif group["kind"] == "compound":
            what, _, evidence_id = key.partition(":")
            if what == "convert":
                accepted_value[evidence_id] = float(chosen["answer"])
            elif chosen["option"] == "client":
                choose(ws, evidence_id, reason="the client's value selected on Inputs", by=by)
                kept.add(evidence_id)
            else:
                decide(ws, evidence_id, state=EvidenceState.REJECTED, reason=f"on Inputs, {chosen['option']} was selected over "
                       "the client's value", by=by)
                rejected.add(evidence_id)
    for item in group["items"]:
        if item["kind"] == "dataset" and item.get("duplicate_of") and item["id"] not in rejected:
            decide_dataset(ws, item["id"], state=EvidenceState.REJECTED, by=by,
                           reason=f"the same profile as {item['duplicate_of']} (within the tolerance of "
                                  "client_reconciliation.yaml): loaded once, both files named")
            rejected.add(item["id"])
    for n, other in enumerate(arms, start=2):
        rename_study(ws, other, f"{study_id}-{n}", by=by, reason="another arm or cohort of the study, said on Inputs")
    if group["kind"] == "study":   # a document's fact fills the datasets that lack it (I4), as the card showed
        for fact in group["facts"]:
            for dataset_id in fact.get("fills", []):
                if dataset_id not in rejected and not fact["field"].startswith("demographics."):
                    set_study_facts(ws, dataset_id, changes={fact["field"]: fact["stored"]}, by=by)
        _set_demographics(ws, group, demographics, rejected, by=by)
    if group["kind"] == "study":   # one study, one name: the one the person linked it to, or its first spelling
        from modeler_project.dataset_register import dataset as current

        for item in group["items"]:
            found = current(ws, item["id"])
            if item["id"] in rejected or item["id"] in arms or found is None or found.study.get("study_id") == study_id:
                continue
            rename_study(ws, item["id"], study_id, by=by,
                         reason=f"{found.study.get('study_id')} is study {study_id} (linked on Inputs)")
    if profile_sources:
        from modeler_project.dissolution_register import rebuild

        update_review(ws, lambda content: ({**content, "profile_sources": {**content.get("profile_sources", {}),
                                                                          **profile_sources}},
                                           f"{group['title']}: the file kept for {len(profile_sources)} profile(s)"), by=by)
        rebuild(ws, by=by)
    for item in group["items"]:
        if item["state"] != EvidenceState.PROPOSED.value or item["id"] in rejected | kept:
            continue
        if item["kind"] == "dataset":
            decide_dataset(ws, item["id"], state=EvidenceState.ACCEPTED, reason=CONFIRMED_REASON, by=by)
        elif item["kind"] == "value":
            value = accepted_value.get(item["id"])
            decide(ws, item["id"], state=EvidenceState.ACCEPTED, reason=CONFIRMED_REASON, by=by, value_pksim=value,
                   unit_pksim=None)
    entry = {"by": by, "at": datetime.now(UTC).isoformat(), "items": [i["id"] for i in group["items"]],
             "selections": {i["id"]: content["selections"].get(i["id"]) for i in group["issues"]},
             "issues": group["issues"], "notes": group["notes"],   # kept: each settled conflict stays shown
             "facts": _fact_list(group["facts"])}
    if group["kind"] == "product":
        from modeler_project.dissolution_register import profiles

        entry["versions"] = {p["id"]: p["version"] for p in profiles(ws) if p["id"] in entry["items"]}
    update_review(ws, lambda content: ({**content, "confirmations": {**content["confirmations"], gid: entry}},
                                       f"{group['title']} confirmed: {len(group['items'])} items load into the project"), by=by)
    # a group whose every value was set aside for another source has nothing left to show
    return next((g for g in groups(ws) if g["id"] == gid), {**group, "state": "confirmed", "open": 0, "confirmed_by": by})


def _set_demographics(ws: Workspace, group: dict[str, Any], chosen: dict[str, Any], rejected: set[str], *, by: str) -> None:
    """The study's individual (D-29) from a document's demographics and the person's choice of population and sex, set
    as entered on each of the study's datasets that had none."""
    from modeler_project.dataset_register import set_study_facts

    if "population" not in chosen or "sex" not in chosen:
        return
    numbers = {DEMOGRAPHIC_LABEL[f["field"].split(".", 1)[1]][1]: f["stored"] for f in group["facts"]
               if f["field"].split(".", 1)[-1] in DEMOGRAPHIC_LABEL and f["field"].startswith("demographics.")}
    individual = {**numbers, **{k: v for k, v in chosen.items() if v is not None}}
    lacking = next(o["datasets"] for i in group["issues"] if i["id"].endswith("|demographics:population") for o in i["options"])
    for dataset_id in lacking:
        if dataset_id not in rejected:
            set_study_facts(ws, dataset_id, changes={"demographics": individual}, by=by)


def product_confirmed(ws: Workspace, profile_id: str) -> bool:
    """Whether the product a dissolution profile belongs to is confirmed (its release model is proposed only then)."""
    return any(g["kind"] == "product" and g["state"] == "confirmed" and any(i["id"] == profile_id for i in g["items"])
               for g in _product_groups(ws, record(ws)["selections"]))
