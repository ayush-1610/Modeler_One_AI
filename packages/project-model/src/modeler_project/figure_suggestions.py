"""Figures worth digitizing (plan 2026-11-10, R5; the owner's decision 3: "suggest only when no table has the values,
and only for those that are important").

The reading agent suggests a figure only when it is a study's concentration-time profile or a product's dissolution
profile, its caption quoted from its page (`modeler_agents.document_reader.suggest_digitization`); nothing is filed for
a person. Here code decides which suggestions are still open: one is shown only while no table holds the same values,
that is while the project has no dataset of the study (by any name the files link to it, a digitized one included) or no
dissolution profile of the product. A withdrawn file's suggestions are not shown.
"""

from __future__ import annotations

from typing import Any

from modeler_intake.document_reading import name_key
from modeler_project.client_data import READABLE_DOCUMENTS, document_links, submissions
from modeler_project.dataset_register import datasets
from modeler_project.dissolution_register import profiles
from modeler_project.documents import DocumentLibrary
from modeler_project.evidence import EvidenceState
from modeler_project.workspace import Workspace

DIGITIZABLE = ("pdf",)   # the kinds the digitizer opens a page of; a Word file's figure is saved as an image first


def _names(ws: Workspace, kind: str, name: str) -> set[str]:
    """The name's key and every name the client's files link to it (one study or product, however written)."""
    keys = {name_key(name)}
    pairs = [{name_key(n) for n in link["names"]} for link in document_links(ws, kind)]
    grew = True
    while grew:
        grew = False
        for pair in pairs:
            if pair & keys and not pair <= keys:
                keys |= pair
                grew = True
    return {k for k in keys if k}


def open_suggestions(ws: Workspace) -> list[dict[str, Any]]:
    """The figures to suggest to a person now: each with its file, page, caption and the study or product it shows."""
    library = DocumentLibrary(ws)
    studies = {name_key(str(d.study.get("study_id", ""))) for d in datasets(ws) if d.state is not EvidenceState.REJECTED}
    products = {name_key(str(p.get("key", {}).get("product", ""))) for p in profiles(ws)}
    out = []
    for sub in submissions(ws):
        if sub.get("kind") not in READABLE_DOCUMENTS or not sub.get("figure_suggestions"):
            continue
        if library.has_record and library.entry(sub["sha256"]).withdrawn is not None:
            continue
        for figure in sub["figure_suggestions"]:
            if figure["kind"] == "concentration_time":
                held = bool(_names(ws, "study", figure.get("study_id", "")) & studies)
            else:
                held = bool(_names(ws, "product", figure.get("product", "")) & products)
            if not held:
                out.append({**figure, "sid": sub["id"], "file": sub["file"], "doc_sha256": sub["sha256"],
                            "study_id": figure.get("study_id", ""), "product": figure.get("product", ""),
                            "digitizable": sub.get("kind") in DIGITIZABLE})
    return out
