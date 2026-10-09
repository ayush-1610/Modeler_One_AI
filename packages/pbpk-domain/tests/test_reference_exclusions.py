"""Recorded dataset exclusions of published OSP models (MS-01 D5; the owner's decision on Rifampicin, 2026-10-09)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pbpk_domain.reference import import_osp_snapshot
from pbpk_domain.reference.exclusions import exclusions

pytestmark = pytest.mark.req("T-03")

FIXTURES = Path(__file__).resolve().parents[3] / "services" / "engine-worker" / "golden" / "fixtures"
STONE = "Stone 2004 - Day 14 of Rifampin alone - Rifampicin - PO - 600 mg - Plasma - agg. (n=26)"


def test_every_exclusion_names_a_dataset_its_model_carries_and_says_why():
    for e in exclusions():
        snapshot = json.loads((FIXTURES / f"{e.model}-Model.json").read_text(encoding="utf-8"))
        assert e.dataset in {d["Name"] for d in snapshot["ObservedData"]}, e.dataset
        assert e.reason and e.decided_by and e.decided_at


def test_rifampicin_imports_without_stone_2004_and_says_so():
    snapshot = json.loads((FIXTURES / "Rifampicin-Model.json").read_text(encoding="utf-8"))
    before = len(snapshot["ObservedData"])
    imported = import_osp_snapshot(snapshot)
    assert not [s for s in imported.studies if s["study_id"].startswith("stone-2004")]
    line = next(s for s in imported.skipped if s.startswith(STONE))
    assert "excluded (owner, 2026-10-09, D5)" in line and "1000x" in line
    assert len(snapshot["ObservedData"]) == before  # the published snapshot itself is untouched


def test_a_model_without_exclusions_imports_as_before():
    snapshot = json.loads((FIXTURES / "Dapagliflozin-Model.json").read_text(encoding="utf-8"))
    from pbpk_domain.reference.osp_import import import_osp_snapshot as raw

    ours, theirs = import_osp_snapshot(snapshot), raw(snapshot)
    assert (ours.studies, ours.skipped, ours.notes) == (theirs.studies, theirs.skipped, theirs.notes)
