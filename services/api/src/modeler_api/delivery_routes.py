"""The Delivery section: review by exception (contracts 2026-11-12 §8.10, §6.6; plan §7.8, G6).

What the intake pipeline read from the client's files, exceptions first: the coverage of every file, the "study not
stated" values, a card per study, per product and for the compound, the source beside every value, the mappings that
wait for a person, the spot check, and the signed confirmation that lands a subject's values in the project.

Not a router: module-level handlers and `mount(router)`, which `client_api` calls with its own router, so the routes
are that router's (the response ratchet covers them) and no router imports a router. This module imports no
`modeler_api` module that defines one.

Every handler: `workspace_for`, the role of its row, a response model of `views/delivery.py`, `envelope(...)`. With the
pipeline off (`legacy`) the page answers `enabled: false` and every other route answers 409 and does nothing.

**One ledger per request, and blinding in one place.** A request builds one `_Scope`: the workspace, ONE `Ledger` (a
view that also writes), the brief, the data plan and the blinded studies (`intake_review.blinded_subjects`). Every value
a route answers with is a row of `_Scope.rows` (`intake_review.shown`: a blinded study's value, verbatim, spread,
interval, LLOQ, ULOQ and whether it is below the LLOQ are withheld), every card, draw and confirmation takes the
scope's `blinded(...)`, a value's source is `intake_review.source_view` with the scope's blinded studies, and a file
that holds a blinded study's values shows no caption, no outside text and no table body. `bound_record`,
`plan_landing` and a stored confirmation's record hold a blinded study's values: no answer is built from them for a
blinded subject.

**Ids and anchors** from a request pass `anchors.check_id` / `parse_anchor` / `parse_locator` before use, and an anchor
resolves only for a file with a `FileRecord` in this project (§5: no path is built from input).

**The confirmation** (decision E): an interrupted landing completes with no new signature; a record already confirmed
is not signed twice; else every refusal is checked (`prepare_confirmation`: 409 with the blockers, nothing signed),
then the step-up (403 `STEP_UP_REQUIRED`), the signature (from the token's step-up, never a password), the
confirmation's line and the landing. Events: `signature.create`, `intake.confirm`, `intake.land`.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, Field, ValidationError

from modeler_api import agent_jobs, intake_pipeline_jobs, jobs
from modeler_api.auth import ensure_step_up
from modeler_api.compliance.signatures import SignatureMeaning, Signer, sign_after_step_up
from modeler_api.config import SettingsDep
from modeler_api.deps import Reader, StoreDep, Writer, model_risk, project_record, workspace_for
from modeler_api.part11 import record_signature
from modeler_api.responses import answers, envelope
from modeler_api.views.client_data import TriageStart
from modeler_api.views.delivery import (
    DeliveryMapping,
    DeliveryPage,
    DeliverySource,
    DeliverySpotCheck,
    DeliverySubject,
    SubjectKind,
)
from modeler_intake.anchors import AnchorError, check_id, parse_anchor, parse_locator, sha256_of
from modeler_intake.mapping.fingerprint import layout_fingerprint
from modeler_intake.mapping.redact import redact
from modeler_intake.mapping.validate import validate_spec
from modeler_intake.mapping_spec import MappingSpec
from modeler_intake.source import region_grid
from modeler_intake.source_model import RegionGrid, SourceDocument
from modeler_project import ArtifactKind, Workspace, intake_files, intake_landing, intake_pipeline
from modeler_project import intake_review as review
from modeler_project.brief import ProjectBrief
from modeler_project.client_data import ClientDataError

# which outside items a coverage summary counts: no public function says it per item (reported to the integrator)
from modeler_project.coverage import _counts as outside_item_counts
from modeler_project.coverage import _Places as places_of
from modeler_project.datasets import DatasetError
from modeler_project.documents import DocumentLibrary
from modeler_project.evidence import EvidenceState
from modeler_project.inputs import current_cpf, refresh_inputs
from modeler_project.intake_checks import SETTLED_BY_RECORD
from modeler_project.intake_records import (
    FileCoverage,
    FileRecord,
    MappingDecision,
    MappingEntry,
    RegionDecision,
    RequirementDisposition,
    RunRecord,
    SpotTick,
)
from modeler_project.intake_rules import RULES_SHA256, RULES_STATUS, RULES_VERSION
from modeler_project.intake_store import IntakeStore
from modeler_project.ledger import Ledger
from modeler_project.ledger_models import EntityRef, ValueState
from modeler_project.ledger_view import in_subject, is_compound_field
from modeler_project.mapping_cache import MappingCache
from modeler_project.requirements import RequirementMatrix
from modeler_project.study_requirements import product_requirements, request_lines, requirement_status
from modeler_project.study_routing import subject_values

PREFIX = "/projects/{project_id}/delivery"
OFF = ("the intake pipeline is off for this deployment (MODELER_INTAKE_PIPELINE=legacy): the Delivery section shows "
       "nothing and does nothing")
_WAITING = ("queued", "running")
_DIGIT = re.compile(r"\d")
_STATUS = {"UNKNOWN": 404, "INVALID": 422, "CONFLICT": 409, "BLINDED": 409, "STALE": 409}
_ENTITY_ROLES = ("study", "arm", "product", "batch", "analyte")
_LABEL_ROLES = ("subject", "period", "sequence", "occasion", "vessel", "matrix")
_SEVERITY = {"fail": 0, "warn": 1, "info": 2}
_REQUIREMENT = {"missing": 0, "conflicting": 1, "ask_client": 2, "literature": 3, "not_needed": 4, "found": 5,
                "not_applicable": 6}
SubjectType = Annotated[SubjectKind, Path(alias="type")]


# --- refusals ---------------------------------------------------------------------------------------------------------


def _refused(status: int, code: str, message: str, **more: Any) -> HTTPException:
    """A refusal with a code the web app reads (`detail.code`), as the step-up's 403 has one."""
    return HTTPException(status_code=status, detail={"code": code, "message": message, **more})


def _blocked(exc: review.ConfirmationRefused) -> HTTPException:
    """409 for a confirmation the blockers refuse: `BLINDED` for a blinded subject, the blockers' one code when they
    share it, else `CONFIRMATION_REFUSED`; every blocker is in `detail.blockers`."""
    codes = list(dict.fromkeys(b.code for b in exc.blockers))
    code = "BLINDED" if "BLINDED" in codes else codes[0] if len(codes) == 1 else "CONFIRMATION_REFUSED"
    return _refused(409, code, str(exc), blockers=[_blocker(b) for b in exc.blockers])


@contextmanager
def _refusals() -> Iterator[None]:
    """What the review, the ledger and the landing refuse, as an HTTP answer with its code."""
    try:
        yield
    except HTTPException:
        raise
    except review.ConfirmationRefused as exc:
        raise _blocked(exc) from exc
    except review.ReviewError as exc:
        raise _refused(_STATUS[exc.code], exc.code, str(exc)) from exc
    except AnchorError as exc:
        raise _refused(422, "INVALID", str(exc)) from exc
    except intake_landing.LandingError as exc:
        raise _refused(409, "LANDING_REFUSED", str(exc)) from exc
    except (ClientDataError, DatasetError) as exc:
        raise _refused(409, "LANDING_REFUSED", str(exc)) from exc
    except ValidationError as exc:
        raise _refused(422, "INVALID", "; ".join(str(e["msg"]) for e in exc.errors()[:3])) from exc
    except KeyError as exc:
        raise _refused(404, "UNKNOWN", f"no {str(exc).strip(chr(39))} in this project's ledger") from exc
    except ValueError as exc:
        raise _refused(422, "INVALID", str(exc)) from exc


def _value_id(text: str) -> str:
    """A value's id from a request: a fact ("f-41") or the i-th value of an extract ("tx-...#3")."""
    if text.startswith("tx-"):
        return check_id("value", text)
    if not check_id("line", text).startswith("f-"):
        raise AnchorError(f"not a value's id: {text!r}")
    return text


def _target_id(text: str) -> str:
    """A target of an assignment: a value's id, or an extract's (every value of that table)."""
    return check_id("extract", text) if text.startswith("tx-") and "#" not in text else _value_id(text)


def _subject_id(subject_type: str, subject: str) -> str:
    """The subject of a path, checked before use: "compound", or a line id of the ledger (st-n, pr-n)."""
    if subject_type == "compound":
        if subject != intake_landing.COMPOUND:
            raise _refused(404, "UNKNOWN", "the compound's subject id is \"compound\"")
        return subject
    return check_id("line", subject)


# --- the request's scope: one ledger, and what D-15 withholds --------------------------------------------------------------


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _mol_weight(ws: Workspace) -> float | None:
    """The compound's molecular weight as the project's CPF has it (for the unit checks and the landing); None: none."""
    cpf = current_cpf(ws)
    found = cpf.get("phys.mw") if cpf is not None else None
    return _number(found.numeric_value) if found is not None else None


class _Scope:
    """One request's view of a project's delivery (the module docstring): the one place a value, a card, a draw or a
    source view is taken from, so no route can forget what a blinded study withholds."""

    def __init__(self, ws: Workspace):
        self.ws = ws
        self.store = IntakeStore(ws)
        self.reader = Ledger(ws)
        brief = ws.latest(ArtifactKind.BRIEF, "main")
        matrix = ws.latest(ArtifactKind.REQUIREMENTS, "main")
        self.brief = ProjectBrief.from_content(brief.content) if brief is not None else None
        self.matrix = RequirementMatrix.from_content(matrix.content) if matrix is not None else None
        self.mol_weight = _mol_weight(ws)
        self._project, self._risk = project_record(ws), model_risk(ws)
        self.hidden: set[str] = set()
        self.refresh()

    def refresh(self) -> None:
        """After a write: fold the ledger again, and read again which studies are blinded (an entered purpose, a
        landed dataset or a signed MAP changes it)."""
        self.reader.refresh()
        self.hidden = review.blinded_subjects(self.ws, self._project, self._risk)
        self._names: dict[str, str] | None = None
        self._runs: dict[str, RunRecord] | None = None
        self._entries: dict[tuple[str, int], MappingEntry] | None = None
        self._decisions: dict[tuple[str, int], list[MappingDecision]] = {}
        self._coverage: dict[str, FileCoverage | None] = {}
        self._blinded_files: set[str] | None = None

    # --- blinding (D-15) -------------------------------------------------------------------------------------------------

    @property
    def card_args(self) -> dict[str, Any]:
        return {"reader": self.reader, "brief": self.brief, "matrix": self.matrix, "mol_weight": self.mol_weight}

    def blinded(self, subject_type: str, subject: str) -> bool:
        """Whether the subject is blinded now (ReviewError UNKNOWN for a subject that is not one of the project's)."""
        return review.is_blinded(self.reader, subject_type, subject, self.hidden)  # type: ignore[arg-type]

    def rows(self, values: Iterable[ValueState | None]) -> list[dict[str, Any]]:
        """Values as an answer shows them: the ONLY way a value leaves this module."""
        return [self._row(value, blinded) for value, blinded in review.shown((v for v in values if v is not None), self.hidden)]

    def blinded_files(self) -> set[str]:
        """The files that hold a value of a blinded study (active or not): their captions, outside text and table
        bodies are not shown."""
        if self._blinded_files is None:
            self._blinded_files = {v.file_sha256 for v in self.reader.values(active=False)
                                   if v.file_sha256 and v.entity.study in self.hidden} if self.hidden else set()
        return self._blinded_files

    def card(self, subject_type: str, subject: str) -> Any:
        return review.card(self.ws, subject_type, subject, **self.card_args,  # type: ignore[arg-type]
                           blinded=self.blinded(subject_type, subject))

    def blockers(self, subject_type: str, subject: str) -> Any:
        return review.blockers(self.ws, subject_type, subject, **self.card_args,  # type: ignore[arg-type]
                               blinded=self.blinded(subject_type, subject))

    def spot_check(self, subject_type: str, subject: str) -> tuple[Any, Any]:
        return review.latest_spot_check(self.ws, subject_type, subject, reader=self.reader,  # type: ignore[arg-type]
                                        blinded=self.blinded(subject_type, subject))

    def source(self, *, value: str | None, anchor: str | None) -> tuple[Any, FileRecord, str | None, bool]:
        """A value's source view as the viewer may see it, and whether anything of it was withheld."""
        view, file, value_id = review.source_view(self.ws, reader=self.reader, hidden=self.hidden, value=value, anchor=anchor)
        if not self.hidden:
            return view, file, value_id, False
        plain, _file, _id = review.source_view(self.ws, reader=self.reader, hidden=(), value=value, anchor=anchor)
        return view, file, value_id, plain != view

    # --- what the views share ---------------------------------------------------------------------------------------------

    def label(self, entity_id: str | None) -> str | None:
        found = self.reader.entity(entity_id) if entity_id else None
        return found.label if found is not None else entity_id

    def file_name(self, sha256: str | None) -> str | None:
        if self._names is None:
            self._names = {}
            for record in intake_files.files(self.ws):
                self._names.setdefault(record.sha256, record.name)
        return self._names.get(sha256) if sha256 else None

    def latest_runs(self) -> dict[str, RunRecord]:
        """Each file's latest run (the last one queued for its bytes), by sha256."""
        if self._runs is None:
            self._runs = {}
            for run in intake_pipeline.runs(self.ws):
                self._runs[run.sha256] = run
        return self._runs

    def reading(self, sha256: str | None) -> bool:
        """Whether a run of the file waits or runs."""
        run = self.latest_runs().get(sha256 or "")
        return run is not None and run.state in _WAITING

    def coverage(self, sha256: str) -> FileCoverage | None:
        if sha256 not in self._coverage:
            self._coverage[sha256] = self.store.coverage(sha256)
        return self._coverage[sha256]

    def mapping_entries(self) -> dict[tuple[str, int], MappingEntry]:
        if self._entries is None:
            self._entries = {(e.mapping_id, e.version): e for e in MappingCache(self.ws).entries()}
            for line in self.store.mappings.entries("decision"):
                decision = MappingDecision.model_validate(line.body)
                self._decisions.setdefault((decision.mapping_id, decision.version), []).append(decision)
        return self._entries

    def mapping_status(self, mapping_id: str | None, version: int | None) -> str | None:
        """A version's status: its latest decision, "proposed" with none; None for no mapping."""
        if mapping_id is None or version is None or (mapping_id, version) not in self.mapping_entries():
            return None
        decisions = self._decisions.get((mapping_id, version))
        return decisions[-1].status if decisions else "proposed"

    def mapping_decisions(self, mapping_id: str, version: int) -> list[MappingDecision]:
        self.mapping_entries()
        return self._decisions.get((mapping_id, version), [])

    def source_document(self, sha256: str) -> SourceDocument | None:
        """The file's cached source model as its latest finished run parsed it; else the latest one cached."""
        versions = self.store.source_versions(sha256)
        if not versions:
            return None
        run = self.latest_runs().get(sha256)
        if run is not None and run.parser and run.parser_version and (run.parser, run.parser_version) in versions:
            return self.store.source(sha256, run.parser, run.parser_version)
        done = [r for r in intake_pipeline.runs(self.ws) if r.sha256 == sha256 and r.state == "done" and r.parser
                and r.parser_version and (r.parser, r.parser_version) in versions]
        if done:
            return self.store.source(sha256, done[-1].parser, done[-1].parser_version)  # type: ignore[arg-type]
        return self.store.source(sha256, *versions[-1])

    def _row(self, value: ValueState, blinded: bool) -> dict[str, Any]:
        entity = {role: found for role in _ENTITY_ROLES if (found := getattr(value.entity, role))}
        labels = {role: self.label(found) or found for role, found in entity.items()}
        labels.update({role: text for role in _LABEL_ROLES if (text := getattr(value.entity, role))})
        return {
            "id": value.id, "field": value.field, "value": value.value, "unit": value.unit,
            "verbatim": None if blinded else value.verbatim, "time": value.time, "time_unit": value.time_unit,
            "time_actual": value.time_actual, "statistic": value.statistic, "spread": value.spread,
            "spread_kind": value.spread_kind, "n_at": value.n_at,
            "interval": list(value.interval) if value.interval is not None else None,
            "interval_kind": value.interval_kind, "interval_level": value.interval_level,
            "censored": None if blinded else value.censored, "lloq": value.lloq, "lloq_unit": value.lloq_unit,
            "uloq": value.uloq, "conditions": dict(value.conditions), "labels": labels, "entity": entity,
            "method": value.method, "level": value.level, "status": value.status, "status_reason": value.status_reason,
            "superseded_by": value.superseded_by, "confirmation": value.confirmation,
            "mapping_id": value.mapping.mapping_id if value.mapping else None,
            "mapping_version": value.mapping.version if value.mapping else None,
            "derived_from": list(value.derived_from), "compute": value.compute, "cross_file": value.cross_file is not None,
            "table_kind": value.table_kind, "file_sha256": value.file_sha256, "file": self.file_name(value.file_sha256),
            "delivery": value.delivery, "anchor": value.anchor, "locators": dict(value.locators), "blinded": blinded}


def _on(ws: Workspace) -> bool:
    return intake_pipeline_jobs.enabled() and IntakeStore(ws).available


def _scope(project_id: str, principal: Any, store: Any) -> _Scope:
    """The request's scope; 409 when the pipeline is off (nothing is read or written then)."""
    ws = workspace_for(project_id, principal, store)
    if not _on(ws):
        raise _refused(409, "INTAKE_PIPELINE_OFF", OFF)
    return _Scope(ws)


# --- small views -------------------------------------------------------------------------------------------------------


def _rules() -> dict[str, str]:
    return {"version": RULES_VERSION, "status": RULES_STATUS, "sha256": RULES_SHA256}


def _blocker(blocker: Any) -> dict[str, Any]:
    return {"code": blocker.code, "detail": blocker.detail, "ids": list(blocker.ids)}


def _summary(summary: Any) -> dict[str, Any]:
    return {**summary.model_dump(mode="json"), "needs_ocr_pages": list(summary.needs_ocr_pages)}


def _mask(text: str) -> str:
    return _DIGIT.sub("•", text)


def _run(run: RunRecord, blinded: bool) -> dict[str, Any]:
    """A run as the page shows it. `blinded` (its file holds a blinded study's values): the digits of a failure's
    message are masked, since an error may quote the cell it stopped at."""
    def said(text: str, failed: bool) -> str:
        return _mask(text) if blinded and failed else text

    return {"run_id": run.run_id, "state": run.state, "attempt": run.attempt, "queued_at": run.queued_at,
            "started_at": run.started_at, "finished_at": run.finished_at, "by": run.by, "error": said(run.error, True),
            "stages": [{"stage": s.stage, "seconds": s.seconds, "ok": s.ok, "detail": said(s.detail, not s.ok)}
                       for s in run.stages]}


def _region_state(scope: _Scope, outcome: Any) -> str:
    """A region's state as the page shows it: `waiting` while its mapping is rejected and the coverage still shows the
    rejected reading (the run that follows the rejection has not finished: its earlier values are still active)."""
    mapping = outcome.mapping
    if outcome.state == "mapped" and mapping is not None \
            and scope.mapping_status(mapping.mapping_id, mapping.version) == "rejected":
        return "waiting"
    return outcome.state


def _regions(scope: _Scope, coverage: FileCoverage, blinded: bool) -> list[dict[str, Any]]:
    out = []
    for found in coverage.regions:
        region, outcome = found.region, found.outcome
        mapping = outcome.mapping
        state = _region_state(scope, outcome)
        out.append({
            "region_id": region.id, "kind": region.kind, "where": region.where,
            "caption": None if blinded else region.caption, "table_kind": region.table_kind, "state": state,
            "reason": _mask(outcome.reason) if blinded and outcome.state == "unread" else outcome.reason,
            "origin": outcome.origin, "mapping_id": mapping.mapping_id if mapping else None,
            "mapping_version": mapping.version if mapping else None,
            "mapping_status": scope.mapping_status(mapping.mapping_id, mapping.version) if mapping else None,
            "numeric_cells": found.numeric_cells, "used": found.used, "excluded": found.excluded,
            "silent": found.silent_count})
    return out


def _outside(coverage: FileCoverage, decisions: Sequence[RegionDecision], blinded: bool) -> list[dict[str, Any]]:
    """The items with a number outside every region (page furniture left out), each with whether the summary counts
    it (`coverage.file_coverage`'s own rule: not cited by a mapped table, not accepted by a person)."""
    cited = places_of(c for r in coverage.regions if r.outcome.state == "mapped" for c in r.outcome.cited)
    accepted = places_of(where for d in decisions if d.file_sha256 == coverage.file.sha256 and d.scope == "outside"
                         for where in d.regions)
    return [{"where": item.where, "text": None if blinded else item.text, "region": item.region,
             "counted": outside_item_counts(item, cited, accepted)}
            for item in coverage.outside if item.numeric and not item.furniture]


def _file(scope: _Scope, record: FileRecord, decisions: Sequence[RegionDecision]) -> dict[str, Any]:
    coverage = scope.coverage(record.sha256)
    run = scope.latest_runs().get(record.sha256)
    blinded = record.sha256 in scope.blinded_files()
    if run is not None and run.state in _WAITING:
        state, reason = "waiting", "queued for the intake pipeline" if run.state == "queued" else "being read"
    elif run is not None and run.state == "failed":
        state, reason = "failed", _mask(run.error) if blinded else run.error
    elif coverage is not None:
        state, reason = coverage.summary.state, coverage.summary.reason
    else:
        state, reason = "not_read", "no run has read this file"
    detail = coverage is not None and not record.repeat
    return {
        "file_id": record.file_id, "sha256": record.sha256, "name": record.name, "size_bytes": record.size_bytes,
        "delivery": record.delivery,
        "container": record.container.model_dump(mode="json") if record.container is not None else None,
        "repeat": record.repeat, "legacy_sid": record.legacy_sid, "legacy_refusal": record.legacy_refusal,
        "by": record.by, "at": record.at, "state": state, "reason": reason,
        "coverage": _summary(coverage.summary) if coverage is not None else None,
        "run": _run(run, blinded) if run is not None else None,
        "regions": _regions(scope, coverage, blinded) if detail else [],      # type: ignore[arg-type]
        "outside": _outside(coverage, decisions, blinded) if detail else [],  # type: ignore[arg-type]
        "blinded": blinded}


def _mapping_uses(scope: _Scope) -> dict[tuple[str, int], list[dict[str, Any]]]:
    """Where each mapping version is in use now: the regions whose stored outcome names it."""
    uses: dict[tuple[str, int], list[dict[str, Any]]] = {}
    seen: set[str] = set()
    for record in intake_files.files(scope.ws):
        if record.sha256 in seen:
            continue
        seen.add(record.sha256)
        coverage = scope.coverage(record.sha256)
        for found in (coverage.regions if coverage is not None else ()):
            mapping = found.outcome.mapping
            if mapping is not None:
                uses.setdefault((mapping.mapping_id, mapping.version), []).append({
                    "file_sha256": record.sha256, "file": record.name, "region_id": found.region.id,
                    "where": found.region.where, "version": mapping.version, "state": _region_state(scope, found.outcome)})
    return uses


def _mapping_row(scope: _Scope, entry: MappingEntry, uses: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {"mapping_id": entry.mapping_id, "version": entry.version,
            "status": scope.mapping_status(entry.mapping_id, entry.version), "origin": entry.origin,
            "origin_detail": entry.origin_detail, "kind": entry.spec.kind, "by": entry.by, "at": entry.at,
            "used_in": list(uses), "waiting": any(scope.reading(use["file_sha256"]) for use in uses)}


def _waiting_mappings(scope: _Scope, only: set[tuple[str, int]] | None = None) -> list[dict[str, Any]]:
    """The mapping versions that wait for a person: proposed and in use (or a person's version not read with yet), and
    rejected ones whose table still shows the rejected reading. `only`: among these versions (a subject's)."""
    uses = _mapping_uses(scope)
    out = []
    for key, entry in sorted(scope.mapping_entries().items()):
        status = scope.mapping_status(*key)
        used = uses.get(key, [])
        if only is not None:
            if key not in only or status == "approved":
                continue
        elif not ((status == "proposed" and (used or entry.origin == "person"))
                  or (status == "rejected" and any(use["state"] == "waiting" for use in used))):
            continue
        out.append(_mapping_row(scope, entry, used))
    return out


# --- the page ---------------------------------------------------------------------------------------------------------


def _empty_page(enabled: bool) -> dict[str, Any]:
    return {"enabled": enabled, "running": False, "agents": agent_jobs.agents_status("A4"), "deliveries": [],
            "totals": {"files": 0, "files_by_state": {}, "regions": 0, "regions_mapped": 0, "regions_excluded": 0,
                       "regions_unread": 0, "silent_loss": 0, "outside_numeric": 0, "values_unassigned": 0,
                       "anchors_unresolved": 0, "needs_ocr_pages": 0, "values": 0},
            "subjects": [], "unassigned": [], "mappings": [], "request": [], "rules": _rules()}


def _request_lines(scope: _Scope) -> list[dict[str, Any]]:
    """One line of the client request per study or product item still to ask for (`study_requirements.request_lines`)."""
    reader = scope.reader
    dispositions = [RequirementDisposition.model_validate(e.body) for e in scope.store.review.entries("disposition")]
    statuses: list[Any] = []
    labels: dict[str, str] = {}
    for study in reader.entities("study"):
        if reader.values(study=study.id):
            labels[study.id] = study.label
            statuses += requirement_status(reader, study.id, brief=scope.brief, matrix=scope.matrix,
                                           dispositions=dispositions).items
    for product in reader.entities("product"):
        if reader.values(product=product.id):
            labels[product.id] = product.label
            statuses += product_requirements(reader, product.id, brief=scope.brief, matrix=scope.matrix,
                                             dispositions=dispositions)
    return [{"req_id": line.req_id, "what": line.what, "why": line.why, "required": line.required,
             "product": line.product, "sheet": line.sheet} for line in request_lines(statuses, labels=labels)]


def _page(scope: _Scope) -> dict[str, Any]:
    ws, reader = scope.ws, scope.reader
    decisions = [RegionDecision.model_validate(e.body) for e in scope.store.review.entries("region")]
    records = intake_files.files(ws)
    deliveries = [{"id": str(d.get("id")), "by": str(d.get("by", "")), "at": str(d.get("at", "")),
                   "files": [_file(scope, r, decisions) for r in records if r.delivery == d.get("id")]}
                  for d in intake_files.deliveries(ws)]
    first: dict[str, dict[str, Any]] = {}
    for delivery in deliveries:
        for file in delivery["files"]:
            first.setdefault(file["sha256"], file)
    covered = [f["coverage"] for f in first.values() if f["coverage"] is not None]
    totals = {
        "files": len(first), "files_by_state": dict(sorted(Counter(f["state"] for f in first.values()).items())),
        **{name: sum(c[name] for c in covered) for name in ("regions", "regions_mapped", "regions_excluded",
                                                             "regions_unread", "silent_loss", "outside_numeric",
                                                             "values_unassigned", "anchors_unresolved")},
        "needs_ocr_pages": sum(len(c["needs_ocr_pages"]) for c in covered), "values": len(reader.values())}
    arms: dict[str, list[dict[str, str]]] = {}
    for kind in ("arm", "batch"):
        for entity in reader.entities(kind):  # type: ignore[arg-type]
            parent = reader.entity(entity.parent) if entity.parent else None
            if parent is not None:
                arms.setdefault(parent.id, []).append({"id": entity.id, "label": entity.label})
    subjects = []
    for row in review.subjects(ws, reader=reader):
        children = arms.get(row["subject"], [])
        subjects.append({**row, "arms": children if row["subject_type"] == "study" else [],
                         "batches": children if row["subject_type"] == "product" else [],
                         "blinded": scope.blinded(row["subject_type"], row["subject"])})
    running = jobs.running(ws.store, ws.tenant_id, ws.project_id, "intake") or intake_pipeline.unfinished(ws)
    return {"enabled": True, "running": running, "agents": agent_jobs.agents_status("A4"), "deliveries": deliveries,
            "totals": totals, "subjects": subjects, "unassigned": scope.rows(review.unassigned(ws, reader=reader)),
            "mappings": _waiting_mappings(scope), "request": _request_lines(scope), "rules": _rules()}


def get_delivery(project_id: str, principal: Reader, store: StoreDep) -> dict[str, Any]:
    """The Delivery section's page: every delivery with its files and their coverage, the subjects to review, the
    "study not stated" values, the mappings that wait and the client request. Looking at it queues the client files
    stored before the pipeline ran and starts the intake job when a run waits. Poll while `running`."""
    ws = workspace_for(project_id, principal, store)
    if not _on(ws):
        return envelope(_empty_page(enabled=False))
    intake_pipeline_jobs.sweep(store, principal.tenant_id, project_id, by=principal.user_id)
    intake_pipeline_jobs.kick(store, principal.tenant_id, project_id, by=principal.user_id)
    with _refusals():
        return envelope(_page(_Scope(ws)))


class DeliveryRun(BaseModel):
    files: list[str] = Field(default_factory=list)      # sha256s; none named: every file of the project


def run_delivery(project_id: str, principal: Writer, store: StoreDep, body: DeliveryRun | None = None) -> dict[str, Any]:
    """Read files again (all of them, or the ones named by sha256): each is queued as a new run, behind the runs that
    wait. "RUNNING" when the intake job runs now, "QUEUED" when the runs wait for it."""
    scope = _scope(project_id, principal, store)
    with _refusals():
        wanted = [check_id("sha256", sha) for sha in (body.files if body else [])]
        records = _run_records(scope)
        unknown = [sha for sha in wanted if sha not in records]
        if unknown:
            raise _refused(404, "UNKNOWN", f"{len(unknown)} of the files named did not arrive in this project")
        chosen = [records[sha] for sha in (wanted or records)]
        if not chosen:
            raise _refused(409, "CONFLICT", "no file has arrived in this project yet")
        intake_pipeline.enqueue(scope.ws, chosen, by=principal.user_id, again=True)
    return envelope({"status": _kick(scope, principal, store)})


def _run_records(scope: _Scope) -> dict[str, FileRecord]:
    """The record a new run of each file is queued with, by sha256: the one of the delivery its latest run read it in
    (so what the run reads stays in that delivery), else its first."""
    by_sha: dict[str, list[FileRecord]] = {}
    for record in intake_files.files(scope.ws):
        by_sha.setdefault(record.sha256, []).append(record)
    out = {}
    for sha, records in by_sha.items():
        run = scope.latest_runs().get(sha)
        out[sha] = next((r for r in records if run is not None and r.delivery == run.delivery), records[0])
    return out


def _kick(scope: _Scope, principal: Any, store: Any) -> str:
    ws = scope.ws
    started = intake_pipeline_jobs.kick(store, ws.tenant_id, ws.project_id, by=principal.user_id)
    return "RUNNING" if started or jobs.running(ws.store, ws.tenant_id, ws.project_id, "intake") else "QUEUED"


# --- a subject's card ------------------------------------------------------------------------------------------------------


def _tables(scope: _Scope, values: Sequence[ValueState]) -> list[dict[str, Any]]:
    """The subject's values grouped by the table they were read from (an extract), its scalar facts per file."""
    extracts = {str(e.body.get("id")): e.body for e in scope.store.facts.entries("extract")}
    groups: dict[str, dict[str, Any]] = {}
    for value, row in zip(values, scope.rows(values), strict=True):
        if value.id.startswith("tx-"):
            key = value.id.split("#")[0]
            ref = extracts.get(key, {})
            mapping = value.mapping
            status = scope.mapping_status(mapping.mapping_id, mapping.version) if mapping else None
            base = {"id": key, "kind": "table", "file_sha256": value.file_sha256, "file": scope.file_name(value.file_sha256),
                    "region_id": ref.get("region_id"), "table_kind": value.table_kind,
                    "mapping_id": mapping.mapping_id if mapping else None,
                    "mapping_version": mapping.version if mapping else None, "mapping_status": status,
                    "waiting": scope.reading(value.file_sha256)}
        else:
            key = f"facts:{intake_files.file_id_of(value.file_sha256)}" if value.file_sha256 else "facts:entered"
            base = {"id": key, "kind": "facts", "file_sha256": value.file_sha256, "file": scope.file_name(value.file_sha256),
                    "region_id": None, "table_kind": None, "mapping_id": None, "mapping_version": None,
                    "mapping_status": None, "waiting": scope.reading(value.file_sha256)}
        groups.setdefault(key, {**base, "values": []})["values"].append(row)
    return list(groups.values())


def _confirmation(scope: _Scope, subject_type: str, subject: str, blinded: bool) -> dict[str, Any] | None:
    """The subject's current confirmation: who signed what, and what its record says of the rules, the coverage and
    what was held back. Its record holds the values: none is copied here, and nothing of a blinded subject's list."""
    found = review.current_confirmation(scope.ws, subject_type, subject, reader=scope.reader)  # type: ignore[arg-type]
    if found is None:
        return None
    record = found.record
    done = review.landed(scope.ws, found.id)
    rules = record.get("rules") if isinstance(record.get("rules"), dict) else None
    coverage = record.get("coverage") if isinstance(record.get("coverage"), dict) else {}
    return {
        "id": found.id, "at": found.at, "by": found.by, "printed_name": found.printed_name,
        "signature_id": found.signature_id, "manifestation": found.manifestation, "record_sha256": found.record_sha256,
        "supersedes": found.supersedes,
        "current": record.get("subject_digest") == intake_landing.subject_digest(scope.reader, subject_type, subject),
        "rules": {k: str(rules.get(k, "")) for k in ("version", "status", "sha256")} if rules else None,
        "coverage": {str(k): int(v) for k, v in coverage.items() if isinstance(v, int) and not isinstance(v, bool)},
        "held": None if blinded else [str(text) for text in record.get("held", ())],
        "landed": None if done is None else {
            "datasets": list(done.datasets), "evidence": list(done.evidence), "dissolution_records": done.dissolution_records,
            "rejected_legacy": list(done.rejected_legacy), "pending": None if blinded else list(done.pending), "at": done.at}}


def _wanted(draw: Any, record: Any) -> list[str]:
    """The values the one submit of ticks must name: always and sampled, minus carried, minus the values whose tick
    failed in an earlier draw; none once the ticks are recorded."""
    if draw is None or record is not None:
        return []
    return [vid for vid in (*draw.always, *draw.sampled)
            if vid not in draw.carried and draw.strata.get(vid) != review.FAILED_TICK]


def _subject_view(scope: _Scope, subject_type: str, subject: str, *, signature: dict[str, str] | None = None) -> dict[str, Any]:
    ws, reader = scope.ws, scope.reader
    blinded = scope.blinded(subject_type, subject)
    card = scope.card(subject_type, subject)
    subject = card.subject
    values = subject_values(reader, subject_type, subject)  # type: ignore[arg-type]
    held: list[str] | None = None
    problem: str | None = None
    if not blinded:           # the plan holds the values: nothing of it is shown for a blinded subject
        try:
            held = list(intake_landing.plan_landing(ws, DocumentLibrary(ws), subject_type, subject,  # type: ignore[arg-type]
                                                    reader=reader, matrix=scope.matrix, mol_weight=scope.mol_weight).held)
        except intake_landing.LandingError as exc:
            held, problem = [], str(exc)
    state = review.spot_check_state(ws, subject_type, subject, reader=reader)  # type: ignore[arg-type]
    draw, record = scope.spot_check(subject_type, subject)
    wanted = [] if blinded or state == "stale" else _wanted(draw, record)
    checks = sorted(card.checks, key=lambda c: (c.id in card.overridden, _SEVERITY.get(c.severity, 9)))
    elsewhere = [d.id for d in intake_landing.legacy_overlap(ws, subject_type, subject, reader=reader)  # type: ignore[arg-type]
                 if d.state is not EvidenceState.REJECTED]
    used = {(v.mapping.mapping_id, v.mapping.version) for v in values if v.mapping is not None}
    view = {
        "subject_type": subject_type, "subject": subject, "label": card.label, "blinded": blinded,
        "confirm_on": review.confirm_on(ws, values), "loaded_elsewhere": elsewhere, "values": card.values,
        "by_level": dict(card.by_level), "by_method": dict(card.by_method), "silent_loss": card.silent_loss,
        "coverage": [_summary(c) for c in card.coverage],
        "blockers": [_blocker(b) for b in scope.blockers(subject_type, subject)],
        "gaps": [{"study": g.study, "tag": g.tag, "value": g.value, "reason": g.reason} for g in card.gaps],
        # a check's message may quote a value or count the values below the LLOQ: not shown for a blinded subject
        "checks": [{"id": c.id, "code": c.code, "severity": c.severity, "message": None if blinded else c.message,
                    "values": list(c.values), "rule": c.rule, "overridden": c.id in card.overridden} for c in checks],
        "conflicts": [{"id": c.id, "field": c.field, "time": c.time, "kind": c.kind, "values": list(c.values),
                       "labels": next((row["labels"] for row in scope.rows(reader.value(v) for v in c.values[:1])), {})}
                      for c in card.conflicts],
        "links": [{"id": link.id, "link_fact": link.link_fact, "study": link.study, "study_label": scope.label(link.study),
                   "file_sha256": link.file_sha256, "file": scope.file_name(link.file_sha256) or link.file_sha256[:12],
                   "values": link.values, "state": link.state,
                   "candidates": [{"id": c, "label": scope.label(c) or c} for c in link.candidates]} for link in card.links],
        "requirements": [{"req_id": r.req_id, "template": r.template, "label": r.label, "scope": r.scope,
                          "criticality": r.criticality, "applies": r.applies, "status": r.status, "values": list(r.values),
                          "disposition": r.disposition}
                         for r in sorted(card.requirements, key=lambda r: _REQUIREMENT.get(r.status, 9))],
        "mappings": _waiting_mappings(scope, only=used), "tables": _tables(scope, values), "held": held,
        "landing_problem": problem,
        "spot_check": {"state": state, "draw_id": draw.id if draw is not None else None,
                       "drawn": len({*draw.always, *draw.sampled}) if draw is not None else 0, "wanted": len(wanted)},
        "confirmation": _confirmation(scope, subject_type, subject, blinded), "rules": _rules()}
    if signature is not None:
        view["signature"] = signature
    return view


def get_subject(project_id: str, subject_type: SubjectType, subject: str, principal: Reader, store: StoreDep) -> dict[str, Any]:
    """A subject's card, exceptions first: its blockers, schema gaps, checks, conflicts, cross-file links, missing
    items and new mappings; then its values by table, what the landing would hold back, the spot check's state and
    its confirmation with the signature's manifestation."""
    scope = _scope(project_id, principal, store)
    with _refusals():
        return envelope(_subject_view(scope, subject_type, _subject_id(subject_type, subject)))


# --- a person's decisions on a card ------------------------------------------------------------------------------------------


class DeliveryOverride(BaseModel):
    check_id: str
    why: str = Field(min_length=1)


class DeliveryDisposition(BaseModel):
    req_id: str
    disposition: Literal["ask_client", "literature", "not_needed"]
    why: str = Field(min_length=1)


class DeliveryChoice(BaseModel):
    conflict_id: str
    keep: str                               # the value kept; the others that read differently are excluded
    why: str = Field(min_length=1)


class DeliveryLinkDecision(BaseModel):
    file_sha256: str
    confirmed: bool
    link_fact: str | None = None
    study: str | None = None                # an ambiguous link: the candidate study chosen (default: the card's study)
    why: str = ""                           # required to refuse


class DeliveryEntry(BaseModel):
    """A person's entry or correction of one value of the subject. `supersedes`: the value corrected (the new one
    inherits its place in the series unless given). `arm`, `analyte`, `batch` are the ledger's entity ids."""

    field: str | None = None
    value: float | int | str | bool | None
    unit: str | None = None
    time: float | None = None
    time_unit: str | None = None
    statistic: str | None = None
    spread: float | None = None
    spread_kind: str | None = None
    n: int | None = None
    conditions: dict[str, str] | None = None
    censored: bool | None = None
    lloq: float | None = None
    lloq_unit: str | None = None
    supersedes: str | None = None
    arm: str | None = None
    analyte: str | None = None
    batch: str | None = None
    labels: dict[Literal["subject", "period", "sequence", "occasion", "vessel", "matrix"], str] = Field(default_factory=dict)
    why: str = Field(min_length=1)


def _decided(scope: _Scope, subject_type: str, subject: str) -> dict[str, Any]:
    """The card after a decision: the ledger folded again, the blinded studies read again."""
    scope.refresh()
    return envelope(_subject_view(scope, subject_type, subject))


def override_check(project_id: str, subject_type: SubjectType, subject: str, body: DeliveryOverride, principal: Writer,
                   store: StoreDep) -> dict[str, Any]:
    """Clear a failed check of the subject with a reason. A missing required item is settled by a disposition and an
    open conflict by a choice, never by an override."""
    scope = _scope(project_id, principal, store)
    with _refusals():
        subject = _subject_id(subject_type, subject)
        check_id("check", body.check_id)
        check = next((c for c in scope.card(subject_type, subject).checks if c.id == body.check_id), None)
        if check is None:
            raise _refused(404, "UNKNOWN", f"no check {body.check_id} on this subject's card")
        if check.code in SETTLED_BY_RECORD:
            raise _refused(409, "CONFLICT", f"{check.code} is settled by a disposition of the item or a choice between "
                                            "the values, not by an override")
        review.override(scope.ws, subject=subject, check_id=body.check_id, why=body.why, by=principal.user_id)
        return _decided(scope, subject_type, subject)


def dispose_requirement(project_id: str, subject_type: SubjectType, subject: str, body: DeliveryDisposition,
                        principal: Writer, store: StoreDep) -> dict[str, Any]:
    """A requirement item of the subject that is missing: ask the client, take it from literature, or not needed."""
    scope = _scope(project_id, principal, store)
    with _refusals():
        subject = _subject_id(subject_type, subject)
        if body.req_id not in {r.req_id for r in scope.card(subject_type, subject).requirements}:
            raise _refused(404, "UNKNOWN", f"no requirement item {body.req_id!r} on this subject's card")
        review.dispose(scope.ws, subject=subject, req_id=body.req_id, disposition=body.disposition, why=body.why,
                       by=principal.user_id)
        return _decided(scope, subject_type, subject)


def choose_value(project_id: str, subject_type: SubjectType, subject: str, body: DeliveryChoice, principal: Writer,
                 store: StoreDep) -> dict[str, Any]:
    """Settle an open conflict of the subject: the value kept stays, the others that read differently are excluded."""
    scope = _scope(project_id, principal, store)
    with _refusals():
        subject = _subject_id(subject_type, subject)
        check_id("conflict", body.conflict_id)
        keep = _value_id(body.keep)
        if body.conflict_id not in {c.id for c in scope.card(subject_type, subject).conflicts}:
            raise _refused(404, "UNKNOWN", f"no open conflict {body.conflict_id} on this subject's card")
        review.choose(scope.ws, conflict_id=body.conflict_id, keep=keep, why=body.why, by=principal.user_id)
        return _decided(scope, subject_type, subject)


def decide_link(project_id: str, subject_type: SubjectType, subject: str, body: DeliveryLinkDecision, principal: Writer,
                store: StoreDep) -> dict[str, Any]:
    """Confirm or refuse a cross-file link of the study, per file; for an ambiguous link, `study` is the candidate
    chosen (the file's own study is merged into it)."""
    scope = _scope(project_id, principal, store)
    with _refusals():
        subject = _subject_id(subject_type, subject)
        if subject_type != "study":
            raise _refused(422, "INVALID", "a cross-file link joins a file's values to a study")
        check_id("sha256", body.file_sha256)
        if body.link_fact is not None:
            _value_id(body.link_fact)
        target = resolved = scope.card(subject_type, subject).subject
        if body.study is not None and check_id("line", body.study) != subject:
            links = [link for link in scope.reader.pending_links(study=resolved) if link.file_sha256 == body.file_sha256]
            found = scope.reader.entity(body.study)
            if found is None or found.id not in {c for link in links for c in link.candidates}:
                raise _refused(422, "INVALID", f"{body.study} is not one of the studies a link of this study and that "
                                               "file names")
            target = found.id
        # the review refuses a file with no link to this study (and no earlier decision on one): 404
        review.confirm_link(scope.ws, link_fact=body.link_fact, study=target, file_sha256=body.file_sha256,
                            confirmed=body.confirmed, why=body.why, by=principal.user_id)
        return _decided(scope, subject_type, subject)


def _entity_of(scope: _Scope, entity_id: str, kind: str, parent: str | None = None) -> str:
    found = scope.reader.entity(check_id("line", entity_id))
    if found is None or found.type != kind:
        raise _refused(404, "UNKNOWN", f"no {kind} {entity_id!r} in this project's ledger")
    if parent is not None:
        owner = scope.reader.entity(found.parent) if found.parent else None
        if owner is None or owner.id != parent:
            raise _refused(422, "INVALID", f"{kind} {found.label} is not one of this subject's")
    return found.id


def enter_value(project_id: str, subject_type: SubjectType, subject: str, body: DeliveryEntry, principal: Writer,
                store: StoreDep) -> dict[str, Any]:
    """A person's entry or correction of a value of the subject, with the reason (method "person": no source, the
    confirmation's signature binds it). The facts code derives from it follow."""
    scope = _scope(project_id, principal, store)
    with _refusals():
        subject = scope.card(subject_type, _subject_id(subject_type, subject)).subject
        old = None
        if body.supersedes is not None:
            old = scope.reader.value(_value_id(body.supersedes))
            if old is None or not in_subject(old.entity, old.field, subject_type, subject):
                raise _refused(404, "UNKNOWN", f"no value {body.supersedes} on this subject's card")
        field = body.field if body.field is not None else old.field if old is not None else None
        if subject_type == "compound" and (field is None or not is_compound_field(field)):
            raise _refused(422, "INVALID", f"{field!r} is not a compound-level field")
        parts: dict[str, Any] = {role: text for role, text in body.labels.items() if text.strip()}
        if body.analyte is not None:
            parts["analyte"] = _entity_of(scope, body.analyte, "analyte")
        if body.arm is not None:
            if subject_type != "study":
                raise _refused(422, "INVALID", "an arm is a study's")
            parts["arm"] = _entity_of(scope, body.arm, "arm", subject)
        if body.batch is not None:
            if subject_type != "product":
                raise _refused(422, "INVALID", "a batch is entered on its product's card")
            parts["batch"] = _entity_of(scope, body.batch, "batch", subject)
        entity: EntityRef | None = None
        if old is None or parts:
            base = old.entity if old is not None else EntityRef(**({subject_type: subject} if subject_type != "compound" else {}))
            entity = base.model_copy(update=parts)
        scope.reader.enter(entity=entity, field=body.field, value=body.value, unit=body.unit, time=body.time,
                           time_unit=body.time_unit, statistic=body.statistic, spread=body.spread,  # type: ignore[arg-type]
                           spread_kind=body.spread_kind, n=body.n, conditions=body.conditions,  # type: ignore[arg-type]
                           censored=body.censored, lloq=body.lloq, lloq_unit=body.lloq_unit, why=body.why,
                           by=principal.user_id, supersedes=body.supersedes)
        scope.reader.derive()               # a dose entered in g gets its mg fact, as after an assignment
        return _decided(scope, subject_type, subject)


# --- the "study not stated" values, and what is not data ---------------------------------------------------------------------


class DeliveryAssignment(BaseModel):
    targets: list[str] = Field(min_length=1)          # value ids, or an extract's id (every value of that table)
    study: str | None = None
    arm: str | None = None
    product: str | None = None
    batch: str | None = None
    why: str = Field(min_length=1)


class DeliveryExclusion(BaseModel):
    file_sha256: str
    regions: list[str] = Field(min_length=1)          # region ids; with scope `outside`, the items' locators
    scope: Literal["regions", "unread_prose", "figures", "outside"] = "regions"
    why: str = Field(min_length=1)


def assign_values(project_id: str, body: DeliveryAssignment, principal: Writer, store: StoreDep) -> dict[str, Any]:
    """Give "study not stated" values their subject: a study (and its arm), a product (and its batch), or both."""
    scope = _scope(project_id, principal, store)
    with _refusals():
        targets = [_target_id(target) for target in body.targets]
        for entity_id in (body.study, body.arm, body.product, body.batch):
            if entity_id is not None:
                check_id("line", entity_id)
        review.assign(scope.ws, targets=targets, study=body.study, arm=body.arm, product=body.product, batch=body.batch,
                      why=body.why, by=principal.user_id)
        scope.refresh()
        return envelope(_page(scope))


def exclude_regions(project_id: str, body: DeliveryExclusion, principal: Writer, store: StoreDep) -> dict[str, Any]:
    """A person's decision that regions of a file are not data (scope `regions`: any region, and what was read from
    it is set aside; `unread_prose`; `figures`), or that items outside every region are not (`outside`: their
    locators). The file's coverage is recomputed."""
    scope = _scope(project_id, principal, store)
    with _refusals():
        check_id("sha256", body.file_sha256)
        for text in body.regions:
            if body.scope == "outside":
                parse_locator(text)
            else:
                check_id("region", text)
        review.exclude_regions(scope.ws, file_sha256=body.file_sha256, regions=body.regions, scope=body.scope, why=body.why,
                               by=principal.user_id)
        scope.refresh()
        return envelope(_page(scope))


# --- the spot check ---------------------------------------------------------------------------------------------------------


class DeliveryTick(BaseModel):
    value_id: str
    ok: bool
    note: str = ""


class DeliveryTicks(BaseModel):
    draw_id: str
    ticks: list[DeliveryTick]


def _spot_view(scope: _Scope, subject_type: str, subject: str) -> dict[str, Any]:
    reader = scope.reader
    blinded = scope.blinded(subject_type, subject)
    card_subject = intake_landing.resolve_subject(reader, subject_type, subject)
    state = review.spot_check_state(scope.ws, subject_type, card_subject, reader=reader)  # type: ignore[arg-type]
    draw, record = scope.spot_check(subject_type, card_subject)
    wanted = [] if blinded or state == "stale" else _wanted(draw, record)
    ticks = {t.value_id: t for t in record.ticks} if record is not None else {}
    values = []
    for value_id in (dict.fromkeys((*draw.always, *draw.sampled)) if draw is not None else ()):
        found = reader.value(value_id)
        if found is None:
            continue
        (row,) = scope.rows([found])
        tick = ticks.get(value_id)
        values.append({"value": row, "reason": None if row["blinded"] else draw.strata.get(value_id),
                       "wanted": value_id in wanted, "carried_by": draw.carried.get(value_id),
                       "ok": tick.ok if tick is not None else None, "note": tick.note if tick is not None else "",
                       "inputs": scope.rows(reader.value(i) for i in found.derived_from)})
    return {
        "subject_type": subject_type, "subject": card_subject,
        "label": intake_landing.subject_label(reader, subject_type, card_subject), "blinded": blinded, "state": state,
        "draw": None if draw is None else {
            "id": draw.id, "by": draw.by, "at": draw.at, "seed": draw.seed, "subject_digest": draw.subject_digest,
            "rules_version": draw.rules_version, "heads": dict(draw.heads), "always": list(draw.always),
            "sampled": list(draw.sampled), "carried": dict(draw.carried)},
        "record": None if record is None else {
            "id": record.id, "by": record.by, "at": record.at,
            "ticks": [{"value_id": t.value_id, "ok": t.ok, "note": t.note} for t in record.ticks]},
        "values": values, "wanted": wanted}


def draw_spot_check(project_id: str, subject_type: SubjectType, subject: str, principal: Writer,
                    store: StoreDep) -> dict[str, Any]:
    """Draw the subject's spot check from the ledger's state (the same state gives the same draw): each value with the
    tuple it is ticked for and its source reference. A blinded study's cannot be drawn (409 `BLINDED`)."""
    scope = _scope(project_id, principal, store)
    with _refusals():
        subject = _subject_id(subject_type, subject)
        review.draw_spot_check(scope.ws, subject_type, subject, reader=scope.reader, by=principal.user_id,
                               blinded=scope.blinded(subject_type, subject))
        scope.refresh()
        return envelope(_spot_view(scope, subject_type, subject))


def record_spot_check(project_id: str, subject_type: SubjectType, subject: str, body: DeliveryTicks, principal: Writer,
                      store: StoreDep) -> dict[str, Any]:
    """Every tick of a draw, once, in one request: a tick says the value, its unit, its time, its labels and its
    statistic match the source."""
    scope = _scope(project_id, principal, store)
    with _refusals():
        subject = intake_landing.resolve_subject(scope.reader, subject_type, _subject_id(subject_type, subject))
        if scope.blinded(subject_type, subject):
            raise review.ReviewError("BLINDED", "the study is blinded until the MAP is signed (D-15): its values are "
                                                "withheld, so they cannot be ticked against their source")
        check_id("line", body.draw_id)
        ticks = [SpotTick(value_id=_value_id(t.value_id), ok=t.ok, note=t.note) for t in body.ticks]
        mine = [e.body for e in scope.store.review.entries("spot_draw") if e.body.get("id") == body.draw_id
                and e.body.get("subject_type") == subject_type
                and (subject_type == "compound" or getattr(scope.reader.entity(str(e.body.get("subject"))), "id", None) == subject)]
        if not mine:
            raise _refused(404, "UNKNOWN", f"no spot-check draw {body.draw_id} of this subject")
        review.record_spot_check(scope.ws, body.draw_id, ticks, by=principal.user_id)
        scope.refresh()
        return envelope(_spot_view(scope, subject_type, subject))


# --- the signed confirmation and the landing ---------------------------------------------------------------------------------


def confirm_subject(project_id: str, subject_type: SubjectType, subject: str, principal: Writer, store: StoreDep,
                    settings: SettingsDep) -> dict[str, Any]:
    """Confirm the subject: sign the record that binds its values, its decisions, its spot check and its coverage, and
    land it in the project. Refused (409, with every blocker; nothing is signed) while anything blocks it. Needs a
    fresh step-up (403 `STEP_UP_REQUIRED`). An interrupted landing completes here with no new signature."""
    scope = _scope(project_id, principal, store)
    ws, by = scope.ws, principal.user_id
    with _refusals():
        subject = intake_landing.resolve_subject(scope.reader, subject_type, _subject_id(subject_type, subject))
        blinded = scope.blinded(subject_type, subject)
        library = DocumentLibrary(ws)
        # the record as it would be signed now. It holds the values: used for its hash only, never answered
        _record, sha = review.bound_record(ws, subject_type, subject, **scope.card_args)  # type: ignore[arg-type]
        waiting = review.landing_incomplete(ws, subject_type, subject, sha)  # type: ignore[arg-type]
        current = review.current_confirmation(ws, subject_type, subject, reader=scope.reader)  # type: ignore[arg-type]
        if waiting is not None:
            # signed and recorded, its landing interrupted: its refusals were checked when it was signed
            plan = intake_landing.plan_landing(ws, library, subject_type, subject, reader=scope.reader,  # type: ignore[arg-type]
                                               matrix=scope.matrix, mol_weight=scope.mol_weight)
            intake_landing.land(ws, library, waiting, plan, by=by)
            confirmation = waiting
        elif current is not None and current.record_sha256 == sha:
            confirmation = current          # this very record is confirmed and landed: nothing is signed twice
        else:
            # every refusal first: no blocker is left and the landing can be planned, or nothing is signed
            record, sha, plan = review.prepare_confirmation(ws, library, subject_type, subject,  # type: ignore[arg-type]
                                                            **scope.card_args, blinded=blinded)
            ensure_step_up(principal)       # the signature comes from the token's recent step-up, never a password
            signature = sign_after_step_up(
                signer=Signer(user_id=by, printed_name=principal.printed_name), meaning=SignatureMeaning.REVIEWED,
                record_type="intake-confirmation", record_id=f"{project_id}/delivery/{subject_type}/{subject}",
                record_sha256=sha, acr=principal.acr or "")
            record_signature(settings, principal.tenant_id, signature)
            confirmation = review.record_confirmation(
                ws, subject_type=subject_type, subject=subject, record=record, record_sha256=sha,  # type: ignore[arg-type]
                signature_id=signature.signature_id, manifestation=signature.manifestation(), by=by,
                printed_name=principal.printed_name, blinded=blinded)
            try:
                intake_landing.land(ws, library, confirmation, plan, by=by)
            except (intake_landing.LandingError, ClientDataError, DatasetError) as exc:
                raise _refused(409, "LANDING_INCOMPLETE", f"confirmation {confirmation.id} is signed and recorded; its "
                               f"landing did not complete ({exc}). Confirm again to complete it: no new signature is "
                               "asked") from exc
        refresh_inputs(ws, by=by)           # the inputs follow every change (redesign §3.2)
        scope.refresh()
        return envelope(_subject_view(scope, subject_type, subject, signature={
            "signature_id": confirmation.signature_id, "manifestation": confirmation.manifestation}))


# --- a value's source --------------------------------------------------------------------------------------------------------


def get_source(project_id: str, principal: Reader, store: StoreDep, value: str | None = None,
               anchor: str | None = None) -> dict[str, Any]:
    """What the review shows beside a value: its table with the value's cell and its time, unit and label cells
    highlighted by role, or its paragraph with the span marked. Give `value` (a value's id) or `anchor` (an anchor
    text), one of them."""
    scope = _scope(project_id, principal, store)
    with _refusals():
        if (value is None) == (anchor is None):
            raise _refused(422, "INVALID", "give a value's id or an anchor, one of them")
        if value is not None:
            _value_id(value)
        else:
            parsed = parse_anchor(anchor)  # type: ignore[arg-type]
            if intake_files.file_record(scope.ws, parsed.file_sha256) is None:
                raise _refused(404, "UNKNOWN", "no file with that sha256 arrived in this project")
        view, file, value_id, blinded = scope.source(value=value, anchor=anchor)
        return envelope({
            "kind": view.kind, "title": view.title, "region_id": view.region_id, "n_rows": view.n_rows,
            "n_cols": view.n_cols, "cells": [c.model_dump(mode="json") for c in view.cells], "text": view.text,
            "span": list(view.span) if view.span is not None else None,
            # a blinded region's page is not given: drawn from the file, it would show what the cells withhold
            "page": None if blinded else view.page,
            "page_size": None if blinded or view.page_size is None else list(view.page_size),
            "box": None if blinded or view.box is None else list(view.box),
            "file": file.name, "sha256": file.sha256, "value_id": value_id, "blinded": blinded})


# --- a mapping ------------------------------------------------------------------------------------------------------------------


class DeliveryMappingApproval(BaseModel):
    version: int = Field(ge=1)
    note: str = ""


class DeliveryMappingRejection(BaseModel):
    version: int = Field(ge=1)
    why: str = Field(min_length=1)


class DeliveryMappingEdit(BaseModel):
    """A person's version of the mapping: a `mapping/2` spec, checked on the table it was written for (the mapping's
    sample table, or the table named)."""

    spec: dict[str, Any]
    why: str = Field(min_length=1)
    file_sha256: str | None = None
    region_id: str | None = None


def _versions(scope: _Scope, mapping_id: str) -> list[MappingEntry]:
    found = sorted((e for (mid, _v), e in scope.mapping_entries().items() if mid == mapping_id), key=lambda e: e.version)
    if not found:
        raise _refused(404, "UNKNOWN", f"no mapping {mapping_id} in this project")
    return found


def _tables_of_layout(scope: _Scope, sha256: str, fingerprint: str) -> list[tuple[SourceDocument, Any, RegionGrid]]:
    """The table regions of a file's cached source model whose layout is this one."""
    doc = scope.source_document(sha256)
    out = []
    for region in (doc.regions if doc is not None else ()):
        if region.kind != "table":
            continue
        try:
            grid = region_grid(doc, region.id)  # type: ignore[arg-type]
        except (AnchorError, KeyError, ValueError):
            continue
        if layout_fingerprint(grid) == fingerprint:
            out.append((doc, region, grid))
    return out


def _sample_table(scope: _Scope, versions: Sequence[MappingEntry], entry: MappingEntry,
                  uses: Sequence[dict[str, Any]]) -> tuple[SourceDocument, Any, RegionGrid] | None:
    """A table of the mapping's layout to show it on: where this version is in use, else where a version was first
    seen. Only a file with a record in this project, in a source model this project cached."""
    known = {r.sha256 for r in intake_files.files(scope.ws)}
    wanted = [(use["file_sha256"], use["region_id"]) for use in uses]
    wanted += [tuple(v.first_seen) for v in (entry, *reversed(versions))]
    for sha, region_id in dict.fromkeys(wanted):
        if sha not in known:
            continue
        tables = _tables_of_layout(scope, sha, entry.fingerprint)
        if tables:
            return next((t for t in tables if t[1].id == region_id), tables[0])
    return None


def _mapping_view(scope: _Scope, mapping_id: str, version: int | None = None, *, queued: Sequence[str] = ()) -> dict[str, Any]:
    versions = _versions(scope, mapping_id)
    entry = versions[-1] if version is None else next((e for e in versions if e.version == version), None)
    if entry is None:
        raise _refused(404, "UNKNOWN", f"no version {version} of mapping {mapping_id}")
    spec = entry.spec
    all_uses = _mapping_uses(scope)
    uses = [use for v in versions for use in all_uses.get((mapping_id, v.version), [])]
    table = _sample_table(scope, versions, entry, all_uses.get((mapping_id, entry.version), []))
    sample, findings, headers = None, [], {}
    if table is not None:
        doc, region, grid = table
        file = scope.file_name(doc.file_sha256) or doc.name
        blinded = doc.file_sha256 in scope.blinded_files()
        shown = redact(grid, region, file_name=file, document_role=doc.role)
        headers = {c: " / ".join(t for row in range(1, min(spec.header_rows, grid.n_rows) + 1)
                                 if (t := grid.cell(row, c).text.strip())) for c in range(1, grid.n_cols + 1)}
        if blinded:
            headers = {c: _mask(text) for c, text in headers.items()}
        sample = {
            "file_sha256": doc.file_sha256, "file": file, "region_id": region.id, "where": region.where,
            "n_rows": shown.n_rows, "n_cols": shown.n_cols, "header_rows": shown.header_rows,
            "context": [{"near": line.near, "line": line.line, "text": _mask(line.text) if blinded else line.text}
                        for line in shown.context],
            "header": [[_mask(text) if blinded else text for text in row] for row in shown.header],
            # a blinded study's table: no body row (a redacted body still says which cells are below the LLOQ)
            "body_rows": [] if blinded else list(shown.body_rows),
            "body": [] if blinded else [list(row) for row in shown.body], "blinded": blinded}
        findings = [{"code": f.code, "location": f.location, "message": _mask(f.message) if blinded else f.message,
                     "severity": f.severity} for f in validate_spec(spec, grid)]
    return {
        "mapping_id": mapping_id, "version": entry.version, "status": scope.mapping_status(mapping_id, entry.version),
        "origin": entry.origin, "origin_detail": entry.origin_detail, "fingerprint": entry.fingerprint, "by": entry.by,
        "at": entry.at, "kind": spec.kind, "layout": spec.layout, "header_rows": spec.header_rows,
        "first_data_row": spec.first_data_row, "last_data_row": spec.last_data_row, "field": spec.field,
        "time_row": spec.time_row, "time_unit": spec.time_unit, "value_unit": spec.value_unit, "statistic": spec.statistic,
        "time_reference": spec.time_reference, "not_data_reason": spec.not_data_reason, "questions": list(spec.questions),
        "columns": [{"column": c.column, "header": headers.get(c.column), "role": c.role, "field": c.field, "unit": c.unit,
                     "statistic": c.statistic, "spread_kind": c.spread_kind, "of": c.of, "cell_form": c.cell_form,
                     "condition": c.condition, "series_role": c.series_role, "reason": c.reason} for c in spec.columns],
        "keys": [{"pattern": k.pattern, "field": k.field, "statistic": k.statistic, "spread_kind": k.spread_kind}
                 for k in spec.keys],
        "tokens": {"below_lloq": list(spec.below_lloq_tokens), "missing": list(spec.missing_tokens)},
        "rules": [{"column": r.column, "pattern": r.pattern, "role": r.role, "spread_kind": r.spread_kind,
                   "reason": r.reason} for r in spec.row_rules],
        "constants": [{"field": c.field, "cite": c.cite.model_dump(mode="json", exclude_none=True), "pattern": c.pattern}
                      for c in spec.constants],
        "spec": spec.model_dump(mode="json", by_alias=True), "sample": sample, "findings": findings,
        "versions": [{"version": v.version, "status": scope.mapping_status(mapping_id, v.version), "origin": v.origin,
                      "origin_detail": v.origin_detail, "by": v.by, "at": v.at,
                      "decisions": [{"status": d.status, "why": d.why, "by": d.by, "at": d.at}
                                    for d in scope.mapping_decisions(mapping_id, v.version)]} for v in versions],
        "used_in": uses, "waiting": any(scope.reading(use["file_sha256"]) for use in uses) or any(
            scope.reading(sha) for sha in queued), "queued": list(queued)}


def get_mapping(project_id: str, mapping_id: str, principal: Reader, store: StoreDep,
                version: int | None = None) -> dict[str, Any]:
    """A mapping as a person reviews it: each column's header with its role, field and unit, the tokens and row rules,
    the table as the table mapper is shown it (no digit of its body), every version with its decisions, and where it
    is in use. `version`: one version (default: the latest)."""
    scope = _scope(project_id, principal, store)
    with _refusals():
        return envelope(_mapping_view(scope, check_id("mapping", mapping_id), version))


def _read_again(scope: _Scope, mapping_id: str, fingerprint: str, principal: Any, store: Any, *,
                only_waiting: bool = False) -> list[str]:
    """Queue again every file that holds a table of the mapping's layout (a table read with one of its versions, or
    one left unread whose layout is this one) and start the intake job: the sha256s queued. `only_waiting`: only the
    files with a table that still shows a rejected version's reading (the run that follows a rejection is owed)."""
    records = _run_records(scope)
    chosen = []
    for sha, record in records.items():
        coverage = scope.coverage(sha)
        tables = [r for r in (coverage.regions if coverage is not None else ()) if r.region.kind == "table"]
        mine = [r for r in tables if r.outcome.mapping is not None and r.outcome.mapping.mapping_id == mapping_id]
        if only_waiting:
            if any(_region_state(scope, r.outcome) == "waiting" for r in mine):
                chosen.append(record)
        elif mine or (any(r.outcome.state == "unread" for r in tables) and _tables_of_layout(scope, sha, fingerprint)):
            chosen.append(record)
    queued = intake_pipeline.enqueue(scope.ws, chosen, by=principal.user_id, again=True) if chosen else []
    _kick(scope, principal, store)
    return [run.sha256 for run in queued]


def _mapping_decided(scope: _Scope, mapping_id: str, version: int, principal: Any, store: Any, *,
                     head: int) -> dict[str, Any]:
    """The mapping after a decision or an edit, its files queued again. `head`: the mappings log's length before it;
    when the request added no line (the same decision or spec again) only a table that still waits is queued."""
    scope.refresh()
    entry = scope.mapping_entries()[(mapping_id, version)]
    queued = _read_again(scope, mapping_id, entry.fingerprint, principal, store,
                         only_waiting=scope.store.mappings.head().seq == head)
    scope.refresh()
    return envelope(_mapping_view(scope, mapping_id, version, queued=queued))


def approve_mapping(project_id: str, mapping_id: str, body: DeliveryMappingApproval, principal: Writer,
                    store: StoreDep) -> dict[str, Any]:
    """A person's approval of one version: the values read under it become `approved_mapping`, the version governs
    its layout from now on, and the files that hold such a table are read again."""
    scope = _scope(project_id, principal, store)
    with _refusals():
        check_id("mapping", mapping_id)
        if (mapping_id, body.version) not in scope.mapping_entries():
            raise _refused(404, "UNKNOWN", f"no version {body.version} of mapping {mapping_id}")
        head = scope.store.mappings.head().seq
        MappingCache(scope.ws).approve(mapping_id, body.version, by=principal.user_id, note=body.note)
        return _mapping_decided(scope, mapping_id, body.version, principal, store, head=head)


def reject_mapping(project_id: str, mapping_id: str, body: DeliveryMappingRejection, principal: Writer,
                   store: StoreDep) -> dict[str, Any]:
    """A person's rejection of one version, with why: it is never read with again, and the files that hold such a
    table are read again. Until that run is done the table shows as waiting (its earlier values are still active)."""
    scope = _scope(project_id, principal, store)
    with _refusals():
        check_id("mapping", mapping_id)
        if (mapping_id, body.version) not in scope.mapping_entries():
            raise _refused(404, "UNKNOWN", f"no version {body.version} of mapping {mapping_id}")
        head = scope.store.mappings.head().seq
        MappingCache(scope.ws).reject(mapping_id, body.version, by=principal.user_id, why=body.why)
        return _mapping_decided(scope, mapping_id, body.version, principal, store, head=head)


def edit_mapping(project_id: str, mapping_id: str, body: DeliveryMappingEdit, principal: Writer,
                 store: StoreDep) -> dict[str, Any]:
    """Store a person's version of the mapping (checked by code on its table: a spec with an error is refused, 422
    with the findings) and read the files that hold such a table again. It waits for approval like any version."""
    scope = _scope(project_id, principal, store)
    with _refusals():
        versions = _versions(scope, check_id("mapping", mapping_id))
        latest = versions[-1]
        if (body.file_sha256 is None) != (body.region_id is None):
            raise _refused(422, "INVALID", "name the table by its file and its region, both or neither")
        if body.file_sha256 is not None:
            check_id("sha256", body.file_sha256)
            check_id("region", body.region_id)  # type: ignore[arg-type]
            if intake_files.file_record(scope.ws, body.file_sha256) is None:
                raise _refused(404, "UNKNOWN", "no file with that sha256 arrived in this project")
            table = next((t for t in _tables_of_layout(scope, body.file_sha256, latest.fingerprint)
                          if t[1].id == body.region_id), None)
            if table is None:
                raise _refused(409, "CONFLICT", "that region is not a table of this mapping's layout")
        else:
            table = _sample_table(scope, versions, latest, _mapping_uses(scope).get((mapping_id, latest.version), []))
            if table is None:
                raise _refused(409, "CONFLICT", "no table of this layout is in the source cache: run its file again")
        doc, region, grid = table
        try:
            spec = MappingSpec.model_validate(body.spec)
        except ValidationError as exc:
            raise _refused(422, "INVALID", "not a mapping spec: " + "; ".join(
                f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5])) from exc
        blinded = doc.file_sha256 in scope.blinded_files()
        errors = [f for f in validate_spec(spec, grid) if f.severity == "error"]
        if errors:
            raise _refused(422, "MAPPING_INVALID", f"the spec does not read this table: {len(errors)} errors", findings=[
                {"code": f.code, "location": f.location, "message": _mask(f.message) if blinded else f.message,
                 "severity": f.severity} for f in errors])
        cache = MappingCache(scope.ws)
        head = scope.store.mappings.head().seq
        entry = cache.propose(latest.fingerprint, spec, origin="person", origin_detail=principal.user_id,
                              first_seen=(doc.file_sha256, region.id), by=principal.user_id)
        if entry.version > latest.version:      # a new version (the same spec as a stored version is that version)
            line = next(e for e in scope.store.mappings.entries("entry")
                        if e.body.get("mapping_id") == mapping_id and e.body.get("version") == entry.version)
            scope.store.audit(actor=principal.user_id, action="intake.mapping.edit", resource_id=f"{mapping_id}/{entry.version}",
                              after={"mapping_id": mapping_id, "version": entry.version, "spec_sha256": sha256_of(entry.spec),
                                     "row_hash": line.hash}, reason=body.why)
        elif cache.status(mapping_id, entry.version) == "rejected":
            raise _refused(409, "CONFLICT", f"this spec is version {entry.version}, which a person rejected: a rejected "
                                            "version is never read with (approve that version to use it)")
        return _mapping_decided(scope, mapping_id, entry.version, principal, store, head=head)


# --- the routes ---------------------------------------------------------------------------------------------------------------


def mount(router: APIRouter) -> None:
    """Add the Delivery routes to `router` (client_api's, prefix /api/v1): they are that router's routes."""
    subject = PREFIX + "/subjects/{type}/{subject}"
    mapping = PREFIX + "/mappings/{mapping_id}"
    router.get(PREFIX, **answers(DeliveryPage))(get_delivery)
    router.post(PREFIX + ":run", status_code=202, **answers(TriageStart))(run_delivery)
    router.get(PREFIX + "/source", **answers(DeliverySource))(get_source)
    router.post(PREFIX + "/values:assign", **answers(DeliveryPage))(assign_values)
    router.post(PREFIX + "/regions:exclude", **answers(DeliveryPage))(exclude_regions)
    router.get(mapping, **answers(DeliveryMapping))(get_mapping)
    router.post(mapping + ":approve", **answers(DeliveryMapping))(approve_mapping)
    router.post(mapping + ":reject", **answers(DeliveryMapping))(reject_mapping)
    router.post(mapping + ":edit", **answers(DeliveryMapping))(edit_mapping)
    router.get(subject, **answers(DeliverySubject))(get_subject)
    router.post(subject + ":override", **answers(DeliverySubject))(override_check)
    router.post(subject + ":dispose", **answers(DeliverySubject))(dispose_requirement)
    router.post(subject + ":choose", **answers(DeliverySubject))(choose_value)
    router.post(subject + ":link", **answers(DeliverySubject))(decide_link)
    router.post(subject + ":enter", **answers(DeliverySubject))(enter_value)
    router.post(subject + ":confirm", **answers(DeliverySubject))(confirm_subject)
    router.post(subject + "/spot-check:draw", **answers(DeliverySpotCheck))(draw_spot_check)
    router.post(subject + "/spot-check", **answers(DeliverySpotCheck))(record_spot_check)
