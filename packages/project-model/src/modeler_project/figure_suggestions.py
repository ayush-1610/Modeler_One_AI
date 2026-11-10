"""Figures worth digitizing (plan 2026-11-10, R5; the owner's decision 3: "suggest only when no table has the values,
and only for those that are important").

The reading agent suggests a figure only when it is a study's concentration-time profile or a product's dissolution
profile, its caption quoted from its page (`modeler_agents.document_reader.suggest_digitization`); nothing is filed for
a person. Here code decides which suggestions are still open: one is shown only while no table holds the same values:
- a concentration-time figure, while the project has no concentration-time profile of the study (an NCA table does not
  hold the curve's values);
- a dissolution figure, while the product has no profile in each medium and pH the caption names (a pH 6.8 table does
  not hold a pH 1.2 figure's values).
A study or product counts under every name a person confirmed for it on Inputs, and under the names the client's
files link to it unless the person answered that they are not one. A withdrawn file's suggestions are not shown.
"""

from __future__ import annotations

from typing import Any

from modeler_intake.document_reading import name_key
from modeler_project.client_data import READABLE_DOCUMENTS, document_links, submissions
from modeler_project.client_review import ALIASES
from modeler_project.client_review import record as review_record
from modeler_project.dataset_register import datasets
from modeler_project.dissolution_register import profiles
from modeler_project.documents import DocumentLibrary
from modeler_project.evidence import EvidenceState
from modeler_project.workspace import Workspace

DIGITIZABLE = ("pdf",)   # the kinds the digitizer opens a page of; a Word file's figure is saved as an image first
_SCOPE = {"study": "link", "product": "plink"}     # the review's link issue of each kind


def _names(ws: Workspace, kind: str, name: str, review: dict[str, Any], files: dict[str, dict[str, Any]],
           library: DocumentLibrary) -> set[str]:
    """The name's key and every name it is one with: the aliases a person confirmed, and the names the client's files
    link to it, unless a person answered that the name is another one (or the link's file is withdrawn)."""
    scope = _SCOPE[kind]
    refused = {name_key(issue.split("|", 1)[1]) for issue, chosen in review.get("selections", {}).items()
               if issue.startswith(f"{scope}|") and chosen.get("option") == "different"}
    pairs = [{name_key(a), name_key(b)} for a, b in review.get(ALIASES[scope], {}).items()]
    for link in document_links(ws, kind):
        sub = files.get(link.get("sid", ""))
        if sub is not None and library.has_record and library.entry(sub["sha256"]).withdrawn is not None:
            continue
        keys = {name_key(n) for n in link["names"]}
        if not keys & refused:
            pairs.append(keys)
    keys = {name_key(name)}
    grew = True
    while grew:
        grew = False
        for pair in pairs:
            if pair & keys and not pair <= keys:
                keys |= pair
                grew = True
    return {k for k in keys if k}


def _ph_of(value: Any) -> float | None:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def open_suggestions(ws: Workspace) -> list[dict[str, Any]]:
    """The figures to suggest to a person now: each with its file, page, caption and the study or product it shows."""
    library = DocumentLibrary(ws)
    review = review_record(ws)
    every = {sub["id"]: sub for sub in submissions(ws)}
    # concentration-time profiles only: an NCA table (pk_parameters) does not hold a curve's values
    studies = {name_key(str(d.study.get("study_id", ""))) for d in datasets(ws)
               if d.state is not EvidenceState.REJECTED and d.kind == "profile"}
    held_conditions = [(name_key(str(k.get("product", ""))), _ph_of(k.get("ph")), str(k.get("medium") or "").lower())
                       for p in profiles(ws) for k in [p.get("key", {})]]
    out = []
    for sub in every.values():
        if sub.get("kind") not in READABLE_DOCUMENTS or not sub.get("figure_suggestions"):
            continue
        if library.has_record and library.entry(sub["sha256"]).withdrawn is not None:
            continue
        for n, figure in enumerate(sub["figure_suggestions"]):
            if figure["kind"] == "concentration_time":
                held = bool(_names(ws, "study", figure.get("study_id", ""), review, every, library) & studies)
            else:
                names = _names(ws, "product", figure.get("product", ""), review, every, library)
                wanted = [_ph_of(p) for p in figure.get("ph", [])] or [None]
                medium = str(figure.get("medium") or "").lower()
                held = all(any(product in names and (ph is None or held_ph == ph) and (not medium or medium in held_medium)
                               for product, held_ph, held_medium in held_conditions) for ph in wanted)
            if not held:
                out.append({"kind": figure["kind"], "page": figure["page"], "quote": figure["quote"], "n": n,
                            "sid": sub["id"], "file": sub["file"], "doc_sha256": sub["sha256"],
                            "study_id": figure.get("study_id", ""), "product": figure.get("product", ""),
                            "medium": str(figure.get("medium") or ""), "ph": [p for p in figure.get("ph", [])],
                            # the digitizer opens a PDF's page and makes a concentration-time profile
                            "digitizable": sub.get("kind") in DIGITIZABLE and figure["kind"] == "concentration_time"})
    return out
