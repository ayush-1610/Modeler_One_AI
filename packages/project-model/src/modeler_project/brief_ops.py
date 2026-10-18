"""Operations on the brief shared by the API, the agent and the tests: who may change a field, identity resolution,
and storing the brief (BRIEF/main): this module is the kind's one writer (phase 6e, rule B3).

Human decisions are never overwritten by an agent pass: a field a person entered, edited, confirmed or marked not
applicable is *locked* (the same convention as `userLocked` on the planning canvas). An agent may fill or refresh
only fields that are missing or that an agent or a database filled before.

A person's edit asks no "why" (redesign map row `p1-why`: the audit trail records who changed what), except the model
risk, which is confirmed with its reasons (ICH M15). Every stored brief re-derives the data checklist at once (D-27:
no approval in between).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any

from modeler_project.artifacts import ArtifactKind, ArtifactRef, ArtifactVersion
from modeler_project.brief import (
    RATINGS,
    Citation,
    FieldRecord,
    FieldStatus,
    ProjectBrief,
    add_question,
    coerce,
    definition_of,
    set_record,
)
from modeler_project.identity import IdentityError, PubChemRecord, fetch_pubchem, from_smiles, mw_agrees
from modeler_project.workspace import Workspace
from pbpk_domain.m15 import Rating, allowed_model_risk

BRIEF_ID = "main"

HUMAN_STATUSES = frozenset({FieldStatus.ENTERED, FieldStatus.EDITED, FieldStatus.CONFIRMED, FieldStatus.NOT_APPLICABLE})
# Fields only a person may set: the ICH M15 ratings and the model risk they bound.
HUMAN_ONLY = frozenset({"m15.influence_rating", "m15.consequence_rating", "acceptance.tier"})
# Fields a person sets with the reasons (the model risk decides the acceptance criteria every round is judged by).
REASON_REQUIRED = frozenset({"acceptance.tier"})


def locked(brief: ProjectBrief, path: str) -> bool:
    return brief.get(path).status in HUMAN_STATUSES


class EditError(ValueError):
    pass


def allowed_risks(brief: ProjectBrief) -> tuple[str, ...]:
    """The model risks ICH M15 §2.1.5 admits for the brief's two ratings (`pbpk_domain.m15`), or () until both are
    rated. Equal ratings give that risk; different ones admit any risk between them, chosen with a reason."""
    influence, consequence = brief.value("m15.influence_rating"), brief.value("m15.consequence_rating")
    if influence not in RATINGS or consequence not in RATINGS:
        return ()
    return tuple(r.value for r in allowed_model_risk(Rating(influence), Rating(consequence)))


def risk_problem(brief: ProjectBrief, tier: Any) -> str | None:
    """Why `tier` cannot be the model risk with the brief's ratings, or None."""
    allowed = allowed_risks(brief)
    if not allowed or tier in allowed:
        return None
    influence, consequence = brief.value("m15.influence_rating"), brief.value("m15.consequence_rating")
    return (f"with model influence {influence} and decision consequence {consequence}, ICH M15 admits a model risk of "
            f"{' or '.join(allowed)}, not {tier}")


def edit_field(brief: ProjectBrief, path: str, *, value: Any = None, unit: str | None = None, status: FieldStatus,
               note: str = "", by: str, citations: tuple[Citation, ...] = ()) -> ProjectBrief:
    """A person's change to one field: EDITED (new value), CONFIRMED (kept), NOT_APPLICABLE or MISSING (cleared).
    No reason is asked, except for the model risk; the version records who changed what."""
    if status not in (FieldStatus.EDITED, FieldStatus.CONFIRMED, FieldStatus.NOT_APPLICABLE, FieldStatus.MISSING):
        raise EditError(f"{path}: a person sets EDITED, CONFIRMED, NOT_APPLICABLE or MISSING, not {status}")
    if path in REASON_REQUIRED and status is FieldStatus.EDITED and not note.strip():
        raise EditError(f"{path}: give the reasons (model influence and decision consequence)")
    definition = definition_of(path)
    current = brief.get(path)
    now = datetime.now(UTC)
    if status is FieldStatus.CONFIRMED:
        if current.status is FieldStatus.MISSING:
            raise EditError(f"{path}: nothing to confirm; enter a value instead")
        record = current.model_copy(update={"status": FieldStatus.CONFIRMED, "by": by, "at": now,
                                            "note": note or current.note})
    elif status is FieldStatus.EDITED:
        try:
            coerced = coerce(definition, value)
        except ValueError as exc:
            raise EditError(str(exc)) from exc
        if coerced in (None, "", []):
            raise EditError(f"{path}: an edit needs a value (use MISSING to clear it)")
        if path == "acceptance.tier" and (problem := risk_problem(brief, coerced)):
            raise EditError(f"{path}: {problem}")
        record = FieldRecord(value=coerced, unit=unit or definition.unit, status=FieldStatus.EDITED,
                             citations=citations or current.citations, confidence=None, note=note, by=by, at=now)
    else:
        record = FieldRecord(status=status, note=note, by=by, at=now)
    return set_record(brief, path, record)


def agent_set(brief: ProjectBrief, path: str, *, value: Any, unit: str | None, citations: tuple[Citation, ...],
              status: FieldStatus, confidence: str, by: str, note: str = "") -> ProjectBrief:
    """An agent's or a database's value for a field. Refused for locked and human-only fields."""
    if path in HUMAN_ONLY:
        raise EditError(f"{path} is set by a person only")
    if locked(brief, path):
        raise EditError(f"{path} was set by a person ({brief.get(path).status}); agents do not overwrite it")
    definition = definition_of(path)
    try:
        coerced = coerce(definition, value)
    except ValueError as exc:
        raise EditError(str(exc)) from exc
    return set_record(brief, path, FieldRecord(value=coerced, unit=unit or definition.unit, status=status,
                                               citations=citations, confidence=confidence, note=note, by=by,
                                               at=datetime.now(UTC)))


def _quote_from(text: str, key: str) -> str | None:
    """The exact `"Key":value` span of a JSON answer, as it appears in the text."""
    match = re.search(rf'"{re.escape(key)}"\s*:\s*("(?:[^"\\]|\\.)*"|[-0-9.eE+]+)', text)
    return match.group(0) if match else None


def apply_pubchem(brief: ProjectBrief, record: PubChemRecord, *, doc_sha256: str, by: str) -> tuple[ProjectBrief, list[str]]:
    """Fill identity fields from a stored PubChem answer (RETRIEVED, each quoted from that answer)."""
    notes: list[str] = []
    for path, value, key in (
        ("drug.pubchem_cid", str(record.cid), "CID"),
        ("drug.smiles", record.smiles, "IsomericSMILES" if _quote_from(record.text, "IsomericSMILES") else "CanonicalSMILES"),
        ("drug.inchikey", record.inchikey, "InChIKey"),
    ):
        quote = _quote_from(record.text, key) or _quote_from(record.text, "SMILES")
        if not value or not quote:
            continue
        cite = Citation(doc_sha256=doc_sha256, page=1, quote=quote, locator=f"PubChem CID {record.cid}",
                        source="PubChem PUG REST")
        try:
            brief = agent_set(brief, path, value=value, unit=None, citations=(cite,), status=FieldStatus.RETRIEVED,
                              confidence="A", by=by)
        except EditError as exc:
            notes.append(str(exc))
    return brief, notes


def check_structure(brief: ProjectBrief, *, by: str) -> tuple[ProjectBrief, list[str]]:
    """RDKit cross-check (MS-01 §2.2): MW from the structure vs the stated or retrieved MW; halogen counts noted."""
    smiles = brief.value("drug.smiles")
    if not smiles:
        return brief, []
    notes: list[str] = []
    try:
        identity = from_smiles(str(smiles))
    except IdentityError as exc:
        return add_question(brief, "drug.smiles", f"{exc}. Correct the structure.", raised_by=by), [str(exc)]
    halogens = ", ".join(f"{k} {v}" for k, v in identity.halogens.items() if v) or "none"
    note = f"from the structure (RDKit): {identity.formula}, MW {identity.mw:g} g/mol, halogens {halogens}"
    stated = brief.value("drug.mw_free_base")
    if stated is None and not locked(brief, "drug.mw_free_base"):
        brief = set_record(brief, "drug.mw_free_base", FieldRecord(
            value=identity.mw, unit="g/mol", status=FieldStatus.COMPUTED, confidence="A", note=note, by=by,
            at=datetime.now(UTC)))
    elif stated is not None and not mw_agrees(float(stated), identity.mw):
        message = (f"the stated molecular weight {float(stated):g} g/mol differs from the structure's {identity.mw:g}: a salt "
                   "form, a different compound, or a typo?")
        brief = add_question(brief, "drug.mw_free_base", message, raised_by=by)
        notes.append(message)
    else:
        notes.append(note)
    return brief, notes


def resolve_identity(brief: ProjectBrief, *, store_record: Callable[[PubChemRecord], str], by: str,
                     fetch: Callable[[str], PubChemRecord] = fetch_pubchem) -> tuple[ProjectBrief, list[str]]:
    """PubChem lookup by drug name (stored as a retrieved record via `store_record`, which returns its sha), then the
    structure check. A lookup that fails is a question on the CID, not an error: the identity can be entered by hand."""
    notes: list[str] = []
    try:
        record = fetch(brief.drug_name)
    except IdentityError as exc:
        notes.append(str(exc))
        brief = add_question(brief, "drug.pubchem_cid", f"PubChem could not give the identity ({exc}): check the drug "
                             "name, or enter the CID or the SMILES by hand.", raised_by=by)
    else:
        brief, more = apply_pubchem(brief, record, doc_sha256=store_record(record), by=by)
        notes.extend(more)
    brief, more = check_structure(brief, by=by)
    return brief, notes + more


def summary(brief: ProjectBrief) -> dict[str, Any]:
    """Counts by status, for the agent and the page header."""
    counts: dict[str, int] = {}
    for record in list(brief.fields.values()) + [r for items in brief.groups.values() for item in items for r in item.values()]:
        counts[record.status.value] = counts.get(record.status.value, 0) + 1
    return {"by_status": counts, "groups": {g: len(items) for g, items in brief.groups.items()},
            "open_questions": sum(q.status == "open" for q in brief.questions)}


def save_brief(ws: Workspace, brief: ProjectBrief, *, actor: str, reason: str,
               derived_from: Iterable[ArtifactRef] | None = None) -> ArtifactVersion:
    """Store `brief` as the brief's next version, then re-derive the data checklist from it. It keeps the current
    version's provenance (the documents it was read from) unless `derived_from` names it anew."""
    from modeler_project.data_plan import derive_data_plan

    if derived_from is None:
        latest = ws.latest(ArtifactKind.BRIEF, BRIEF_ID)
        derived_from = latest.derived_from if latest else ()
    version = ws.commit(ArtifactKind.BRIEF, BRIEF_ID, brief.to_content(), derived_from=derived_from, actor=actor,
                        reason=reason)
    derive_data_plan(ws, actor="system", reason=f"derived from brief v{version.version} ({reason})")
    return version
