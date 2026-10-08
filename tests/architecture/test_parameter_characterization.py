"""What today's CPF parameter vocabulary answers, recorded before the parameter registry replaces it (phase 4).

The ids a value may target are listed in a dozen tables (docs/ARCHITECTURE_BOUNDARIES.md, C1). Phase 4 derives them
from one registry in pbpk_domain (docs/plans/2026-10-08-parameter-registry.md); every step of it must leave the
answers below unchanged. The test records the tables themselves and, for a corpus of ids (every id the tables, the
harvested process table, the requirement templates, the MAP's fit candidates and MS-01 §2.2 name, plus edge probes),
what each vocabulary function answers: placement, storage unit, unit conversion, process binding, compound path,
physical bounds, ValueOrigin method and the S0 requirement it satisfies. The snapshot is
docs/architecture/parameter-vocabulary.json.

A change to it is a change to the science or to what the builder sets: only the science PR (total_cl, ehc_fraction,
with the owner's approval) changes it on purpose, and its diff is the review. Rewrite it with

    UPDATE_SNAPSHOTS=1 uv run pytest tests/architecture/test_parameter_characterization.py
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from modeler_api.templates_api import _BLANK_PARAMETERS
from modeler_project import evidence, inputs
from modeler_project.evidence import EvidenceItem, SourceType
from modeler_project.requirements import load_templates
from pbpk_domain import parameter_units, pksim_paths
from pbpk_domain.campaign.map import STAGE_PLAN
from pbpk_domain.cpf import build, process_bindings
from pbpk_domain.cpf.completeness import check_completeness
from pbpk_domain.cpf.models import CPF, ParameterRecord, ParameterStatus, Provenance
from pbpk_domain.reference.osp_import import PROCESS_FAMILY, PROCESS_PARAMETERS

pytestmark = pytest.mark.req("T-25")

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "docs" / "architecture" / "parameter-vocabulary.json"

# MS-01 §2.2's ids, concrete (docs/PBPK_MODELING_WORKFLOW.md), and probes at the edges of the prefix rules
MS01 = (
    "id.name", "id.inchikey", "id.smiles", "phys.mw", "phys.halogens.Cl", "phys.logp", "phys.pka.acid.1",
    "phys.pka.base.1", "phys.pka.neutral", "phys.solubility.ref", "phys.solubility.ref_ph", "phys.solubility.table",
    "bind.fu", "bind.partner", "dist.bp_ratio", "dist.partition_method", "dist.permeability_method", "perm.cellular",
    "perm.intestinal", "elim.hepatic.CYP3A4.clspec", "elim.hepatic.CYP3A4.km", "elim.hepatic.CYP3A4.vmax",
    "elim.hepatic.total_cl", "elim.fm.CYP3A4", "elim.renal.gfr_fraction", "elim.renal.ts_clspec", "elim.biliary.cl",
    "elim.ehc_fraction", "transp.OCT1.km", "transp.OCT1.vmax", "transp.OCT1.clspec", "form.tablet.type",
    "form.tablet.weibull.t50", "form.tablet.weibull.shape", "form.tablet.weibull.lag", "form.tablet.particle.d50",
    "food.fed_solubility_factor", "ddi.perp.CYP3A4.ki_u", "ddi.perp.CYP3A4.kinact", "ddi.perp.CYP3A4.ec50_u",
    "ddi.perp.CYP3A4.emax", "pd.emax",
)
PROBES = (
    "elim", "phys.pka", "phys.halogens", "unknown.parameter", "phys.solubility.ref@fed", "perm.intestinal@fed",
    "elim.hepatic.CYP3A4@alt.clspec", "sim.x", "sim[oral].x", "cmpd.x", "expr.x", "indiv.x", "alt.select",
    "elim.fe_urine", "elim.fm", "elim.hepatic.{enzyme}.clspec", "elim.hepatic.<enzyme>.clspec", "form.tablet.shape",
    "bind.specific.GABRG2.koff", "elim.renal.total.plasma_clearance", "elim.hepatic.total.plasma_clearance",
)
_ID = re.compile(r"^[a-z]+(\.[A-Za-z0-9_@\[\]|]+)+\.?$")


def _concrete(template: str) -> list[str]:
    """A template id (`elim.hepatic.{enzyme}.km/vmax`, `transp.{name}.kcat`) as the concrete ids it stands for."""
    t = template.replace("<enzyme>", "CYP3A4").replace("{enzyme}", "CYP3A4").replace("{transporter}", "OCT1")
    t = t.replace("{name}", "OCT1" if t.startswith("transp.") else "tablet").replace("{product}", "tablet")
    head, _, last = t.rpartition(".")
    return [f"{head}.{x}" for x in last.split("/")] if "/" in last else [t]


def _sample(prefix: str) -> str:
    """A concrete id under a prefix rule (`phys.pka.acid.` -> `phys.pka.acid.1`, `sim[` -> `sim[oral].x`)."""
    if prefix.endswith(("acid.", "base.")):
        return prefix + "1"
    return prefix + "oral].x" if prefix.endswith("[") else prefix + "x" if prefix.endswith(".") else prefix


def corpus() -> list[str]:
    ids: set[str] = set(MS01) | set(PROBES)
    ids |= set(inputs.MODEL_IDS) | set(inputs.REFERENCE_IDS) | set(inputs.PLACEHOLDERS)
    ids |= {_sample(p) for p in (*inputs.MODEL_PREFIXES, *inputs.REFERENCE_PREFIXES)}
    ids |= {i for t in inputs.PATHWAY_TARGETS for i in _concrete(t)}
    ids |= {_sample(prefix) for prefix, _ in parameter_units._TARGETS}
    ids |= set(pksim_paths._COMPOUND_PARAM) | set(evidence._PHYSICAL) | set(build.ALTERNATIVE_GROUP_OF_ID)
    ids |= {_sample(p) for p in build.REFERENCE_ELIMINATION}
    for prefix, process in process_bindings._FIXED_PREFIX.items():
        ids |= {f"{prefix}.{suffix}" for suffix, _ in PROCESS_PARAMETERS[process].values()}
    for process, family in PROCESS_FAMILY.items():
        ids |= {f"{family}.CYP3A4.{suffix}" for suffix, _ in PROCESS_PARAMETERS[process].values()}
    for stage in STAGE_PLAN.values():
        ids |= {i for t in (*stage["fit_candidates"], *stage["branches"]) if _ID.match(t.replace("{", "").replace("}", ""))
                for i in _concrete(t)}
    for template in load_templates():
        ids |= {i for r in template["items"] if r.get("kind") == "parameter" for i in _concrete(r["target"])}
    ids |= {pid for pid, _, _ in _BLANK_PARAMETERS}
    return sorted(ids)


def _plain(value):
    """Tables as JSON: tuples as lists, sets sorted."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted(_plain(v) for v in value)
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def _record(cpf_id: str) -> ParameterRecord:
    return ParameterRecord(id=cpf_id, value=1.0, status=ParameterStatus.FIXED,
                           provenance=Provenance(source_type="measured", reference="characterization"))


EMPTY = check_completeness(CPF(compound="Drug"))


def answers(cpf_id: str) -> dict:
    family = parameter_units.target_family(cpf_id)
    try:
        converted = parameter_units.to_storage_unit(cpf_id, 1.0, None)
        conversion = [converted.value, converted.unit, converted.how]
    except parameter_units.ConversionError as exc:
        conversion = _error(exc)
    try:
        path = pksim_paths.pksim_parameter_path(_record(cpf_id), compound="Drug")
    except pksim_paths.ParameterPathError as exc:
        path = _error(exc)
    satisfied = set(EMPTY.missing_ids) - set(
        check_completeness(CPF(compound="Drug", parameters=(_record(cpf_id),))).missing_ids)
    item = EvidenceItem(id="ev-characterization", target=cpf_id, source_type=SourceType.PUBLICATION)
    return {
        "placement": inputs.placement(cpf_id),
        "target_problem": inputs.target_problem(cpf_id),
        "storage_family": "not converted" if family is False else family,
        "to_storage_unit(1, no unit)": conversion,
        "numeric": evidence.numeric_target(cpf_id),
        "process_id": process_bindings.is_process_id(cpf_id),
        "binding_candidates": [[c.process, c.parameter, c.unit, c.molecule]
                               for c in process_bindings.binding_candidates(cpf_id)],
        "compound_path": path,
        "physical_bounds": list(evidence._PHYSICAL[cpf_id]) if cpf_id in evidence._PHYSICAL else None,
        "value_origin_method": inputs.value_origin_method(item),
        "s0_satisfies": sorted(satisfied),
    }


def vocabulary() -> dict:
    tables = {
        "parameter_units._TARGETS": parameter_units._TARGETS,
        "parameter_units._FAMILIES": parameter_units._FAMILIES,
        "parameter_units._UNITLESS": parameter_units._UNITLESS,
        "parameter_units._BOUND": parameter_units._BOUND,
        "parameter_units._UNBOUND": parameter_units._UNBOUND,
        "pksim_paths._COMPOUND_PARAM": pksim_paths._COMPOUND_PARAM,
        "pksim_paths._MOLECULE_PROCESSES": pksim_paths._MOLECULE_PROCESSES,
        "pksim_paths._NESTED_PROCESSES": pksim_paths._NESTED_PROCESSES,
        "process_bindings._FIXED_PREFIX": process_bindings._FIXED_PREFIX,
        "build.REFERENCE_ELIMINATION": build.REFERENCE_ELIMINATION,
        "build._PROCESS_FAMILIES": build._PROCESS_FAMILIES,
        "build.ALTERNATIVE_GROUP_OF_ID": build.ALTERNATIVE_GROUP_OF_ID,
        "inputs.MODEL_IDS": inputs.MODEL_IDS,
        "inputs.MODEL_PREFIXES": inputs.MODEL_PREFIXES,
        "inputs.REFERENCE_IDS": inputs.REFERENCE_IDS,
        "inputs.REFERENCE_PREFIXES": inputs.REFERENCE_PREFIXES,
        "inputs.PLACEHOLDERS": inputs.PLACEHOLDERS,
        "inputs.PATHWAY_TARGETS": inputs.PATHWAY_TARGETS,
        "inputs._BUILDER_UNIT": inputs._BUILDER_UNIT,
        "inputs._IN_VIVO": inputs._IN_VIVO,
        "inputs._IN_VITRO": inputs._IN_VITRO,
        "evidence._PHYSICAL": evidence._PHYSICAL,
        "map.STAGE_PLAN": {stage: {"fit_candidates": plan["fit_candidates"], "branches": plan["branches"]}
                           for stage, plan in STAGE_PLAN.items()},
        "templates_api._BLANK_PARAMETERS": _BLANK_PARAMETERS,
    }
    return {
        "tables": _plain(tables),
        "s0_on_an_empty_cpf": {"missing": list(EMPTY.missing), "missing_ids": list(EMPTY.missing_ids)},
        "ids": {cpf_id: answers(cpf_id) for cpf_id in corpus()},
    }


def _render(data: dict) -> str:
    return json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def test_parameter_vocabulary_is_unchanged():
    current = vocabulary()
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        SNAPSHOT.write_text(_render(current), encoding="utf-8")
    recorded = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    current = json.loads(_render(current))
    changed = [f"~ table {k}" for k in sorted(recorded["tables"].keys() | current["tables"].keys())
               if recorded["tables"].get(k) != current["tables"].get(k)]
    if recorded["s0_on_an_empty_cpf"] != current["s0_on_an_empty_cpf"]:
        changed.append("~ the S0 report on an empty CPF")
    for cpf_id in sorted(recorded["ids"].keys() | current["ids"].keys()):
        old, new = recorded["ids"].get(cpf_id), current["ids"].get(cpf_id)
        if old is None or new is None:
            changed.append(f"{'+' if old is None else '-'} id {cpf_id}")
        else:
            changed += [f"~ {cpf_id}: {k} {old.get(k)!r} -> {new.get(k)!r}" for k in sorted(old.keys() | new.keys())
                        if old.get(k) != new.get(k)]
    assert not changed, ("the parameter vocabulary changed (a science change needs the owner's approval and a CHANGELOG "
                         "entry; then UPDATE_SNAPSHOTS=1):\n  " + "\n  ".join(changed))


def test_corpus_covers_every_table_entry():
    ids = set(corpus())
    assert set(inputs.MODEL_IDS) | set(pksim_paths._COMPOUND_PARAM) | set(evidence._PHYSICAL) <= ids
    assert all(any(i == p or i.startswith(p) for i in ids) for p, _ in parameter_units._TARGETS)
    assert all(any(i.startswith(p) for i in ids) for p in (*inputs.MODEL_PREFIXES, *inputs.REFERENCE_PREFIXES))
