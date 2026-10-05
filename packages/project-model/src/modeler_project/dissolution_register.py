"""Dissolution in the project (plan §10.3, T-48): canonical profiles from the client files, their checks and Weibull
fits, f2 between test and reference, and the release model a person proposes from a profile.

Profiles are DISSOLUTION artifacts (``diss-<key hash>``), rebuilt from every client file whenever one arrives or a
mapping is confirmed; an unchanged profile keeps its version. The comparisons (``DISSOLUTION/comparisons``) pair each
TEST profile with the RLD / REFERENCE profile measured under the same conditions. Which profile represents in vivo
release (biorelevant vs QC medium, one batch or pooled) is a planning decision (D-12): nothing becomes a CPF value
until a person proposes a profile's fit as a formulation's release model and the evidence is accepted.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from modeler_project.artifacts import ArtifactKind
from modeler_project.evidence import EvidenceItem, Extraction, SourceRef, SourceType, new_id
from modeler_project.workspace import Workspace
from pbpk_domain.dissolution import (
    ENGINE_CONFIRMED,
    EQUATION,
    FUNCTION_VERSION,
    Profile,
    ProfileKey,
    check_profile,
    f2,
    fit_weibull,
    profiles_from_records,
    profiles_from_rows,
)

COMPARISONS = "comparisons"
REFERENCE_ROLES = ("RLD", "REFERENCE")


class DissolutionRegisterError(ValueError):
    pass


def profile_id(key: ProfileKey) -> str:
    return "diss-" + hashlib.sha256(json.dumps(asdict(key), sort_keys=True, default=str).encode()).hexdigest()[:10]


def _content(profile: Profile, sources: list[str]) -> dict[str, Any]:
    flags, release = check_profile(profile)
    fit = fit_weibull(profile) if release == "Weibull" else None
    return {
        "key": asdict(profile.key), "label": profile.key.label(), "times_min": list(profile.times_min),
        "vessels": [list(v) for v in profile.vessels], "mean": [round(m, 4) for m in profile.mean],
        "sd": [None if s is None else round(s, 4) for s in profile.sd],
        "cv": [None if c is None else round(c, 2) for c in profile.cv], "n": profile.n, "cells": list(profile.cells),
        "flags": flags, "release_model": release, "fit": fit.to_content() if fit else None, "files": sources,
    }


def rebuild(ws: Workspace, *, by: str) -> list[dict[str, Any]]:
    """Profiles and comparisons from every client file (idempotent: unchanged content keeps its version). When a profile
    (same product, batch and conditions) arrives in a later file too, the later file's data replace the earlier."""
    from modeler_project.client_data import submissions

    latest: dict[ProfileKey, tuple[Profile, Any]] = {}
    problems: list[str] = []
    versions = [ws.latest(ArtifactKind.CLIENT_SUBMISSION, sub["id"]) for sub in submissions(ws)
                if sub.get("dissolution") or sub.get("dissolution_records")]
    first_seen = {v.id: ws.versions(ArtifactKind.CLIENT_SUBMISSION, v.id)[0].created_at for v in versions}
    for version in sorted(versions, key=lambda v: first_seen[v.id]):
        from_rows, p1 = profiles_from_rows(version.content.get("dissolution", []))
        from_records, p2 = profiles_from_records(version.content.get("dissolution_records", []))
        problems += [f"{version.content['file']}: {p}" for p in p1 + p2]
        for profile in from_rows + from_records:
            if profile.key in latest:
                problems.append(f"{profile.key.label()}: {version.content['file']} replaces {latest[profile.key][1].content['file']}")
            latest[profile.key] = (profile, version)
    if not latest:
        return []
    out = []
    for profile, version in latest.values():
        saved = ws.commit(ArtifactKind.DISSOLUTION, profile_id(profile.key), _content(profile, [version.content["file"]]),
                          derived_from=[version.ref], actor=by, reason=f"profile {profile.key.label()}")
        out.append(saved.content | {"id": saved.id})
    built = [p for p, _v in latest.values()]
    pairs = []
    for test in (p for p in built if p.key.role == "TEST"):
        for reference in (p for p in built if p.key.role in REFERENCE_ROLES):
            if test.key.condition() == reference.key.condition():
                pairs.append({"test": profile_id(test.key), "reference": profile_id(reference.key),
                              "condition": f"{test.key.medium}" + (f" pH {test.key.ph:g}" if test.key.ph is not None else ""),
                              **f2(test, reference).to_content()})
    used = sorted({v.ref for _p, v in latest.values()}, key=lambda r: r.id)
    ws.commit(ArtifactKind.DISSOLUTION, COMPARISONS, {"comparisons": pairs, "problems": problems}, derived_from=used,
              actor=by, reason="test vs reference")
    return out


def profiles(ws: Workspace) -> list[dict[str, Any]]:
    return [v.content | {"id": v.id, "version": v.version} for v in ws.list(ArtifactKind.DISSOLUTION) if v.id != COMPARISONS]


def comparisons(ws: Workspace) -> dict[str, Any]:
    version = ws.latest(ArtifactKind.DISSOLUTION, COMPARISONS)
    return version.content if version else {"comparisons": [], "problems": []}


def propose_release_model(ws: Workspace, pid: str, *, formulation: str, by: str) -> list[EvidenceItem]:
    """A person proposes a profile as a formulation's release model: its fitted Weibull values (or "Dissolved" for a
    rapidly dissolving product) become evidence (extraction COMPUTED, grade C), with the profile, the function version
    and the fit's quality as conditions. A plateau below complete release is refused: it needs a table formulation."""
    from modeler_project.evidence_register import propose

    version = ws.latest(ArtifactKind.DISSOLUTION, pid)
    if version is None or pid == COMPARISONS:
        raise DissolutionRegisterError(f"no dissolution profile {pid}")
    name = formulation.strip()
    if not name or "." in name:
        raise DissolutionRegisterError("name the formulation (no dots: it becomes part of form.<name>.weibull.*)")
    content = version.content
    source = SourceRef(locator=f"{pid} v{version.version}: {content['label']}", title=", ".join(content["files"]))
    common = {"source_type": SourceType.CLIENT_FILE, "source": source, "extraction": Extraction.COMPUTED, "provider": "CLIENT",
              "purpose": "model_building"}
    if content["release_model"] == "Table":
        raise DissolutionRegisterError("the profile plateaus below complete release: a Weibull curve cannot represent it, "
                                       "and table formulations are not placed by the builder yet")
    if content["release_model"] == "Dissolved":
        quote = f"{content['label']}: ≥ 85 % dissolved within 15 min (rapidly dissolving, MS-01 §4 S2)"
        items = [EvidenceItem(id=new_id(), target=f"form.{name}.type", value="Dissolved", quote=quote, **common)]
    else:
        fit = content["fit"] or {}
        if not fit.get("converged") or fit.get("t50_min") is None:
            raise DissolutionRegisterError(f"the Weibull fit did not converge ({fit.get('note') or 'no fit'})")
        quote = (f"{FUNCTION_VERSION} fit of {content['label']} (n = {fit['n_points']} points, RMSE {fit['rmse_percent']} %): "
                 f"t50 = {fit['t50_min']} min, shape = {fit['shape']}, lag = {fit['lag_min']} min")
        conditions = {"profile": f"{pid} v{version.version}", "function": FUNCTION_VERSION, "equation": EQUATION,
                      "fit": f"SE t50 {fit['se_t50']}, SE shape {fit['se_shape']}"}
        flags = () if ENGINE_CONFIRMED else ("unconfirmed: the Weibull equation is not yet compared with PK-Sim's own release curve",)
        items = [EvidenceItem(id=new_id(), target=f"form.{name}.type", value="Weibull", quote=quote, conditions=conditions, **common)]
        for key, value, unit in (("t50", fit["t50_min"], "min"), ("shape", fit["shape"], None), ("lag", fit["lag_min"], "min")):
            items.append(EvidenceItem(id=new_id(), target=f"form.{name}.weibull.{key}", value=value, unit=unit, quote=quote,
                                      conditions=conditions, flags=flags, **common))
    return [propose(ws, item, actor=by, value_in_quote=True) for item in items]
