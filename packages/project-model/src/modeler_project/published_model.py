"""A published OSP model as a source of the inputs (redesign §5: it takes the place of the Quick start wizard).

The model's parameter values are proposed as evidence citing the model (``OSP_LIBRARY``, its ValueOrigin text as the
quote), and the clinical datasets it carries as observed data citing their publications. They flow into the inputs like
every other source (D-27); the source-selection rule ranks the published model below the client and the literature
(D-32), and nothing is accepted here. The T-56 kit (`deploy/proof/run_t56.py`) builds its inputs with the same rules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from modeler_project.workspace import Workspace

# The data-plan item each published-model parameter answers (by CPF id prefix, most specific first). A parameter with
# no item of its own is carried with the item of its group, and the evidence says so.
REQUIREMENT_OF = (
    ("phys.halogens.", "REQ-phys.halogens"), ("phys.mw", "REQ-phys.mw"), ("phys.logp", "REQ-phys.logp"),
    ("phys.pka.", "REQ-phys.pka"), ("phys.solubility.", "REQ-phys.solubility.ref"), ("bind.fu", "REQ-bind.fu"),
    ("bind.partner", "REQ-bind.partner"), ("perm.intestinal", "REQ-perm.intestinal"), ("elim.renal.", "REQ-elim.renal"),
    ("elim.", "REQ-elim.pathway"), ("expr.", "REQ-expr.profiles"), ("form.", "REQ-form.release"),
    ("indiv.", "REQ-sys.demographics"), ("sim.", "REQ-dist.bp_ratio"), ("dist.", "REQ-dist.bp_ratio"),
    ("perm.cellular", "REQ-dist.bp_ratio"),
)
OWN_ITEM = {"REQ-phys.mw", "REQ-phys.logp", "REQ-bind.fu", "REQ-bind.partner", "REQ-perm.intestinal", "REQ-elim.renal"}
_STAT = {"ArithmeticMean": "arithmetic_mean", "GeometricMean": "geometric_mean", "Median": "median"}
_REF = re.compile(r"\((https?://[^,\s)]+),\s*([^)]*)\)")


def requirement_of(cpf_id: str) -> str:
    return next(req for prefix, req in REQUIREMENT_OF if cpf_id == prefix.rstrip(".") or cpf_id.startswith(prefix))


def statistics(snapshot: dict[str, Any]) -> dict[str, str]:
    """Study id → the statistic its observed series is (harvested from the snapshot's quantity path)."""
    from pbpk_domain.reference.osp_import import _props, _study_id

    out = {}
    for dataset in snapshot.get("ObservedData", []):
        path = ((dataset.get("Columns") or [{}])[0].get("QuantityInfo") or {}).get("Path", "")
        kind = path.rsplit("|", 1)[-1]
        if kind in _STAT:
            out[_study_id(_props(dataset), dataset["Name"])] = _STAT[kind]
    return out


def evidence_bodies(imported: Any, *, model: str, url: str, note: str = "") -> list[dict[str, Any]]:
    """One manual-evidence body per parameter of the published model, citing the model and its ValueOrigin. ``note``
    goes first in each body's note (the T-56 kit names itself there)."""
    out = []
    for record in imported.cpf.parameters:
        req = requirement_of(record.id)
        prov = record.provenance
        origin = prov.reference if prov and prov.reference else imported.source
        fitted = record.status.value == "FITTED"
        text = (f"{note}value of the published OSP {model} model"
                + ("; identified by parameter identification in that model" if fitted else "")
                + ("" if req in OWN_ITEM else f"; carried with {req} (no data-plan item of its own)"))
        out.append({
            "req_id": req, "target": record.id, "value": record.value, "unit": record.unit, "source_type": "OSP_LIBRARY",
            "quote": origin, "locator": f"PK-Sim snapshot, compound {imported.cpf.compound}", "url": url,
            "title": f"Open Systems Pharmacology — {model} model (PK-Sim snapshot)",
            "conditions": {"value origin": (prov.source_type if prov else "published model")}, "note": text,
            **({"_process": record.engine_binding.process} if record.engine_binding and record.engine_binding.process
               and record.id.startswith("elim.") else {}),
        })
    return out


def study_reference(text: str) -> tuple[str | None, str, str]:
    """(url, locator, import note) from an imported study's reference text."""
    match = _REF.search(text or "")
    note = text.split("Import:", 1)[1].strip() if "Import:" in (text or "") else ""
    return (match.group(1), match.group(2).strip(), note) if match else (None, "", note)


def dataset_bodies(imported: Any, stats: dict[str, str], *, model: str, label: str,
                   leave_out: tuple[str, ...] = ()) -> tuple[list[dict[str, Any]], list[str]]:
    """The model's clinical datasets with a mean profile, each with its publication and figure, but those left out by
    id; the others are named with why (no profile, or a statistic the snapshot does not state)."""
    out, skipped = [], []
    for row in imported.studies:
        sid = row["study_id"]
        if sid in leave_out:
            continue
        statistic = stats.get(sid)
        profile = row.get("profile")
        if statistic is None or not profile:
            skipped.append(f"{sid}: {'no profile' if not profile else 'statistic not stated in the snapshot'}")
            continue
        url, locator, note = study_reference(row.get("reference", ""))
        study = {k: v for k, v in row.items() if k not in ("profile", "reference")}
        out.append({
            "kind": "profile", "study": study, "time_unit": profile.get("time_unit", "h"), "unit": profile["unit"],
            "series": [{"name": "mean", "statistic": statistic, "times": profile["times"], "values": profile["values"],
                        "n": row.get("n")}],
            "origin": "OSP_LIBRARY", "purpose": "model_building",
            "source": {"url": url, "locator": locator, "title": f"OSP {model} model observed data: {row['reference'].split(' (')[0]}"},
            "note": f"{label}; import: {note}" if note else label,
        })
    return out, skipped


@dataclass
class Taken:
    """What one use of a published model proposed, and what it did not, with why."""

    values: int = 0
    datasets: int = 0
    already: int = 0
    skipped: list[str] = field(default_factory=list)


def propose_published_model(ws: Workspace, snapshot: dict[str, Any], *, model: str, url: str, actor: str,
                            mol_weight: float | None = None) -> Taken:
    """Propose the published model's values and datasets in this project, citing the model and its publications. A
    value or dataset the model already gave is not proposed again, so taking it twice changes nothing."""
    from modeler_project import ArtifactKind
    from modeler_project.dataset_register import datasets, propose_dataset
    from modeler_project.datasets import DatasetError, ObservedDataset, Origin, Series, new_dataset_id
    from modeler_project.evidence import EvidenceItem, Extraction, SourceRef, SourceType, new_id
    from modeler_project.evidence_register import EvidenceError, items, propose
    from modeler_project.requirements import RequirementMatrix
    from pbpk_domain.reference import import_osp_snapshot

    version = ws.latest(ArtifactKind.REQUIREMENTS, "main")
    if version is None:
        raise ValueError("this project has no data checklist yet: it is derived from the brief at Start")
    matrix = RequirementMatrix.from_content(version.content)
    by_template = {i.req_id.split("@", 1)[0]: i for i in matrix.items}
    imported = import_osp_snapshot(snapshot, source=f"OSP {model} model")
    taken = Taken(skipped=[f"{s}" for s in imported.skipped])
    had = {(e.target, str(e.value)) for e in items(ws) if e.source_type is SourceType.OSP_LIBRARY}
    for body in evidence_bodies(imported, model=model, url=url):
        requirement = by_template.get(body["req_id"])
        if requirement is None:
            taken.skipped.append(f"{body['target']}: the data checklist has no item {body['req_id']}")
            continue
        if (body["target"], str(body["value"])) in had:
            taken.already += 1
            continue
        item = EvidenceItem(
            id=new_id(), req_id=requirement.req_id, target=body["target"], value=body["value"], unit=body["unit"],
            source_type=SourceType.OSP_LIBRARY, source=SourceRef(locator=body["locator"], title=body["title"], url=url),
            quote=body["quote"], extraction=Extraction.MANUAL, conditions=body["conditions"],
            purpose=requirement.purpose or "model_building", provider="LITERATURE", note=body["note"])
        try:
            propose(ws, item, actor=actor, requirement=requirement)
        except EvidenceError as exc:
            taken.skipped.append(f"{body['target']}: {exc}")
            continue
        taken.values += 1
    present = {str(d.study.get("study_id")) for d in datasets(ws) if d.origin is Origin.OSP_LIBRARY}
    bodies, skipped = dataset_bodies(imported, statistics(snapshot), model=model, label=f"published OSP {model} model")
    taken.skipped += skipped
    for body in bodies:
        if str(body["study"]["study_id"]) in present:
            taken.already += 1
            continue
        dataset = ObservedDataset(
            id=new_dataset_id(), kind="profile", study=body["study"], time_unit=body["time_unit"], unit=body["unit"],
            series=tuple(Series.model_validate(s) for s in body["series"]), origin=Origin.OSP_LIBRARY,
            extraction="OSP_SNAPSHOT", source=SourceRef.model_validate(body["source"]), purpose="model_building",
            provider="LITERATURE", note=body["note"])
        try:
            propose_dataset(ws, dataset, actor=actor, mol_weight=mol_weight)
        except (DatasetError, ValueError) as exc:
            taken.skipped.append(f"{body['study']['study_id']}: {exc}")
            continue
        taken.datasets += 1
    return taken
