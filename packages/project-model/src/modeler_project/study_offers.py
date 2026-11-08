"""What a study's data sheet does not say, offered from what the project already holds (the owner, 2026-11-08, of two
study cards asking for the dose, the number of subjects, the dosage form and what the study is for: "it's not able to
answer all the things ... this will be the way users upload data").

A sheet read by code often holds only the concentrations. Before asking a person, each fact it lacks is looked for in:
- the sheet itself: its subjects' own columns, or a mean's n code verified (the number of subjects);
- the project's documents (the proposal and the client's files): a sentence that names the study, or any sentence of a
  document whose name names it ("093-26 Protocol.pdf"): a dose in mg, a number of subjects, a dosage form, a
  bioequivalence study;
- Start: the strengths of its scenarios (a dose), the proposal's dosage form (one oral form);
- the data plan: a bioequivalence study's purpose, as the application's template states it (VBE: external validation).

Each offer says where it comes from, and a document's quote opens on it. One is pre-selected when a document naming the
study gives it, or when it is the only value the project holds (two strengths and nothing saying which: both offered,
neither chosen). Nothing is saved here: the person reads the sheet with them, as with any answer (`sheet_intake.finish`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from modeler_project import ArtifactKind, Workspace
from modeler_project.brief import Citation, ProjectBrief
from modeler_project.documents import DocumentLibrary
from modeler_project.requirements import RequirementMatrix
from modeler_project.start_drafts import Sentence, document_sentences

_ROLE_SUFFIX = re.compile(r"[-_ ](?:TEST|T|RLD|REF|REFERENCE|R|IV)$", re.IGNORECASE)
_DOSE = re.compile(r"(\d+(?:\.\d+)?)\s*mg\b(?!\s*/)", re.IGNORECASE)
_N = re.compile(r"\b[Nn]\s*=\s*(\d{1,3})\b|\b(\d{1,3})\s+(?:healthy\s+)?(?:adult\s+)?(?:male\s+|female\s+)?"
                r"(?:subjects|volunteers|participants)\b", re.IGNORECASE)
_BE = re.compile(r"bioequivalen|\bBE (?:study|studies|trial)", re.IGNORECASE)
_MEDIUM = re.compile(r"dissolution|medium|media|buffer|vessel|USP", re.IGNORECASE)
FORMS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("mr", re.compile(r"extended[- ]release|modified[- ]release|prolonged[- ]release|controlled[- ]release|sustained[- ]"
                      r"release|\b(?:ER|XR|SR|CR|MR|XL)\b", re.IGNORECASE)),
    ("suspension", re.compile(r"\bsuspensions?\b", re.IGNORECASE)),
    ("solution", re.compile(r"\boral solutions?\b", re.IGNORECASE)),
    ("ir_capsule", re.compile(r"\bcapsules?\b", re.IGNORECASE)),
    ("ir_tablet", re.compile(r"\btablets?\b", re.IGNORECASE)),
)
SHEET_FORMS = ("solution", "suspension", "ir_tablet", "ir_capsule", "mr", "other")
FORM_LABEL = {"solution": "Solution", "suspension": "Suspension", "ir_tablet": "IR tablet", "ir_capsule": "IR capsule",
              "mr": "Modified release", "other": "Other"}
PURPOSE_LABEL = {"model_building": "Model building", "external_validation": "External validation",
                 "application_verification": "Application verification"}


@dataclass(frozen=True)
class Context:
    """What the offers are read from, loaded once for every sheet on the page."""

    sentences: tuple[Sentence, ...]
    brief: ProjectBrief | None
    be_purposes: tuple[tuple[str, str, str], ...]     # (purpose, label, req id) of the data plan's bioequivalence items


def context(ws: Workspace) -> Context:
    version = ws.latest(ArtifactKind.BRIEF, "main")
    brief = ProjectBrief.from_content(version.content) if version else None
    plan = ws.latest(ArtifactKind.REQUIREMENTS, "main")
    items = RequirementMatrix.from_content(plan.content).items if plan else ()
    purposes = tuple((i.purpose, i.label, i.req_id) for i in items
                     if i.kind == "dataset" and i.target == "BE study" and i.purpose in PURPOSE_LABEL)
    return Context(tuple(document_sentences(DocumentLibrary(ws))), brief, purposes)


def _study_pattern(study_id: str) -> re.Pattern[str] | None:
    """The study's own id however a document writes it ("093-26-TEST" is "093-26", "093/26", "093 26" or "09326")."""
    base = study_id.strip()
    while _ROLE_SUFFIX.search(base):
        base = _ROLE_SUFFIX.sub("", base)
    tokens = re.findall(r"[A-Za-z]+|\d+", base)
    if not tokens or not any(t.isdigit() for t in tokens):
        return None                       # a name with no number in it would be read in too many sentences
    return re.compile(r"(?<![A-Za-z0-9])" + r"[-_/. ]?".join(map(re.escape, tokens)) + r"(?![A-Za-z0-9])", re.IGNORECASE)


def _about(ctx: Context, study_id: str) -> list[Sentence]:
    """The sentences that name the study, and every sentence of a document whose name names it."""
    pattern = _study_pattern(study_id)
    if pattern is None:
        return []
    return [s for s in ctx.sentences if pattern.search(s.text) or pattern.search(s.source)]


def _peek(c: Citation | Sentence) -> dict[str, Any]:
    if isinstance(c, Sentence):
        c = c.cite()
    return {"doc_sha256": c.doc_sha256, "page": c.page, "locator": f"p. {c.page}", "title": c.source or "source",
            "quote": c.quote[:600]}


def _offer(value: Any, shown: str, where: str, source: dict[str, Any] | None, *, document: bool) -> dict[str, Any]:
    return {"value": f"{value:g}" if isinstance(value, float) else str(value), "label": f"{shown} · {where}",
            "source": source, "document": document}


def _from_documents(about: list[Sentence], need: str) -> list[dict[str, Any]]:
    out = []
    for s in about:
        where = f"{s.source}, p. {s.page}"
        if need == "dose":
            doses = {float(m.group(1)) for m in _DOSE.finditer(s.text)}
            if len(doses) == 1:           # a sentence giving two doses does not say which this sheet is
                dose = doses.pop()
                out.append(_offer(dose, f"{dose:g} mg", where, _peek(s), document=True))
        elif need == "n" and (m := _N.search(s.text)):
            n = int(m.group(1) or m.group(2))
            if n > 0:
                out.append(_offer(n, str(n), where, _peek(s), document=True))
        elif need == "formulation" and not _MEDIUM.search(s.text):
            form = next((f for f, pattern in FORMS if pattern.search(s.text)), None)
            if form:
                out.append(_offer(form, FORM_LABEL[form], where, _peek(s), document=True))
    return out


def _from_start(ctx: Context, need: str) -> list[dict[str, Any]]:
    brief = ctx.brief
    if brief is None:
        return []
    out = []
    if need == "dose":
        for i in range(len(brief.groups.get("scenarios", ()))):
            record = brief.get(f"scenarios[{i}].dose")
            if isinstance(record.value, int | float) and record.value > 0:
                cite = _peek(record.citations[0]) if record.citations else None
                out.append(_offer(float(record.value), f"{float(record.value):g} mg", "a strength on Start", cite,
                                  document=False))
    elif need == "formulation":
        record = brief.get("scope.formulation_types")
        forms = [f for f in (record.value or []) if f in SHEET_FORMS]
        if len(forms) == 1:               # one oral dosage form in the proposal: the study's
            cite = _peek(record.citations[0]) if record.citations else None
            out.append(_offer(forms[0], FORM_LABEL[forms[0]], "the proposal's product on Start", cite, document=False))
    return out


def _purpose(ctx: Context, study_id: str, about: list[Sentence]) -> list[dict[str, Any]]:
    """A bioequivalence study's purpose as the data plan states it: an arm of a test or reference product, or a study a
    document calls a bioequivalence study."""
    arm = bool(_ROLE_SUFFIX.search(study_id.strip())) and not study_id.strip().upper().endswith("IV")
    if not ctx.be_purposes or not (arm or any(_BE.search(s.text) for s in about)):
        return []
    return [_offer(purpose, PURPOSE_LABEL[purpose], f"the data plan: {label} ({req})", None, document=False)
            for purpose, label, req in ctx.be_purposes[:1]]


def _from_sheet(points: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The number of subjects the sheet itself holds: a mean's n code verified, else its subjects' own columns."""
    series = (points or {}).get("series") or []
    stated = next((int(s["n"]) for s in series if s.get("statistic") != "individual" and s.get("n")), None)
    if stated:
        return [_offer(stated, str(stated), "the sheet's mean row (its n)", None, document=True)]
    subjects = [s["name"] for s in series if s.get("statistic") == "individual"]
    if len(subjects) >= 2:
        return [_offer(len(subjects), str(len(subjects)), f"the sheet: {len(subjects)} subjects' columns "
                       f"({subjects[0]} … {subjects[-1]})", None, document=True)]
    return []


def offers(ctx: Context, study_id: str, needs: list[str], points: dict[str, Any] | None = None) -> dict[str, list[dict[str, Any]]]:
    """For each need, the values the project holds for it, the sheet's and documents' first; none pre-selected here.
    `points`: the sheet's own series as code read them (its subjects, a mean's n)."""
    about = _about(ctx, study_id)
    out: dict[str, list[dict[str, Any]]] = {}
    for need in needs:
        found = ((_from_sheet(points) if need == "n" else []) + _from_documents(about, need) + _from_start(ctx, need)
                 if need in ("dose", "n", "formulation")
                 else _purpose(ctx, study_id, about) if need == "purpose" else [])
        seen: set[str] = set()            # one offer per value, the first source's (a document before Start)
        unique = [o for o in found if o["value"] not in seen and not seen.add(o["value"])]
        if unique:
            out[need] = unique
    return out


def preselect(offered: list[dict[str, Any]]) -> str | None:
    """The value to pre-fill: a document naming the study gives it, or the project holds only that one value."""
    if not offered:
        return None
    if offered[0].get("document"):
        return str(offered[0]["value"])
    values = {str(o["value"]) for o in offered}
    return values.pop() if len(values) == 1 else None
