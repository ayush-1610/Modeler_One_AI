"""T-48: dissolution profiles from client files, f2 test vs reference, and a release model proposed from a fit."""

from __future__ import annotations

import io

import numpy as np
import pytest
from openpyxl import load_workbook

from modeler_intake.client_template import build_template
from modeler_project import ArtifactKind, FileProjectStore, Workspace
from modeler_project.client_data import ingest
from modeler_project.dissolution_register import (
    DissolutionRegisterError,
    comparisons,
    profiles,
    propose_release_model,
)
from modeler_project.documents import DocumentLibrary
from modeler_project.evidence_register import items
from pbpk_domain.dissolution import weibull_fraction

pytestmark = pytest.mark.req("T-48")
TIMES = (5, 10, 15, 20, 30, 45, 60)


def _workbook(note: str = "") -> bytes:
    wb = load_workbook(io.BytesIO(build_template()))
    wb["README"].append([note])
    curves = {("Test 10 mg", "TEST"): weibull_fraction(np.array(TIMES), 18.0, 1.3),
              ("Brand 10 mg", "RLD"): weibull_fraction(np.array(TIMES), 20.0, 1.3),
              ("Slow 10 mg", "OTHER"): np.array([0.20, 0.35, 0.45, 0.52, 0.60, 0.61, 0.615])}
    for (product, role), fraction in curves.items():
        for t, f in zip(TIMES, fraction, strict=True):
            vessels = [round(100 * float(f) + d, 3) for d in np.linspace(-1.5, 1.5, 12)]
            wb["Dissolution"].append([product, role, 10, "B1", "USP 2 paddle", 50, "phosphate", 6.8, 900, 37, None, t, "min",
                                      *vessels])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_profiles_are_built_fitted_and_compared_from_the_client_file(tmp_path):
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    data = _workbook()
    ingest(ws, DocumentLibrary(ws), data, "dissolution.xlsx", by="u")
    found = {p["key"]["product"]: p for p in profiles(ws)}
    test, slow = found["Test 10 mg"], found["Slow 10 mg"]
    assert test["n"] == 12 and test["times_min"] == list(TIMES) and test["release_model"] == "Weibull"
    assert test["fit"]["t50_min"] == pytest.approx(18.0, rel=0.01) and test["fit"]["shape"] == pytest.approx(1.3, rel=0.02)
    assert test["fit"]["engine_confirmed"] is True and test["cells"][0].startswith("Dissolution!")
    assert slow["release_model"] == "Table" and slow["fit"] is None
    pair = comparisons(ws)["comparisons"]
    assert len(pair) == 1 and pair[0]["applicable"] and pair[0]["similar"] and pair[0]["f2"] > 50
    assert pair[0]["condition"] == "phosphate pH 6.8"

    proposed = propose_release_model(ws, test["id"], formulation="Test10", by="u")
    by_target = {e.target: e for e in proposed}
    assert by_target["form.Test10.type"].value == "Weibull"
    t50 = by_target["form.Test10.weibull.t50"]
    assert t50.value_pksim == pytest.approx(test["fit"]["t50_min"]) and t50.unit_pksim == "min" and t50.confidence == "C"
    # the equation is confirmed on PK-Sim (dissolution.ENGINE_CHECK): no "unconfirmed" flag, and the check is cited
    assert not any(f.startswith("unconfirmed") for f in t50.flags)
    assert "engine-image run" in t50.conditions["engine check"]
    assert len(items(ws)) == 4
    # with a release-model item in the data plan, the proposed values serve it rather than arrive unpromised
    from modeler_project.brief import Citation, FieldStatus, empty_brief
    from modeler_project.brief_ops import agent_set
    from modeler_project.client_data import reconcile
    from modeler_project.requirements import derive

    brief = empty_brief("X", by="u")
    for path, value in (("products[0].name", "Test 10 mg"), ("products[0].role", "TEST"), ("products[0].dosage_form", "tablet"),
                        ("data_plan[0].item", "dissolution"), ("data_plan[0].category", "dissolution"),
                        ("data_plan[0].provider", "CLIENT")):
        brief = agent_set(brief, path, value=value, unit=None, citations=(Citation(doc_sha256="a" * 64, page=1, quote="q" * 12),),
                          status=FieldStatus.EXTRACTED, confidence="A", by="a1")
    recon = reconcile(ws, derive(brief))
    assert not any(u.startswith("form.") for u in recon.unpromised)
    with pytest.raises(DissolutionRegisterError, match="plateaus"):
        propose_release_model(ws, slow["id"], formulation="Slow", by="u")
    # the same file again changes nothing; a re-sent workbook (new bytes) replaces the profiles it repeats, noted
    before = {p["id"]: p["version"] for p in profiles(ws)}
    ingest(ws, DocumentLibrary(ws), data, "dissolution.xlsx", by="u")
    assert {p["id"]: p["version"] for p in profiles(ws)} == before
    assert ws.latest(ArtifactKind.DISSOLUTION, "comparisons").version == 1
    ingest(ws, DocumentLibrary(ws), _workbook("re-sent after the assay review"), "dissolution-resent.xlsx", by="u")
    assert {p["files"][0] for p in profiles(ws)} == {"dissolution-resent.xlsx"}
    assert any("dissolution-resent.xlsx replaces dissolution.xlsx" in x for x in comparisons(ws)["problems"])
