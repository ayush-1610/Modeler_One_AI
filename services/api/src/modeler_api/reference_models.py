"""The published OSP models the platform carries, and the other project starting points (services, not a router).

The Inputs step takes a published model's values and datasets as a source (`evidence:published-model`). A starting
point's content (`starting_point`: its CPF and studies) is what scripts build a project from: the showcase seeder, the
reference runs and the e2e specs (the `/templates` routes that served it are retired, the console redesign's slice 9).
The snapshots are the OSP reference files harvested for the engine catalog (T-02). The published one is imported on
request (`pbpk_domain.reference`): its CPF and its real clinical studies, straight from the peer-reviewed snapshot. The
illustrative one is a small hand-made set kept for a fast software check of the pipeline; it says so in its label and
in every study's reference, so its numbers are never mistaken for evidence.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from modeler_api.config import Settings

_HERE = Path(__file__).resolve().parent
# The OSP reference snapshots harvested for the engine catalog (T-02); the repo layout is the same on the server.
DEFAULT_REFERENCE_DIR = _HERE.parents[2] / "engine-worker" / "golden" / "fixtures"

# Compounds a published model names otherwise than the drug (the CPF, the project and PK-Sim paths use this name).
_MODEL_COMPOUND = {"Ketoconazole": "ketoconazole", "Voriconazole": "Voriconazole1"}

TEMPLATES: dict[str, dict[str, Any]] = {
    "dapagliflozin-osp": {
        "name": "Dapagliflozin — published OSP model, real clinical data",
        "compound": "Dapagliflozin",
        "question": "Predict dapagliflozin plasma exposure (AUC, Cmax) after 10 mg once daily in healthy adults",
        "model_risk": "medium",
        "real_data": True,
        "snapshot": "Dapagliflozin-Model.json",
        "description": "The peer-reviewed OSP Dapagliflozin PBPK model and the clinical studies it was built and "
                       "qualified on (13 publications: IV microdose, solution, capsules, tablet, fed, multiple dose, "
                       "renal impairment). Runs the whole MS-01 pipeline on real data.",
    },
    **{f"{name.lower()}-osp": {
        "name": f"{name} — published OSP model, real clinical data",
        "compound": _MODEL_COMPOUND.get(name, name),  # as the published model names it (its CPF's compound)
        "question": f"Predict {name.lower()} plasma exposure (AUC, Cmax) in healthy adults",
        "model_risk": "medium",
        "real_data": True,
        "snapshot": f"{name}-Model.json",
        "description": f"The peer-reviewed OSP {name} PBPK model ({topic}) and the clinical studies it was built and "
                       "qualified on, imported from its published snapshot. Runs the whole MS-01 pipeline on real data.",
    } for name, topic in (
        # single-compound OSP library models that import S0-ready (deploy/reference/portfolio.py); the models that
        # need several compounds (Dabigatran, Omeprazole, Verapamil) wait for multi-compound projects in the UI
        ("Rifampicin", "saturable AADAC metabolism, OATP1B1 / P-gp transport, auto-induction"),
        ("Midazolam", "CYP3A4 / UGT1A4 metabolism, GABRG2 binding, tablet and solution"),
        ("Alfentanil", "CYP3A4 metabolism, IV bolus and oral"),
        ("Alprazolam", "CYP3A4 metabolism"),
        ("Clarithromycin", "CYP3A4 metabolism and mechanism-based inhibition, renal clearance"),
        ("Digoxin", "P-gp transport, glomerular filtration, hepatic clearance"),
        ("Metformin", "OCT1 / OCT2 / MATE1 / PMAT transport, fed studies"),
        ("Raltegravir", "UGT1A1 / UGT1A9 metabolism, tablet and granule formulations"),
        ("Ketoconazole", ("particle dissolution, fed permeability; parent only here: the published model's metabolites "
                          "inhibit its CYP3A4 / P-gp clearance, so this differs from it by design")),
        ("Voriconazole", "CYP2C19 / CYP3A4 metabolism, loading-dose regimens, pH-solubility table"),
        ("Itraconazole", "CYP3A4 metabolism, solubility per product and food state; parent only here"),
    )},
    "own-compound": {
        "name": "Your own compound — enter its parameters and clinical data",
        "compound": "MyCompound",
        "question": "Predict plasma exposure (AUC, Cmax) of the compound in healthy adults",
        "model_risk": "medium",
        "real_data": False,
        "blank": True,
        "description": "Starts from the parameters the S0 readiness gate requires (molecular weight, lipophilicity, pKa or "
                       "neutral, fraction unbound, solubility, an elimination pathway), each marked missing: fill in the "
                       "values with their sources, add further processes, then load your studies (CSV) and run.",
    },
    "aciclovir-illustrative": {
        "name": "Aciclovir — illustrative quick check (not clinical data)",
        "compound": "Aciclovir",
        "question": "First-in-human renal starting dose from IV disposition",
        "model_risk": "medium",
        "real_data": False,
        "file": "aciclovir_illustrative.json",
        "description": "One hand-made IV profile for a fast software check of the pipeline. Not evidence of "
                       "anything: use the published template to test the modelling.",
    },
}


def reference_dir(settings: Settings) -> Path:
    configured = settings.reference_models_dir
    return Path(configured) if configured else DEFAULT_REFERENCE_DIR


def model_name(spec: dict[str, Any]) -> str:
    """The drug a published model is of, as its name gives it ("Dapagliflozin — published OSP model …")."""
    return str(spec["name"]).split(" —", 1)[0].strip()


def published_models(drug: str) -> list[tuple[str, dict[str, Any]]]:
    """The published OSP models of this drug (by name, ignoring case)."""
    return [(tid, spec) for tid, spec in TEMPLATES.items()
            if "snapshot" in spec and model_name(spec).casefold() == drug.strip().casefold()]


def snapshot(spec: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """The model's PK-Sim snapshot. FileNotFoundError when it is not installed where the settings say."""
    path = reference_dir(settings) / spec["snapshot"]
    if not path.is_file():
        raise FileNotFoundError(f"reference model {spec['snapshot']} is not installed at {path.parent}")
    return json.loads(path.read_text(encoding="utf-8"))


# --- a starting point's content ---------------------------------------------------------------------------------------


@lru_cache(maxsize=8)
def _published(snapshot_path: str) -> dict[str, Any]:
    from pbpk_domain.reference import import_osp_snapshot

    imported = import_osp_snapshot(json.loads(Path(snapshot_path).read_text(encoding="utf-8")))
    if imported.unplaced:
        raise ValueError("the model has parts the builder cannot place: " + "; ".join(imported.unplaced))
    return {
        "cpf": imported.cpf.model_dump(mode="json", exclude={"created_at"}),
        # the clinical data the published model was built and qualified with (plan §9.4)
        "studies": [{**study, "origin": "OSP_LIBRARY"} for study in imported.studies],
        "skipped": list(imported.skipped),
        "notes": list(imported.notes),
        "source": imported.source,
    }


# The S0 gate's parameters (pbpk_domain.cpf.completeness), empty: a user's own compound starts from these. The
# elimination pathway is PK-Sim's total hepatic clearance, bound as the OSP models bind it (harvested: OSP Digoxin
# "Total Hepatic Clearance", LiverClearance "Plasma clearance" in ml/min/kg); other processes are added as records.
_BLANK_PARAMETERS = (("phys.mw", "g/mol", None), ("phys.logp", "Log Units", None), ("phys.pka.neutral", None, None),
                     ("bind.fu", None, None), ("phys.solubility.ref", "mg/ml", None),
                     ("elim.hepatic.total.plasma_clearance", "ml/min/kg",
                      {"building_block": "Compound", "parameter": "Plasma clearance", "process": "LiverClearance",
                       "data_source": "Literature"}))


def _content(template_id: str, spec: dict[str, Any], settings: Settings) -> dict[str, Any]:
    if spec.get("blank"):
        cpf = {"compound": spec["compound"], "parameters": [
            {"id": pid, "value": None, "unit": unit, "status": "MISSING", **({"engine_binding": eb} if eb else {})}
            for pid, unit, eb in _BLANK_PARAMETERS]}
        return {"cpf": cpf, "studies": [], "skipped": [], "notes": [], "source": "your own data"}
    if "snapshot" in spec:
        path = reference_dir(settings) / spec["snapshot"]
        if not path.is_file():
            raise FileNotFoundError(f"reference model {spec['snapshot']} is not installed at {path.parent}")
        try:
            return _published(str(path))
        except ValueError as exc:
            raise ValueError(f"starting point {template_id}: {exc}") from exc
    data = json.loads((_HERE / "templates" / spec["file"]).read_text(encoding="utf-8"))
    # hand-made example data: it runs the pipeline but is never evidence (plan §9.4 item 4)
    studies = [{**study, "origin": "ILLUSTRATIVE"} for study in data["studies"]]
    return {"cpf": data["cpf"], "studies": studies, "skipped": [], "notes": [], "source": "illustrative"}


def _summary(template_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    return {"id": template_id, "blank": bool(spec.get("blank")),
            **{k: spec[k] for k in ("name", "compound", "question", "model_risk", "real_data", "description")}}


def starting_points() -> list[dict[str, Any]]:
    """Every starting point's summary, the published real-data model first."""
    return [_summary(tid, spec) for tid, spec in TEMPLATES.items()]


def starting_point(template_id: str, settings: Settings) -> dict[str, Any]:
    """One starting point in full: its summary, the CPF, the studies in the upload shape, and what was left out and
    why. KeyError for an unknown id; FileNotFoundError when its snapshot is not installed; ValueError when the
    builder cannot place a part of the model."""
    spec = TEMPLATES[template_id]
    return _summary(template_id, spec) | _content(template_id, spec, settings)
