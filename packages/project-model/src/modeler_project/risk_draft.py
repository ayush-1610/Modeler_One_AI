"""The ICH M15 ratings drafted by code, by the rule in `m15_draft.yaml`, when the intake agent left them empty (the owner,
2026-11-07: everything on Start pre-filled; the rule approved by the owner the same day, UNVERIFIED until the SME signs).

The model influence and the decision consequence are suggested (`m15.*_suggested`, which Start pre-selects), each with
why in a sentence (`m15.influence`, `m15.consequence`), and, when the two differ, why the stricter model risk fits
(`m15.risk_justification`). All DRAFTED: a person saves the ratings and confirms or changes the texts. Nothing is drafted
over a rating a person set, a suggestion the intake agent made, or a text a person wrote or a document states.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any

import yaml

from modeler_project.brief import FieldStatus, ProjectBrief
from modeler_project.brief_ops import agent_set, locked
from pbpk_domain.m15 import Rating, allowed_model_risk

RULE = "code:m15-draft-rule"


@dataclass(frozen=True)
class Rule:
    rating: str
    when: str
    text: str
    words: tuple[str, ...] = ()
    applications: tuple[str, ...] = ()
    default: bool = False


@cache
def ruleset() -> dict[str, Any]:
    """`m15_draft.yaml`: its version and status, the rules for each rating, who is at risk, the tier's reason."""
    raw = yaml.safe_load(resources.files("modeler_project").joinpath("m15_draft.yaml").read_text(encoding="utf-8"))
    rules = {dim: tuple(Rule(rating=r["rating"], when=r["when"], text=" ".join(r["text"].split()),
                             words=tuple(r.get("words", ())), applications=tuple(r.get("applications", ())),
                             default=bool(r.get("default"))) for r in raw[dim])
             for dim in ("influence", "consequence")}
    return {"version": str(raw["version"]), "status": raw["status"], **rules, "who": tuple(raw["who"]),
            "why_this_tier": " ".join(raw["why_this_tier"].split())}


@cache
def _word(word: str) -> re.Pattern[str]:
    """An acronym (FDA, NTI) as a whole word, case kept; any other word as the start of a word, any case ("neonat" reads
    "neonates")."""
    if word.isupper() and len(word) <= 5:
        return re.compile(rf"\b{re.escape(word)}\b")
    return re.compile(rf"\b{re.escape(word)}", re.IGNORECASE)


def _says(text: str, words: tuple[str, ...] | list[str]) -> bool:
    return any(_word(w).search(text) for w in words)


def _match(rules: tuple[Rule, ...], text: str, apps: set[str]) -> Rule:
    return next(r for r in rules if r.default or _says(text, r.words) or apps & set(r.applications))


def _text(brief: ProjectBrief, path: str) -> str:
    value = brief.get(path).value          # a draft is read too: the rule drafts from what Start shows
    return " ".join(map(str, value)) if isinstance(value, list) else str(value or "")


def draft_risk(brief: ProjectBrief, *, proposal: list[str] | tuple[str, ...] = (), by: str = RULE
               ) -> tuple[ProjectBrief, list[str]]:
    """Draft the ICH M15 ratings and their reasons by the rule, when nothing has suggested them; the paths drafted.
    `proposal`: the proposal's sentences; one stating a narrow therapeutic index is read with the context of use."""
    if any(brief.get(p).value not in (None, "") for p in ("m15.influence_suggested", "m15.consequence_suggested",
                                                           "m15.influence_rating", "m15.consequence_rating")):
        return brief, []
    use = _text(brief, "qoi.context_of_use").strip()
    if not use:
        return brief, []                  # nothing to draft from: the context of use comes first
    rules = ruleset()
    said = " ".join((_text(brief, "qoi.text"), use))
    apps = {str(a).split(" ", 1)[0] for a in (brief.get("qoi.applications").value or [])}
    influence = _match(rules["influence"], said, apps)
    stakes = " ".join([said, *(s for s in proposal if _says(s, ["narrow therapeutic", "NTI"]))])
    consequence = _match(rules["consequence"], stakes, apps)
    who = next((w["name"] for w in rules["who"] if _says(stakes, w["words"]) or apps & set(w["applications"])), "patients")
    short = use if len(use) <= 200 else use[:197] + "…"
    drafts: list[tuple[str, str]] = [
        ("m15.influence_suggested", influence.rating), ("m15.consequence_suggested", consequence.rating),
        ("m15.influence", influence.text.format(use=short)), ("m15.consequence", consequence.text.format(who=who))]
    admitted = [r.value for r in allowed_model_risk(Rating(influence.rating), Rating(consequence.rating))]
    if len(admitted) > 1:
        higher = "model influence" if admitted[-1] == influence.rating else "decision consequence"
        drafts.append(("m15.risk_justification", rules["why_this_tier"].format(
            admitted=f"{admitted[0]} to {admitted[-1]}", tier=admitted[-1], dimension=higher, rating=admitted[-1])))
    citations = tuple(c for p in ("qoi.context_of_use", "qoi.text") for c in brief.get(p).citations)
    tag = f"m15_draft {rules['version']} ({rules['status']})"
    why = {"m15.influence_suggested": influence.when, "m15.influence": influence.when,
           "m15.consequence_suggested": consequence.when, "m15.consequence": consequence.when,
           "m15.risk_justification": "the ratings differ: the stricter model risk"}
    drafted = []
    for path, value in drafts:
        record = brief.get(path)
        if locked(brief, path) or record.status is FieldStatus.EXTRACTED or record.value not in (None, ""):
            continue
        brief = agent_set(brief, path, value=value, unit=None, citations=citations, status=FieldStatus.DRAFTED,
                          confidence=None, by=by, note=f"drafted by code from the rule {tag}: {why[path]}")
        drafted.append(path)
    return brief, drafted
