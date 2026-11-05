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
import re
from dataclasses import asdict
from typing import Any

from modeler_project.artifacts import ArtifactKind
from modeler_project.evidence import EvidenceItem, Extraction, SourceRef, SourceType, new_id
from modeler_project.workspace import Workspace
from pbpk_domain.dissolution import (
    ENGINE_CHECK,
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


def _name(name: str, aliases: dict[str, str]) -> str:
    """A product or batch name as the register matches it: the name a person linked it to, then case, spaces and
    punctuation aside (plan 2026-11-03 §3.4: one product or batch, however the files write it)."""
    return re.sub(r"[^A-Z0-9]", "", str(aliases.get(name, name)).upper())


def identity(key: ProfileKey, aliases: dict[str, dict[str, str]] | None = None) -> tuple[Any, ...]:
    """What makes two profiles one: the same product and batch (by `_name`), role, strength and test conditions."""
    aliases = aliases or {}
    def text(v: Any) -> str:
        return " ".join(str(v or "").lower().split())

    return (_name(key.product, aliases.get("product", {})), key.role.upper(), key.strength_mg,
            _name(key.batch, aliases.get("batch", {})), text(key.apparatus), key.rpm, text(key.medium), key.ph, key.volume_ml)


def _aliases(ws: Workspace) -> dict[str, dict[str, str]]:
    from modeler_project.client_data import review_record

    record = review_record(ws)
    return {"product": record.get("product_aliases", {}), "batch": record.get("batch_aliases", {})}


def _given(ws: Workspace) -> list[tuple[Profile, Any]]:
    """Every profile each client file gives, oldest file first, with the file's record."""
    from modeler_project.client_data import submissions

    versions = [ws.latest(ArtifactKind.CLIENT_SUBMISSION, sub["id"]) for sub in submissions(ws)
                if sub.get("dissolution") or sub.get("dissolution_records")]
    first_seen = {v.id: ws.versions(ArtifactKind.CLIENT_SUBMISSION, v.id)[0].created_at for v in versions}
    out = []
    for version in sorted(versions, key=lambda v: first_seen[v.id]):
        from_rows, _p1 = profiles_from_rows(version.content.get("dissolution", []))
        from_records, _p2 = profiles_from_records(version.content.get("dissolution_records", []))
        out += [(profile, version) for profile in from_rows + from_records]
    return out


def by_file(ws: Workspace) -> dict[ProfileKey, list[tuple[Profile, str, str]]]:
    """Each profile (same product, batch and conditions, however the files write the names) with the client files that
    give it, oldest file first: the profile as that file gives it, the file's submission id and its name. Keyed by the
    first file's key, whose id the register keeps."""
    aliases = _aliases(ws)
    first: dict[tuple[Any, ...], ProfileKey] = {}
    out: dict[ProfileKey, list[tuple[Profile, str, str]]] = {}
    for profile, version in _given(ws):
        key = first.setdefault(identity(profile.key, aliases), profile.key)
        out.setdefault(key, []).append((profile, version.id, version.content["file"]))
    return out


def rebuild(ws: Workspace, *, by: str) -> list[dict[str, Any]]:
    """Profiles and comparisons from every client file (idempotent: unchanged content keeps its version). When a profile
    (same product, batch and conditions) arrives in a later file too, the later file's data replace the earlier, unless
    a person selected the file to keep on Inputs (plan 2026-11-03 §3.4, I3: a contradiction is settled by a person and
    the choice is kept in the review record's `profile_sources`)."""
    from modeler_project.client_data import review_record, submissions

    latest: dict[tuple[Any, ...], tuple[Profile, Any]] = {}
    first: dict[tuple[Any, ...], ProfileKey] = {}       # the id stays the first file's, however later files write it
    problems: list[str] = []
    keep = review_record(ws).get("profile_sources", {})
    aliases = _aliases(ws)
    for sub in submissions(ws):
        if sub.get("dissolution") or sub.get("dissolution_records"):
            version = ws.latest(ArtifactKind.CLIENT_SUBMISSION, sub["id"])
            _r, p1 = profiles_from_rows(version.content.get("dissolution", []))
            _d, p2 = profiles_from_records(version.content.get("dissolution_records", []))
            problems += [f"{version.content['file']}: {p}" for p in p1 + p2]
    for profile, version in _given(ws):
        same = identity(profile.key, aliases)
        key = first.setdefault(same, profile.key)
        if same in latest:
            kept = keep.get(profile_id(key))
            if kept == latest[same][1].id:
                problems.append(f"{key.label()}: {latest[same][1].content['file']} kept over "
                                f"{version.content['file']} (selected on Inputs)")
                continue
            problems.append(f"{key.label()}: {version.content['file']} replaces {latest[same][1].content['file']}")
        latest[same] = (profile, version)
    if not latest:
        return []
    out = []
    for same, (profile, version) in latest.items():
        saved = ws.commit(ArtifactKind.DISSOLUTION, profile_id(first[same]), _content(profile, [version.content["file"]]),
                          derived_from=[version.ref], actor=by, reason=f"profile {profile.key.label()}")
        out.append(saved.content | {"id": saved.id})
    built_ids = {profile_id(k) for k in first.values()}
    for stale in ws.list(ArtifactKind.DISSOLUTION):   # a spelling now matched to another's profile is retired, not erased
        if stale.id not in built_ids and stale.id != COMPARISONS and not stale.content.get("retired"):
            ws.commit(ArtifactKind.DISSOLUTION, stale.id, {**stale.content, "retired": "the same product and batch as "
                      "another profile, written another way: merged into it"}, actor=by, reason=f"profile {stale.id} merged")
    built = [(p, profile_id(first[same])) for same, (p, _v) in latest.items()]
    pairs = []
    for test, test_id in ((p, i) for p, i in built if p.key.role == "TEST"):
        for reference, reference_id in ((p, i) for p, i in built if p.key.role in REFERENCE_ROLES):
            if test.key.condition() == reference.key.condition():
                pairs.append({"test": test_id, "reference": reference_id,
                              "condition": f"{test.key.medium}" + (f" pH {test.key.ph:g}" if test.key.ph is not None else ""),
                              **f2(test, reference).to_content()})
    used = sorted({v.ref for _p, v in latest.values()}, key=lambda r: r.id)
    ws.commit(ArtifactKind.DISSOLUTION, COMPARISONS, {"comparisons": pairs, "problems": problems}, derived_from=used,
              actor=by, reason="test vs reference")
    return out


def profiles(ws: Workspace) -> list[dict[str, Any]]:
    return [v.content | {"id": v.id, "version": v.version} for v in ws.list(ArtifactKind.DISSOLUTION)
            if v.id != COMPARISONS and not v.content.get("retired")]


def comparisons(ws: Workspace) -> dict[str, Any]:
    version = ws.latest(ArtifactKind.DISSOLUTION, COMPARISONS)
    return version.content if version else {"comparisons": [], "problems": []}


def propose_release_model(ws: Workspace, pid: str, *, formulation: str, by: str) -> list[EvidenceItem]:
    """A person proposes a profile as a formulation's release model: its fitted Weibull values (or "Dissolved" for a
    rapidly dissolving product) become evidence (extraction COMPUTED, grade C), with the profile, the function version
    and the fit's quality as conditions. A plateau below complete release is refused: it needs a table formulation."""
    from modeler_project.evidence_register import propose

    version = ws.latest(ArtifactKind.DISSOLUTION, pid)
    if version is None or pid == COMPARISONS or version.content.get("retired"):
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
        if ENGINE_CONFIRMED:
            conditions["engine check"] = ENGINE_CHECK
        flags = () if ENGINE_CONFIRMED else ("unconfirmed: the Weibull equation is not yet compared with PK-Sim's own release curve",)
        items = [EvidenceItem(id=new_id(), target=f"form.{name}.type", value="Weibull", quote=quote, conditions=conditions, **common)]
        for key, value, unit in (("t50", fit["t50_min"], "min"), ("shape", fit["shape"], None), ("lag", fit["lag_min"], "min")):
            items.append(EvidenceItem(id=new_id(), target=f"form.{name}.weibull.{key}", value=value, unit=unit, quote=quote,
                                      conditions=conditions, flags=flags, **common))
    return [propose(ws, item, actor=by, value_in_quote=True) for item in items]
