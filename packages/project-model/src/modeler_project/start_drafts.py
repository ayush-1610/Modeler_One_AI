"""What code reads for Start from the proposal's own words, for every Start field the intake agent left empty (the owner,
2026-11-06: "making sure everything is there; the user will just see through and only change in case the selection or
pre-fills are way wrong").

The floor under the intake agent (A1), and Start's reading when agents are off. Each draft is DRAFTED, not a value until
a person confirms or changes it, and rests on the sentence it was read from, quoted from its page:
- the question of interest: the proposal's objective sentence ("Objective", "to predict / evaluate / support …");
- the context of use: the sentence saying what the results are for (a submission, a waiver, the label, an agency);
- the applications: by what the proposal names (bioequivalence, food effect, an interaction, children, impairment …);
- the formulation types: the dosage forms it names (an extended-release tablet is modified release; a tablet or capsule
  with no release named is immediate release); a dissolution medium is never read as a solution;
- the routes: oral when the product is taken by mouth or is a tablet or capsule; intravenous when an infusion or bolus is
  named.
Two choices are defaults, said so: a full (whole-body) PBPK model of systemic action, the only model the builder makes
(D-28), unless the proposal speaks of a local site of action. A field a person set, or a document states, is kept.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from modeler_project.brief import Citation, FieldStatus, ProjectBrief
from modeler_project.brief_ops import agent_set, locked
from modeler_project.documents import DocumentLibrary, document_record

CODE = "code:start-reading"
NOTE = "read by code from the proposal's words (the intake agent left it empty): {why}"
_SENTENCE = re.compile(r"[^.!?\n]{20,600}[.!?]?")
_MEDIUM = re.compile(r"dissolution|medium|media|buffer|vessel|USP", re.IGNORECASE)
_MR = re.compile(r"extended[- ]release|modified[- ]release|prolonged[- ]release|controlled[- ]release|sustained[- ]release|"
                 r"delayed[- ]release|\b(?:ER|XR|SR|CR|MR|XL|PR)\b", re.IGNORECASE)
FORMS: tuple[tuple[str, re.Pattern[str], bool], ...] = (       # (option, pattern, never in a dissolution sentence)
    ("suspension", re.compile(r"\bsuspensions?\b", re.IGNORECASE), True),
    ("solution", re.compile(r"\b(?:oral |drinking |intravenous |infusion )?solutions?\b", re.IGNORECASE), True),
    ("ir_tablet", re.compile(r"\btablets?\b", re.IGNORECASE), False),
    ("ir_capsule", re.compile(r"\bcapsules?\b", re.IGNORECASE), False),
)
ROUTES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("iv_infusion", re.compile(r"\b(?:intravenous|i\.?v\.?)\s+infusion|\binfused\b", re.IGNORECASE)),
    ("iv_bolus", re.compile(r"\b(?:intravenous|i\.?v\.?)\s+bolus|\bbolus injection", re.IGNORECASE)),
    ("oral", re.compile(r"\boral(?:ly)?\b|\bby mouth\b|\btablets?\b|\bcapsules?\b", re.IGNORECASE)),
)
APPLICATIONS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("APP-14 virtual bioequivalence", re.compile(r"bioequivalen|\bVBE\b|\bBE (?:study|studies|trial)", re.IGNORECASE)),
    ("APP-12 food effect", re.compile(r"food[- ]effect|\bfed\b|high[- ]fat|with food", re.IGNORECASE)),
    ("APP-03 enzyme DDI", re.compile(r"drug[- ]drug interaction|\bDDI\b|\bCYP\d[A-Z]\d+ (?:inhibitor|inducer)", re.IGNORECASE)),
    ("APP-06 pediatric extrapolation", re.compile(r"p(?:a)?ediatric|\bchildren\b|\binfants?\b|\bneonat", re.IGNORECASE)),
    ("APP-07 hepatic impairment", re.compile(r"hepatic impairment", re.IGNORECASE)),
    ("APP-08 renal impairment", re.compile(r"renal impairment", re.IGNORECASE)),
    ("APP-09 pregnancy and lactation", re.compile(r"pregnan|lactation", re.IGNORECASE)),
    ("APP-13 pH-dependent DDI", re.compile(r"pH[- ]dependent|acid[- ]reducing|proton[- ]pump", re.IGNORECASE)),
    ("APP-11 absorption and formulation", re.compile(r"dissolution|\bformulation\b|absorption|biowaiver|\bIVIVC\b|release profile",
                                                     re.IGNORECASE)),
    ("APP-02 FIH translation", re.compile(r"first[- ]in[- ]human|\bFIH\b", re.IGNORECASE)),
    ("APP-18 dose and regimen", re.compile(r"dose selection|dosing regimen|dose adjustment", re.IGNORECASE)),
)
_OBJECTIVE = re.compile(r"\b(?:objectives?|aims?|purpose|goals?)\b", re.IGNORECASE)
_GOAL_VERB = re.compile(r"\bto (?:predict|evaluate|assess|demonstrate|simulate|investigate|establish|determine|"
                        r"develop|build|characteri[sz]e)\b", re.IGNORECASE)
_USE = re.compile(r"\b(?:support|submission|regulatory|waiver|biowaiver|label(?:ling)?|agency|approval|Health Canada|FDA|EMA|"
                  r"filing|dossier|justify|justification)\b", re.IGNORECASE)
# what the results are for, said plainly (a sentence that only says "support" is weaker)
_USE_STRONG = re.compile(r"\b(?:submission|regulatory|waiver|biowaiver|label(?:ling)?|agency|approval|Health Canada|FDA|EMA|"
                         r"filing|dossier)\b", re.IGNORECASE)
_LOCAL = re.compile(r"\b(?:topical|local(?:ly)? acting|inhaled|ophthalmic|intra-?articular)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Sentence:
    text: str
    sha: str
    page: int
    source: str

    def cite(self) -> Citation:
        return Citation(doc_sha256=self.sha, page=self.page, quote=self.text, source=self.source)


def sentences(library: DocumentLibrary) -> list[Sentence]:
    """The proposal's sentences, page by page (the documents the person gave as the proposal; else every document but
    the records code retrieved)."""
    records = [r for r in map(document_record, library.documents()) if r.role != "retrieved_record"]
    proposals = [r for r in records if r.role == "proposal"] or records
    out = []
    for record in proposals:
        for number, text in enumerate(library.pages(record.sha256), start=1):
            for match in _SENTENCE.finditer(text):
                sentence = " ".join(match.group(0).split()).strip(" -•*#")
                if len(sentence) >= 20:
                    out.append(Sentence(sentence, record.sha256, number, record.name))
    return out


def _open(brief: ProjectBrief, path: str) -> bool:
    record = brief.get(path)
    return (not locked(brief, path) and record.status is not FieldStatus.EXTRACTED
            and record.value in (None, "", []))


def _first(found: list[Sentence], pattern: re.Pattern[str], *, avoid: re.Pattern[str] | None = None,
           not_in: set[str] = frozenset(), strong: re.Pattern[str] | None = None) -> Sentence | None:
    """The sentence to quote: one that matches; a full sentence before a heading, one with `strong` words before one
    without, the earliest otherwise."""
    hits = [s for s in found if pattern.search(s.text) and not (avoid and avoid.search(s.text)) and s.text not in not_in]
    if not hits:
        return None
    return min(enumerate(hits), key=lambda ih: (not (strong and strong.search(ih[1].text)),
                                                not ih[1].text.endswith((".", "!", "?")), ih[0]))[1]


def read_for_start(library: DocumentLibrary, brief: ProjectBrief, *, by: str = CODE) -> tuple[ProjectBrief, list[str]]:
    """Draft every Start field still empty from the proposal's words (and the two defaults); the paths drafted."""
    found = sentences(library)
    drafted: list[str] = []

    def put(path: str, value: Any, why: str, cites: tuple[Citation, ...] = ()) -> None:
        nonlocal brief
        if not _open(brief, path):
            return
        brief = agent_set(brief, path, value=value, unit=None, citations=cites, status=FieldStatus.DRAFTED,
                          confidence=None, by=by, note=NOTE.format(why=why))
        drafted.append(path)

    if found:
        goal = _first(found, _OBJECTIVE) or _first(found, _GOAL_VERB)
        if goal:
            put("qoi.text", goal.text, "the proposal's objective", (goal.cite(),))
        use = _first(found, _USE, not_in={goal.text} if goal else set(), strong=_USE_STRONG)
        if use:
            put("qoi.context_of_use", use.text, "what the proposal says the results are for", (use.cite(),))
        apps = [(option, hit) for option, pattern in APPLICATIONS if (hit := _first(found, pattern))]
        if apps:
            put("qoi.applications", [o for o, _h in apps], "; ".join(f"{o.split(' ', 1)[1]}: “{h.text[:60]}…”" for o, h in apps),
                tuple(dict.fromkeys(h.cite() for _o, h in apps)))
        forms: dict[str, Sentence] = {}
        for option, pattern, not_medium in FORMS:
            hit = _first(found, pattern, avoid=_MEDIUM if not_medium else None)
            if hit:
                mr = option in ("ir_tablet", "ir_capsule") and _MR.search(hit.text)
                forms.setdefault("mr" if mr else option, hit)
        if forms:
            put("scope.formulation_types", list(forms), "the dosage forms the proposal names", tuple(s.cite() for s in forms.values()))
        # no scenario yet: one per route the proposal names (at most two); scenarios already there: a missing route is
        # filled only when the proposal names one route
        routes = [(option, hit) for option, pattern in ROUTES if (hit := _first(found, pattern, avoid=_MEDIUM))]
        items = brief.groups.get("scenarios", ())
        chosen = routes[:2] if not items else (routes * len(items) if len(routes) == 1 else [])
        for i, (option, hit) in enumerate(chosen):
            put(f"scenarios[{i}].route", option, f"the proposal gives the product {option.replace('_', ' ')}", (hit.cite(),))
    local = _first(found, _LOCAL) if found else None
    put("scope.pbpk_model", "full", "the default: the builder makes full (whole-body) PBPK models")
    if local is None:
        put("scope.site_of_action", "systemic", "the default: systemic action (plasma and tissue exposure)")
    return brief, drafted
