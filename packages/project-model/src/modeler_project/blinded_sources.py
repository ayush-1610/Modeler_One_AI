"""What D-15 withholds of the client's files, one rule for every view and route that would show it (final review INT-2,
INT-3): the client-review groups, the files and the sheets of the studies blinded until the MAP is signed.

A study is blinded by the delivery (`intake_review.blinded_subjects`: an external purpose entered on its card, a
dataset the delivery landed that the project's blinding list holds, or the same study the sheet form read as one the
list holds) or by the project's blinding list (`blinding.blinded_studies`: the plan's S5 / S6, the MS-01 split's
proposal before a plan, a dataset entered for external validation). Withheld:
- the client-review groups of such a study (by `legacy_groups`, or by the same name: `blinding.study_key`) and of a
  product the delivery blinds: their facts, options, answers and points;
- the files that hold such a study's values (the delivery's `intake_decisions.blinded_files`, and the files the
  datasets of a listed study were read from, a library paper included): no page line, the digits of their pages
  masked, the original not served, nothing drawn by the digitizer, no figure suggested from them. A file is withheld
  whole, as the delivery's rule withholds it: a paper one figure of which was digitized for a listed study waits with
  its other figures and pages (an owner's decision, plan 2026-11-14 §5 round 3); `by` names the studies, so the page
  says why;
- the sheets those values were read from (the delivery's anchors, the sheet form's readings that made a listed study's
  datasets, a template's sheets a listed study's rows are on): not shown, read or previewed;
- the values of such a study wherever its id names it (`withholds`, by the same names: its datasets' points and
  reported PK on the evidence and the client review, its catalog row's profile, the Studies list's chip), so no view
  shows the points of a study another view says are withheld (final review round 6).
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from typing import Any

from modeler_project import blinding, intake_decisions
from modeler_project import intake_review as delivery_review
from modeler_project.client_data import submissions
from modeler_project.dataset_register import datasets
from modeler_project.ledger_view import LedgerView
from modeler_project.workspace import Workspace


@dataclass(frozen=True)
class BlindedSources:
    """What is withheld now. `groups`: client-review group ids; `names`: "<kind>:<study_key>" of a blinded study or
    product (a group of that name is withheld); `files`: sha256s; `sheets`: the sheets of each workbook (by sha256);
    `by`: the blinded studies whose values each file holds (by sha256: a study's id as its dataset or card names it),
    what the page says a file is withheld for; `why`: why a group is withheld, in words, by its id or its name (as
    `groups` and `names` key it): the delivery's reason for the study it is joined to (`intake_review.blinded_why`), or
    why the project's blinding list holds the study of its name (`blinding.external_why`; round 4); `listed`: the
    project's list, each study id with why it is on it (`blinding.listed_why`)."""

    groups: frozenset[str] = frozenset()
    names: frozenset[str] = frozenset()
    files: frozenset[str] = frozenset()
    sheets: Mapping[str, frozenset[str]] = field(default_factory=dict)
    by: Mapping[str, frozenset[str]] = field(default_factory=dict)
    why: Mapping[str, str] = field(default_factory=dict)
    listed: Mapping[str, str] = field(default_factory=dict)

    def withholds(self, study_id: Any) -> bool:
        """Whether the values of the study of this id are withheld: the project's list holds it, or a study of its name is
        withheld (`names`: the list's under another spelling, or one the delivery blinds; `blinding.study_key`: a
        delivery study, a client-review group and a dataset of one name are one study for blinding). One rule for every
        view of a study's values, its datasets, its catalog row and its sheet form's group alike (final review round 6:
        the evidence redacted the list's studies only, so a study the delivery blinds kept its points on the card whose
        sheet-form line said they were withheld)."""
        return str(study_id) in self.listed or f"study:{blinding.study_key(study_id)}" in self.names

    def study_why(self, study_id: Any) -> str | None:
        """Why the study's values are withheld, in words (None for a study whose values are not): the list's reason for a
        study it holds (`blinding.listed_why`), else the reason of the study of its name (`why`)."""
        if not self.withholds(study_id):
            return None
        return self.listed.get(str(study_id)) or self.why.get(f"study:{blinding.study_key(study_id)}")

    def studies(self, sha256: str | None) -> list[str]:
        """The blinded studies a withheld file holds the values of, in order ([] for a file that is not withheld)."""
        return sorted(self.by.get(sha256 or "", ())) if self.file(sha256) else []

    def group(self, group: Mapping[str, Any]) -> bool:
        gid = str(group["id"])
        kind, _sep, name = gid.partition(":")
        return gid in self.groups or f"{kind}:{blinding.study_key(name)}" in self.names

    def reason(self, group: Mapping[str, Any]) -> str | None:
        """Why a withheld group is withheld, in words (None for a group that is not)."""
        if not self.group(group):
            return None
        gid = str(group["id"])
        kind, _sep, name = gid.partition(":")
        return self.why.get(gid) or self.why.get(f"{kind}:{blinding.study_key(name)}")

    def sheet(self, sha256: str, sheet: str) -> bool:
        return sheet in self.sheets.get(sha256, ())

    def file(self, sha256: str | None) -> bool:
        return bool(sha256) and sha256 in self.files

    def __bool__(self) -> bool:
        return bool(self.groups or self.names or self.files)


def _sheets_of(content: Mapping[str, Any], listed: Collection[str], studies: Mapping[str, str]) -> set[str]:
    """The sheets of a client workbook a listed study's values are on: the sheet form's readings (`mappings`, not
    replaced) that made one of its datasets, and a template's sheets its rows were read from (the dataset's locator,
    `Sheet!B3; Concentrations!5:20`)."""
    out: set[str] = set()
    for mapping in content.get("mappings", []):
        if not mapping.get("replaced_by") and any(studies.get(str(d)) in listed for d in mapping.get("datasets", [])):
            out |= {str(t.get("sheet")) for t in mapping.get("recipe", {}).get("tables", []) if t.get("sheet")}
    return out


def blinded_sources(ws: Workspace, project: dict[str, Any] | None, model_risk: str | None, *,
                    delivery: bool) -> BlindedSources:
    """What D-15 withholds now (empty when blinding is off or a MAP is signed). `delivery`: the intake pipeline runs
    (its rule joins the project's)."""
    listed_why = blinding.listed_why(ws, project, model_risk)
    hidden_why = delivery_review.blinded_why(ws, project, model_risk) if delivery else {}
    listed, hidden = set(listed_why), set(hidden_why)
    if not listed and not hidden:
        return BlindedSources()
    groups: set[str] = set()
    names = {f"study:{blinding.study_key(s)}" for s in listed}
    # why each is withheld (round 4: the sheet form's card says it, as the delivery's does): the list's reason by the
    # study's name, the delivery's (which names the list's where it is the list's) by its name and its joined groups
    why = {f"study:{blinding.study_key(s)}": f"the project's blinding list names it (study {s}): {listed_why[s]}"
           for s in sorted(listed, key=str)}
    files: set[str] = set()
    sheets: dict[str, set[str]] = {}
    by: dict[str, set[str]] = {}
    if listed:
        found = datasets(ws)
        studies = {d.id: str(d.study.get("study_id")) for d in found}
        mine = [d for d in found if str(d.study.get("study_id")) in listed and d.source.doc_sha256]
        files |= {str(d.source.doc_sha256) for d in mine}
        for d in mine:
            by.setdefault(str(d.source.doc_sha256), set()).add(str(d.study.get("study_id")))
        for content in submissions(ws):
            sha = str(content.get("sha256"))
            on = _sheets_of(content, listed, studies)
            names_of_sheets = {str(t.get("sheet")) for t in content.get("triage", []) if t.get("sheet")}
            for d in mine:
                if d.source.doc_sha256 == sha:
                    on |= {s for s in names_of_sheets if f"{s}!" in d.source.locator or d.source.locator.startswith(f"{s} (")}
            if on:
                files.add(sha)
                sheets.setdefault(sha, set()).update(on)
                for mapping in content.get("mappings", []):
                    if not mapping.get("replaced_by"):
                        by.setdefault(sha, set()).update(studies[str(d)] for d in mapping.get("datasets", [])
                                                         if studies.get(str(d)) in listed)
    if hidden:
        reader = LedgerView(ws)
        files |= intake_decisions.blinded_files(reader, hidden)
        for sha, on in intake_decisions.blinded_sheets(reader, hidden).items():
            sheets.setdefault(sha, set()).update(on)
        for value in reader.values(active=False):
            if value.file_sha256 and value.entity.study in hidden:
                entity = reader.entity(value.entity.study)
                by.setdefault(value.file_sha256, set()).add(entity.label if entity is not None else value.entity.study)
        for row in delivery_review.subjects(ws, reader=reader):
            if row["subject_type"] != "compound" and delivery_review.is_blinded(reader, row["subject_type"], row["subject"], hidden):
                name = f"{row['subject_type']}:{blinding.study_key(row['label'])}"
                names.add(name)
                groups.update(row["legacy_groups"])
                reason = (hidden_why.get(row["subject"]) if row["subject_type"] == "study"
                          else "it holds the values of a blinded study")
                if reason:
                    why[name] = reason
                    why.update({gid: reason for gid in row["legacy_groups"]})
    return BlindedSources(groups=frozenset(groups), names=frozenset(names), files=frozenset(files),
                          sheets={sha: frozenset(on) for sha, on in sheets.items()},
                          by={sha: frozenset(found) for sha, found in by.items()}, why=why, listed=listed_why)
