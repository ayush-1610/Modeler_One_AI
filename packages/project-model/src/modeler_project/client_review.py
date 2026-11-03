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
"""

from __future__ import annotations

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

GroupKind = Literal["study", "product", "compound"]
TAB: dict[str, str] = {"study": "studies", "product": "formulations", "compound": "compound"}
FACT_LABEL = {"dose_mg": "Dose (mg)", "route": "Route", "food_state": "Food state", "formulation": "Formulation",
              "n": "Subjects (n)", "lloq": "LLOQ"}
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


def _study_groups(ws: Workspace, selections: dict[str, Any]) -> list[dict[str, Any]]:
    from modeler_project.dataset_register import datasets

    by_study: dict[str, list[ObservedDataset]] = defaultdict(list)
    for d in datasets(ws):
        if _client_dataset(d) and d.state is not EvidenceState.REJECTED:
            by_study[str(d.study.get("study_id", d.id))].append(d)
    groups = []
    for study_id, members in sorted(by_study.items()):
        gid = f"study:{study_id}"
        items = [{"id": d.id, "kind": "dataset", "label": f"{d.kind} · {len(d.series) or len(d.reported)} "
                  f"{'series' if d.kind == 'profile' else 'PK parameters'} · {d.analyte}, {d.matrix}",
                  "value": f"{d.unit}, time in {d.time_unit}", "state": d.state.value,
                  "source": _source(d.source, d.quote)} for d in members]
        facts, issues = [], []
        for field, label in FACT_LABEL.items():
            given = [(d, d.study.get(field)) for d in members if d.study.get(field) is not None]
            distinct: dict[Any, list[ObservedDataset]] = defaultdict(list)
            for d, value in given:
                distinct[_normal(field, value)].append(d)
            if len(distinct) > 1:
                explainable = field in rule()["explainable"]["fields"]
                options = [{"id": f"v{i}", "label": _shown(ds[0].study[field]), "value": ds[0].study[field],
                            "source": _source(ds[0].source, ds[0].quote), "datasets": [d.id for d in ds]}
                           for i, (_v, ds) in enumerate(distinct.items())]
                options.append({"id": "explained" if explainable else "different",
                                "label": "Explained: dosed and PK-evaluable counts differ" if explainable
                                else "They are different things: each file keeps its own value",
                                "value": None, "source": None, "datasets": []})
                issues.append(_issue(gid, field, "difference" if explainable else "conflict",
                                     f"{label}: the client's files give {len(distinct)} values", options, selections))
            elif given:
                d, value = given[0]
                facts.append({"field": field, "label": label, "value": _shown(value), "source": _source(d.source, d.quote)})
        for d in members:
            if d.study.get("route") == "oral" and not d.study.get("food_state"):
                issues.append(_issue(gid, f"food_state:{d.id}", "question", "Oral study with no food state: fasted or fed?",
                                     [{"id": "fasted", "label": "Fasted", "value": "fasted", "source": None, "datasets": [d.id]},
                                      {"id": "fed", "label": "Fed", "value": "fed", "source": None, "datasets": [d.id]}],
                                     selections))
            if d.kind == "profile" and d.study.get("lloq") is None and any(v is None for s in d.series for v in s.values):
                issues.append(_issue(gid, f"lloq:{d.id}", "question",
                                     f"Values below the LLOQ, and no LLOQ stated: give it in {d.unit}",
                                     [], selections, answer=True))
        groups.append(_group(gid, "study", f"Study {study_id}", items, facts, issues, ws))
    return groups


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


def _product_groups(ws: Workspace, selections: dict[str, Any]) -> list[dict[str, Any]]:
    from modeler_project.dissolution_register import profiles

    by_product: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in profiles(ws):
        by_product[str(p["key"].get("product") or "product")].append(p)
    groups = []
    for product, members in sorted(by_product.items()):
        gid = f"product:{product}"
        items = [{"id": p["id"], "kind": "profile", "label": p["label"],
                  "value": f"{len(p['times_min'])} times to {max(p['times_min'], default=0):g} min · n = {p['n']}",
                  "state": "PROPOSED", "note": "; ".join(p.get("flags", [])),
                  "source": {"doc_sha256": None, "page": None, "locator": ", ".join(p.get("cells", [])[:3]),
                             "title": ", ".join(p.get("files", [])), "quote": ""}} for p in members]
        groups.append(_group(gid, "product", product, items, [], [], ws, versions={p["id"]: p["version"] for p in members}))
    return groups


def _issue(gid: str, key: str, kind: str, text: str, options: list[dict[str, Any]], selections: dict[str, Any], *,
           answer: bool = False) -> dict[str, Any]:
    iid = f"{gid}|{key}"
    chosen = selections.get(iid)
    return {"id": iid, "kind": kind, "text": text, "options": options, "answer": answer,
            "selected": chosen.get("option") if chosen else None, "answered": chosen.get("answer") if chosen else None,
            "selected_by": chosen.get("by") if chosen else None, "selected_at": chosen.get("at") if chosen else None}


def _group(gid: str, kind: GroupKind, title: str, items: list[dict[str, Any]], facts: list[dict[str, Any]],
           issues: list[dict[str, Any]], ws: Workspace, versions: dict[str, int] | None = None) -> dict[str, Any]:
    confirmation = record(ws)["confirmations"].get(gid)
    if kind == "product":
        confirmed = confirmation is not None and all(confirmation.get("versions", {}).get(i["id"]) == v
                                                     for i, v in ((i, (versions or {})[i["id"]]) for i in items))
        for i in items:
            i["state"] = "ACCEPTED" if confirmed else "PROPOSED"
    else:
        confirmed = bool(items) and not any(i["state"] == EvidenceState.PROPOSED.value for i in items)
    if confirmed and confirmation:   # as they were settled, in their order; anything new after them
        recorded = confirmation.get("issues", [])
        known = {i["id"] for i in recorded}
        issues = recorded + [i for i in issues if i["id"] not in known]
    open_issues = [i for i in issues if i["selected"] is None and i["answered"] is None]
    return {"id": gid, "kind": kind, "tab": TAB[kind], "title": title, "items": items, "facts": facts, "issues": issues,
            "state": "confirmed" if confirmed else "to_confirm", "open": len(open_issues),
            "confirmed_by": confirmation.get("by") if confirmation and confirmed else None,
            "confirmed_at": confirmation.get("at") if confirmation and confirmed else None}


def groups(ws: Workspace) -> list[dict[str, Any]]:
    """Every group of client data, with its items, its facts, and its conflicts and questions (settled or open)."""
    selections = record(ws)["selections"]
    return _study_groups(ws, selections) + _product_groups(ws, selections) + _compound_groups(ws, selections)


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
    update_review(ws, lambda content: ({**content, "selections": {**content["selections"], issue_id: {
        **chosen, "group": gid, "by": by, "at": datetime.now(UTC).isoformat()}}}, f"{issue['text']}: selected {shown}"), by=by)
    return _find(ws, gid)


def reopen(ws: Workspace, gid: str, issue_id: str, *, by: str) -> dict[str, Any]:
    """Change a settled conflict or question before the group is confirmed."""
    group = _find(ws, gid)
    if group["state"] == "confirmed":
        raise ReviewError(f"{group['title']} is confirmed already")
    update_review(ws, lambda content: None if issue_id not in content["selections"] else (
        {**content, "selections": {k: v for k, v in content["selections"].items() if k != issue_id}},
        f"{issue_id}: selection reopened"), by=by)
    return _find(ws, gid)


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
    from modeler_project.dataset_register import decide_dataset, set_study_facts
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
    for issue in group["issues"]:
        chosen = content["selections"][issue["id"]]
        key = issue["id"].split("|", 1)[1]
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
             "issues": group["issues"]}   # kept, so each settled conflict stays shown with its final value
    if group["kind"] == "product":
        from modeler_project.dissolution_register import profiles

        entry["versions"] = {p["id"]: p["version"] for p in profiles(ws) if p["id"] in entry["items"]}
    update_review(ws, lambda content: ({**content, "confirmations": {**content["confirmations"], gid: entry}},
                                       f"{group['title']} confirmed: {len(group['items'])} items load into the project"), by=by)
    # a group whose every value was set aside for another source has nothing left to show
    return next((g for g in groups(ws) if g["id"] == gid), {**group, "state": "confirmed", "open": 0, "confirmed_by": by})


def product_confirmed(ws: Workspace, profile_id: str) -> bool:
    """Whether the product a dissolution profile belongs to is confirmed (its release model is proposed only then)."""
    return any(g["kind"] == "product" and g["state"] == "confirmed" and any(i["id"] == profile_id for i in g["items"])
               for g in _product_groups(ws, record(ws)["selections"]))
