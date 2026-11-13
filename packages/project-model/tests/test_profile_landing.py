"""What a dataset carries to the campaign beyond its values (contracts §8.2, D1a; plan 2026-11-12 L-a, L-b, L-d, L-e).

Fidelity first: today's profile, catalog row and PI block of every dataset that hits none of the deliberate changes
(the parent in plasma, an arithmetic SD or no spread, no point below the LLOQ, one n) are pinned literally and checked
against a frozen copy of today's code; the MS-01 split does not move. Then each deliberate change, one test each. Software
test data (made-up numbers, the made-up drug Exampleamide): nothing here is PBPK evidence.
"""

from __future__ import annotations

import io
import itertools
import json
from types import SimpleNamespace
from typing import Any

import pytest
from openpyxl import load_workbook

from modeler_intake.client_template import build_template
from modeler_intake.records import ConcentrationObservation, SourceRef
from modeler_project import ArtifactKind, FileProjectStore, Workspace
from modeler_project.artifacts import ArtifactVersion, content_sha256
from modeler_project.brief import FieldRecord, FieldStatus, empty_brief, set_record
from modeler_project.client_data import datasets_from_observations, ingest
from modeler_project.dataset_register import datasets, decide_dataset, propose_dataset, set_study_facts
from modeler_project.datasets import DatasetError, ObservedDataset, Origin, Series, check_dataset, new_dataset_id
from modeler_project.documents import DocumentLibrary
from modeler_project.evidence import EvidenceState
from modeler_project.inputs import InputChoices, _profile, assemble, dataset_warnings, study_catalog, usable_dataset
from modeler_project.intake_rules import RULES_STATUS, RULES_VERSION, rules
from modeler_project.plan import Structure, _records, build_default, map_from_plan
from modeler_project.profile_landing import (
    blq,
    is_parent,
    judged_as_plasma,
    judged_sd,
    landing_limitations,
    matrix_judgement,
    matrix_key,
    spread_confirmed,
)
from modeler_project.sheet_intake import _points
from pbpk_domain import spread
from pbpk_domain.campaign.split import StudyRecord, split_studies
from pbpk_domain.cpf.models import CPF, EngineBinding, ParameterRecord, ParameterStatus, Provenance
from pbpk_domain.fit_spec import pi_observed
from pbpk_domain.units import normalize_profile

pytestmark = pytest.mark.req("T-49", "T-45", "T-47")
DRUG = "Exampleamide"
NEW_ROW_KEYS = {"measured_analyte", "measured_matrix", "blq_rule", "joined_from"}
NAMED = f"intake rules {RULES_VERSION}, {RULES_STATUS}"
TIMES = (0.5, 1.0, 2.0, 4.0, 8.0)
VALUES = (10.0, 30.0, 22.0, 9.0, 2.5)


# --- today's code, frozen (packages/project-model/src/modeler_project/inputs.py at 045ffc3) ----------------------------


def _today_profile(dataset: ObservedDataset) -> dict[str, Any] | None:
    series = next((s for s in dataset.series if s.statistic != "individual"), None)
    if series is None:
        return None
    pairs = [(t, v, (series.error[i] if series.error is not None else None))
             for i, (t, v) in enumerate(zip(series.times, series.values, strict=True)) if v is not None]
    if not pairs:
        return None
    sd = [e for _t, _v, e in pairs] if series.error_kind == "SD" and all(e is not None for _t, _v, e in pairs) else None
    return {"times": [t for t, _v, _e in pairs], "values": [v for _t, v, _e in pairs], "time_unit": dataset.time_unit,
            "unit": dataset.unit, "sd": sd, "lloq": dataset.study.get("lloq")}


def _today_catalog(ws: Workspace, picked: InputChoices) -> tuple[list[dict[str, Any]], list[str], list[ArtifactVersion]]:
    rows, notes, used = [], [], []
    versions = sorted(ws.list(ArtifactKind.DATASET), key=lambda v: v.created_at)
    usable = [(v, d) for v in versions if usable_dataset(d := ObservedDataset.from_content(v.content))]
    winner: dict[str, str] = {}
    for _v, d in sorted(usable, key=lambda vd: (vd[1].state is not EvidenceState.ACCEPTED, vd[1].provider != "CLIENT",
                                                  vd[0].created_at)):
        winner.setdefault(str(d.study["study_id"]), d.id)
    for version, dataset in usable:
        study = dict(dataset.study)
        sid = study["study_id"]
        if sid in picked.excluded_studies:
            if winner[sid] == dataset.id:
                notes.append(f"{sid}: left out ({picked.excluded_studies[sid]})")
            continue
        if winner[sid] != dataset.id:
            notes.append(f"{sid}: also in {winner[sid]}; {dataset.id} is not used (two datasets for one study)")
            continue
        profile = _today_profile(dataset)
        row: dict[str, Any] = {**study, "origin": dataset.origin.value, "dataset_id": dataset.id,
                               "purpose": dataset.purpose, "evaluable": profile is not None,
                               "demographics_choice": dataset.demographics_choice}
        if profile is not None:
            row["profile"] = profile
        elif dataset.kind == "pk_parameters":
            notes.append(f"{sid}: PK parameters only — it can judge a prediction once the evaluation reads reported NCA; "
                         "it trains no fit")
        else:
            notes.append(f"{sid}: individual profiles only — population evaluation (PE %, GMR, 90 % CI) is the "
                         "evaluation lane's; not judged by the current campaign")
        if study.get("formulation") in ("ir_tablet", "ir_capsule", "mr", "suspension") and sid in picked.formulation:
            row["formulation_name"] = picked.formulation[sid]
        rows.append(row)
        used.append(version)
    return rows, notes, used


# --- helpers -----------------------------------------------------------------------------------------------------------


def _ws(tmp_path, *, synonyms: list[str] | None = None) -> Workspace:
    ws = Workspace(FileProjectStore(tmp_path), "t1", "p1")
    brief = empty_brief(DRUG, by="u")
    if synonyms:
        brief = set_record(brief, "drug.synonyms", FieldRecord(value=synonyms, status=FieldStatus.ENTERED, by="u"))
    ws.commit(ArtifactKind.BRIEF, "main", brief.to_content(), actor="u", reason="start")
    return ws


def _study(sid: str, **extra: Any) -> dict[str, Any]:
    return {"study_id": sid, "reference": "Doe 2019", "n": 18, "route": "oral", "dose_mg": 100, "formulation": "solution",
            "food_state": "fasted", "n_timepoints": 5, **extra}


def _series(statistic: str = "arithmetic_mean", *, values: tuple[float | None, ...] = VALUES, error=None, kind="none",
            n: int | None = 18, n_at=None) -> Series:
    return Series(name="mean", statistic=statistic, times=TIMES[:len(values)], values=values, error=error,
                  error_kind=kind, n=n, n_at=n_at)


def _dataset(sid: str = "doe-po-100", *series: Series, analyte: str = "parent", matrix: str = "plasma",
             study: dict[str, Any] | None = None, time_unit: str = "h", **extra: Any) -> ObservedDataset:
    return ObservedDataset(id=new_dataset_id(), kind="profile", origin=Origin.LITERATURE, time_unit=time_unit, unit="ng/ml",
                           study=study or _study(sid), series=series or (_series(),), analyte=analyte, matrix=matrix,
                           **extra)


def _add(ws: Workspace, dataset: ObservedDataset, *, accept: bool = True) -> ObservedDataset:
    proposed = propose_dataset(ws, dataset, actor="u")
    if accept:
        decide_dataset(ws, proposed.id, state=EvidenceState.ACCEPTED, reason="checked", by="u")
    return proposed


def _catalog(ws: Workspace, parent_names: tuple[str, ...] = (DRUG,)):
    return study_catalog(ws, InputChoices(), parent_names=parent_names)


def _pi(row: dict[str, Any]) -> str:
    """The observed block the campaign writes into the PI spec for a catalog row (plan:sign normalises the profile with
    the parent's MW; _build_fit_request passes the error type the profile names)."""
    p = normalize_profile(row["profile"], 300.0)
    return json.dumps(pi_observed(row["study_id"], p["times"], p["values"], time_unit=p["time_unit"], unit=p["unit"],
                                  mol_weight=300.0, dimension="Concentration (molar)", sd=p.get("sd"), lloq=p.get("lloq"),
                                  error_type=p.get("sd_type")), ensure_ascii=False)


# --- fidelity ----------------------------------------------------------------------------------------------------------


def test_an_unaffected_profile_and_catalog_row_are_todays_dicts(tmp_path):
    ws = _ws(tmp_path)
    with_sd = _add(ws, _dataset("doe-po-100", _series(error=(1.0, 4.0, 3.0, 1.5, 0.4), kind="SD"),
                                study=_study("doe-po-100", lloq=0.2)))
    bare = _add(ws, _dataset("doe-po-50", _series(), study=_study("doe-po-50", dose_mg=50)))
    rows, notes, _used = _catalog(ws)
    assert notes == []
    assert rows == [
        {"study_id": "doe-po-100", "reference": "Doe 2019", "n": 18, "route": "oral", "dose_mg": 100, "formulation": "solution",
         "food_state": "fasted", "n_timepoints": 5, "lloq": 0.2, "origin": "LITERATURE", "dataset_id": with_sd.id,
         "purpose": "model_building", "evaluable": True, "demographics_choice": None,
         "profile": {"times": [0.5, 1.0, 2.0, 4.0, 8.0], "values": [10.0, 30.0, 22.0, 9.0, 2.5], "time_unit": "h",
                     "unit": "ng/ml", "sd": [1.0, 4.0, 3.0, 1.5, 0.4], "lloq": 0.2}},
        {"study_id": "doe-po-50", "reference": "Doe 2019", "n": 18, "route": "oral", "dose_mg": 50, "formulation": "solution",
         "food_state": "fasted", "n_timepoints": 5, "origin": "LITERATURE", "dataset_id": bare.id,
         "purpose": "model_building", "evaluable": True, "demographics_choice": None,
         "profile": {"times": [0.5, 1.0, 2.0, 4.0, 8.0], "values": [10.0, 30.0, 22.0, 9.0, 2.5], "time_unit": "h",
                     "unit": "ng/ml", "sd": None, "lloq": None}},
    ]
    assert [list(r) for r in rows] == [list(r) for r in _today_catalog(ws, InputChoices())[0]]   # the key order too
    # the PI spec's observed blocks, byte for byte as today (no error_type, sd [] when there is none)
    # (the literals were printed by the code at 045ffc3, before this change)
    assert _pi(rows[0]) == (
        '{"name": "doe-po-100", "time": [30.0, 60.0, 120.0, 240.0, 480.0], "time_unit": "min", "values": '
        '[0.03333333333333333, 0.1, 0.07333333333333333, 0.030000000000000002, 0.008333333333333333], "unit": "µmol/l", '
        '"dimension": "Concentration (molar)", "mol_weight": 300.0, "sd": [0.0033333333333333335, 0.013333333333333334, '
        '0.01, 0.005, 0.0013333333333333335], "lloq": 0.0006666666666666668}')
    assert _pi(rows[1]) == (
        '{"name": "doe-po-50", "time": [30.0, 60.0, 120.0, 240.0, 480.0], "time_unit": "min", "values": '
        '[0.03333333333333333, 0.1, 0.07333333333333333, 0.030000000000000002, 0.008333333333333333], "unit": "µmol/l", '
        '"dimension": "Concentration (molar)", "mol_weight": 300.0, "sd": []}')
    assert landing_limitations(rows) == ()


def _unaffected() -> list[ObservedDataset]:
    """Every combination today's catalog sees on a parent plasma profile: an arithmetic SD or none, n one / none, an
    LLOQ or none, literature or client, minutes or hours, a median or a geometric mean with no spread, individuals."""
    out = []
    for k, (kind, n, lloq, statistic) in enumerate(itertools.product(("SD", "none"), (18, None), (0.2, None),
                                                                       ("arithmetic_mean", "median", "geometric_mean"))):
        if kind == "SD" and statistic != "arithmetic_mean":
            continue
        error = (1.0, 4.0, 3.0, 1.5, 0.4) if kind == "SD" else None
        study = _study(f"st-{k}", **({"lloq": lloq} if lloq else {}))
        individual = Series(name="001", statistic="individual", times=TIMES, values=(None, 31.0, 20.0, 8.0, 2.0))
        dataset = _dataset(f"st-{k}", individual, _series(statistic, error=error, kind=kind, n=n), study=study,
                           time_unit="min" if k % 2 else "h")
        if k % 3 == 0:   # a client's dataset, read from its cells
            dataset = dataset.model_copy(update={"origin": Origin.CLIENT, "provider": "CLIENT", "extraction": "CELL"})
        out.append(dataset)
    out.append(_dataset("ind-only", Series(name="001", statistic="individual", times=TIMES, values=VALUES),
                        study=_study("ind-only", lloq=0.2)))
    out.append(ObservedDataset(id=new_dataset_id(), kind="pk_parameters", origin=Origin.LITERATURE, study=_study("pk-only"),
                               reported=({"parameter": "Cmax", "value": 30.0, "unit": "ng/ml"},)))
    return out


def test_todays_catalog_is_unchanged_for_every_dataset_no_deliberate_change_touches(tmp_path):
    """Before / after over a frozen copy of today's code: profiles, rows, notes and the datasets used are equal, and so
    is every PI block; two datasets of one study id and an excluded study keep today's notes."""
    ws = _ws(tmp_path)
    for dataset in _unaffected():
        assert _profile(dataset) == _today_profile(dataset)
        _add(ws, dataset, accept=dataset.study["study_id"] != "st-6")
    # two datasets for one study: a person's accepted one wins over the earlier proposed one, as today
    _add(ws, _dataset("st-0", _series(error=(1.1, 4.1, 3.1, 1.6, 0.5), kind="SD"), study=_study("st-0")), accept=False)
    picked = InputChoices(excluded_studies={"st-3": "a person left it out"})
    rows, notes, used = study_catalog(ws, picked, parent_names=(DRUG,))
    today_rows, today_notes, today_used = _today_catalog(ws, picked)
    assert (rows, notes, [v.ref for v in used]) == (today_rows, today_notes, [v.ref for v in today_used])
    assert any("two datasets for one study" in n for n in notes) and any("left out" in n for n in notes)
    assert not any(NEW_ROW_KEYS & set(r) for r in rows)
    assert {r["study_id"]: _pi(r) for r in rows if r.get("profile")} == {r["study_id"]: _pi(r) for r in today_rows
                                                                          if r.get("profile")}
    assert landing_limitations(rows) == ()


def test_today_s_client_template_reads_to_the_same_catalog(tmp_path):
    """The filled template of test_client_data (individuals with a BLQ cell, a summary with SD and one n): every dataset
    and the catalog are as before; the analyte column empty is the parent, the drug's name is the parent too."""
    ws = _ws(tmp_path)
    wb = load_workbook(io.BytesIO(build_template()))
    header = [c.value.rstrip("*") for c in wb["Studies"][1]]
    for arm, analyte in (("TEST", None), ("RLD", DRUG)):
        values = {"study_id": "BE-01", "treatment": arm, "design": "SD", "crossover": "yes", "population": "healthy", "n": 24,
                  "route": "oral", "dose": 10, "dose_unit": "mg", "formulation": "ir_tablet", "food_state": "fasted",
                  "lloq": 0.5, "lloq_unit": "ng/ml", "analyte": analyte}
        wb["Studies"].append([values.get(h) for h in header])
    for subject, values in (("001", (0, 40.2, 31.0, 12.5)), ("002", ("BLQ", 45.1, 33.3, 10.2))):
        for t, c in zip((0, 1, 2, 6), values, strict=True):
            wb["PK_Individual"].append(["BE-01", "TEST", subject, 1, t, None, "h", c, "ng/ml"])
    for t, mean, sd in ((1, 42.6, 3.5), (2, 32.1, 1.6), (6, 11.3, 1.6)):
        wb["PK_Summary"].append(["BE-01", "RLD", t, "h", "arithmetic_mean", mean, sd, "SD", 24, "ng/ml"])
    buf = io.BytesIO()
    wb.save(buf)
    sub = ingest(ws, DocumentLibrary(ws), buf.getvalue(), "client.xlsx", by="u")
    assert "NO_VALUE" not in {i["code"] for i in sub["issues"]}
    found = {d.study["study_id"]: d for d in datasets(ws)}
    assert found["BE-01-TEST"].series[1].values == (None, 45.1, 33.3, 10.2)        # BLQ is still below the LLOQ
    assert all(s.n_at is None for d in found.values() for s in d.series)           # one n: nothing new on the series
    for d in found.values():
        decide_dataset(ws, d.id, state=EvidenceState.ACCEPTED, reason="checked", by="u")
    assemble(ws, by="u")
    catalog = ws.latest(ArtifactKind.STUDY_CATALOG, "main").content
    rows, notes, _ = _today_catalog(ws, InputChoices())
    assert catalog == {"studies": rows, "notes": notes}
    assert next(r for r in rows if r["study_id"] == "BE-01-RLD")["profile"] == {
        "times": [1.0, 2.0, 6.0], "values": [42.6, 32.1, 11.3], "time_unit": "h", "unit": "ng/ml", "sd": [3.5, 1.6, 1.6],
        "lloq": 0.5}


def test_the_ms01_split_does_not_move(tmp_path):
    """The split of a parent-only catalog is equal with and without the change; with a metabolite study added it is equal
    too, so the parent rows keep their classes and assignments. None of the new keys is a StudyRecord field."""
    assert NEW_ROW_KEYS.isdisjoint(StudyRecord.model_fields)
    ws = _ws(tmp_path)
    _add(ws, _dataset("iv-1", study=_study("iv-1", route="iv_infusion", infusion_time_min=60, dose_mg=250)))
    _add(ws, _dataset("iv-2", study=_study("iv-2", route="iv_infusion", infusion_time_min=60, dose_mg=500)))
    for sid, dose in (("po-10", 10), ("po-50", 50), ("po-100", 100)):
        _add(ws, _dataset(sid, _series(error=(1.0, 4.0, 3.0, 1.5, 0.4), kind="SD"), study=_study(sid, dose_mg=dose)))
    parent_only = split_studies(_records(_catalog(ws)[0]))
    assert parent_only == split_studies(_records(_today_catalog(ws, InputChoices())[0]))
    _add(ws, _dataset("met-po-10", analyte="M1", study=_study("met-po-10", dose_mg=10)))
    rows, _notes, _ = _catalog(ws)
    assert rows[-1]["measured_analyte"] == "M1" and not rows[-1]["evaluable"]
    with_metabolite = split_studies(_records(rows))
    today = split_studies(_records(_today_catalog(ws, InputChoices())[0]))
    assert with_metabolite == today
    assert [s for s in with_metabolite.splits if s.study_id != "met-po-10"] == [s for s in today.splits
                                                                                 if s.study_id != "met-po-10"]
    assert all(r.analyte is None for r in _records(rows))        # the analyte never reaches StudyRecord.analyte


# --- L-a: BLQ ----------------------------------------------------------------------------------------------------------


def test_points_below_the_lloq_are_left_out_by_the_named_rule_and_counted(tmp_path):
    ws = _ws(tmp_path)
    dataset = _add(ws, _dataset("blq-1", _series(values=(None, 30.0, 22.0, 9.0, None), error=(0.1, 4.0, 3.0, 1.5, 0.2),
                                                  kind="SD"), study=_study("blq-1", lloq=0.5)))
    assert blq(dataset.series[0]) == {"rule": "omit", "omitted": 2} and rules().landing.blq_rule == "omit"
    assert blq(_series()) is None
    (row,), _notes, _ = _catalog(ws)
    assert row["profile"] == {"times": [1.0, 2.0, 4.0], "values": [30.0, 22.0, 9.0], "time_unit": "h", "unit": "ng/ml",
                              "sd": [4.0, 3.0, 1.5], "lloq": 0.5, "blq": {"rule": "omit", "omitted": 2}}
    assert {k: v for k, v in row["profile"].items() if k != "blq"} == _today_profile(dataset)   # what is fitted: as today
    assert row["blq_rule"] == "omit" and "omitted" not in json.dumps({k: v for k, v in row.items() if k != "profile"})
    assert '"blq"' not in _pi(row)                                                              # nothing new in the PI spec


def _workbook(studies: list[dict[str, Any]], *, summary=(), individual=()) -> bytes:
    """A filled template: Studies rows (study_id plus today's required facts), PK_Summary and PK_Individual rows."""
    wb = load_workbook(io.BytesIO(build_template()))
    header = [c.value.rstrip("*") for c in wb["Studies"][1]]
    base = {"design": "SD", "population": "healthy", "n": 12, "route": "oral", "dose": 10, "dose_unit": "mg",
            "formulation": "ir_tablet", "food_state": "fasted", "lloq": 0.5, "lloq_unit": "ng/ml"}
    for study in studies:
        wb["Studies"].append([{**base, **study}.get(h) for h in header])
    for row in summary:
        wb["PK_Summary"].append(list(row))
    for row in individual:
        wb["PK_Individual"].append(list(row))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _ingested(tmp_path, data: bytes) -> tuple[Workspace, dict[str, Any], dict[str, ObservedDataset]]:
    ws = _ws(tmp_path)
    sub = ingest(ws, DocumentLibrary(ws), data, "client.xlsx", by="u")
    found = {d.study["study_id"]: d for d in datasets(ws)}
    for d in found.values():
        decide_dataset(ws, d.id, state=EvidenceState.ACCEPTED, reason="checked", by="u")
    return ws, sub, found


def test_a_refused_summary_value_is_not_counted_below_the_lloq_the_e2e_template(tmp_path):
    """The e2e fixture's CL-01 (apps/web/e2e/fixtures/client_workbooks.py): its 8 h point is BLQ and its 12 h value "1,2"
    is refused. Only the BLQ point is below the LLOQ (omitted: 1); the refused row is left out and named (NO_VALUE). The
    PI block and n_timepoints are today's (the literal was printed by the code at 045ffc3)."""
    data = _workbook([{"study_id": "CL-01"}], summary=[
        *(["CL-01", None, t, "h", "arithmetic_mean", v, None, None, 12, "ng/ml"]
          for t, v in ((0.5, 20.0), (1, 41.0), (2, 30.5), (4, 12.0), (8, "BLQ"))),
        ["CL-01", None, 12, "h", "arithmetic_mean", "1,2", None, None, 12, "ng/ml"]])
    ws, sub, found = _ingested(tmp_path, data)
    codes = [(i["code"], i["location"]) for i in sub["issues"]]
    assert ("UNPARSEABLE_VALUE", "PK_Summary!F7") in codes and ("NO_VALUE", "PK_Summary!A7:J7") in codes
    (series,) = found["CL-01"].series
    assert (series.times, series.values) == ((0.5, 1.0, 2.0, 4.0, 8.0), (20.0, 41.0, 30.5, 12.0, None))
    assert found["CL-01"].study["n_timepoints"] == 6                                   # as today: six sampling times
    (row,), notes, _ = _catalog(ws)
    assert row["profile"]["blq"] == {"rule": "omit", "omitted": 1} and row["blq_rule"] == "omit" and notes == []
    assert _pi(row) == (
        '{"name": "CL-01", "time": [30.0, 60.0, 120.0, 240.0], "time_unit": "min", "values": [0.06666666666666667, '
        '0.1366666666666667, 0.10166666666666667, 0.04], "unit": "µmol/l", "dimension": "Concentration (molar)", '
        '"mol_weight": 300.0, "sd": [], "lloq": 0.0016666666666666668}')


def test_an_empty_summary_value_is_no_blq_point_and_changes_nothing_the_campaign_sees(tmp_path):
    """A mean with one empty value cell and no BLQ mark (MISSING_VALUE): no blq key, no blq_rule, no MAP line. Whether the
    series has an SD is read over every row as today (MS-02's empty row has no SD either: no SD, as today), so the profile,
    the PI block, n_timepoints and the study's statistic are today's (literals printed by the code at 045ffc3)."""
    data = _workbook([{"study_id": "MS-01"}, {"study_id": "MS-02"}], summary=[
        *(["MS-01", None, t, "h", "arithmetic_mean", v, sd, "SD", 12, "ng/ml"]
          for t, v, sd in ((1, 41.0, 3.0), (2, 30.5, 2.0), (4, None, 1.0), (8, 5.0, 0.5))),
        *(["MS-02", None, t, "h", "arithmetic_mean", v, sd, "SD", 12, "ng/ml"]
          for t, v, sd in ((1, 41.0, 3.0), (2, 30.5, 2.0), (4, None, None), (8, 5.0, 0.5)))])
    ws, sub, found = _ingested(tmp_path, data)
    codes = [(i["code"], i["location"]) for i in sub["issues"]]
    assert {("NO_VALUE", "PK_Summary!A4:J4"), ("NO_VALUE", "PK_Summary!A8:J8")} <= set(codes)
    assert all(not any(v is None for v in s.values) for d in found.values() for s in d.series)
    assert [(d.study["n_timepoints"], d.study["statistic"]) for _sid, d in sorted(found.items())] == \
        [(4, "mean_sd"), (4, "mean")]
    rows, notes, _ = _catalog(ws)
    assert notes == [] and not any(NEW_ROW_KEYS & set(r) for r in rows) and not any("blq" in r["profile"] for r in rows)
    assert landing_limitations(rows) == ()
    assert [_pi(r) for r in sorted(rows, key=lambda r: r["study_id"])] == [
        ('{"name": "MS-01", "time": [60.0, 120.0, 480.0], "time_unit": "min", "values": [0.1366666666666667, '
         '0.10166666666666667, 0.016666666666666666], "unit": "µmol/l", "dimension": "Concentration (molar)", '
         '"mol_weight": 300.0, "sd": [0.01, 0.006666666666666667, 0.0016666666666666668], "lloq": 0.0016666666666666668}'),
        ('{"name": "MS-02", "time": [60.0, 120.0, 480.0], "time_unit": "min", "values": [0.1366666666666667, '
         '0.10166666666666667, 0.016666666666666666], "unit": "µmol/l", "dimension": "Concentration (molar)", '
         '"mol_weight": 300.0, "sd": [], "lloq": 0.0016666666666666668}')]


# --- L-b: SE, CV%, geometric and median spreads -----------------------------------------------------------------------


def test_an_se_with_n_becomes_an_sd_per_time_point_or_per_series():
    se = (1.0, 2.0, 1.5, 0.5, 0.2)
    per_series = judged_sd(_series(error=se, kind="SE", n=16), range(5))
    assert per_series == {"sd": [spread.sd_from_se(e, 16) for e in se],
                          "sd_from": {"kind": "SE", "method": "se_times_sqrt_n", "n": "series", "version": "spread-1"}}
    assert per_series["sd"][0] == 4.0
    varying = _dataset("se-1", _series(values=(None, 30.0, 22.0, 9.0, 2.5), error=se, kind="SE", n=16,
                                        n_at=(16, 16, 15, 12, 9)))
    profile = _profile(varying)
    assert profile["sd"] == [spread.sd_from_se(e, n) for e, n in zip(se[1:], (16, 15, 12, 9), strict=True)]
    assert profile["sd_from"] == {"kind": "SE", "method": "se_times_sqrt_n", "n": "per_time", "version": spread.VERSION}
    assert profile["n_at"] == [16, 15, 12, 9] and profile["blq"] == {"rule": "omit", "omitted": 1}
    assert (profile["times"], profile["values"]) == ([1.0, 2.0, 4.0, 8.0], [30.0, 22.0, 9.0, 2.5])
    assert "spread" not in profile and "warnings" not in profile and "sd_type" not in profile


def test_a_cv_percent_of_an_arithmetic_mean_becomes_an_sd():
    profile = _profile(_dataset("cv-1", _series(error=(10.0, 20.0, 10.0, 10.0, 40.0), kind="CV%")))
    assert profile["sd"] == [spread.sd_from_cv_percent(c, m) for c, m in zip((10.0, 20.0, 10.0, 10.0, 40.0), VALUES, strict=True)]
    assert profile["sd"] == [1.0, 6.0, 2.2, 0.9, 1.0]
    assert profile["sd_from"] == {"kind": "CV%", "method": "cv_percent_times_mean", "version": "spread-1"}


@pytest.mark.parametrize(("statistic", "kind", "n", "n_at", "unit", "words"), [
    ("arithmetic_mean", "SE", None, None, "ng/ml", "n is not known"),
    ("arithmetic_mean", "SE", 16, (16, None, 16, 16, 16), "ng/ml", "n is not known"),   # one point's n unknown
    ("median", "SE", 16, None, "ng/ml", "median"),
    ("median", "SD", 16, None, "ng/ml", "median"),
    ("median", "CV%", 16, None, "%", "median"),
    ("geometric_mean", "SE", 16, None, "ng/ml", "geometric mean"),
    ("geometric_mean", "CV%", 16, None, "%", "geometric mean"),
])
def test_a_spread_that_is_not_converted_is_kept_verbatim_with_its_unit_and_a_warning(statistic, kind, n, n_at, unit, words):
    errors = (1.0, 2.0, 1.5, 0.5, 0.2)
    dataset = _dataset("sp-1", _series(statistic, values=(10.0, 30.0, 22.0, 9.0, None), error=errors, kind=kind, n=n,
                                       n_at=n_at))
    profile = _profile(dataset)
    assert profile["sd"] is None and "sd_from" not in profile and "sd_type" not in profile
    assert profile["spread"] == {"kind": kind, "values": [1.0, 2.0, 1.5, 0.5], "unit": unit}   # the kept points'
    (warning,) = profile["warnings"]
    assert words in warning and "kept as reported" in warning
    canonical = normalize_profile(profile, 300.0)
    assert canonical["spread"] == profile["spread"] and canonical["sd"] is None          # never scaled, never sent
    assert landing_limitations([{"study_id": "sp-1", "profile": profile}]) == (
        f"sp-1: the reported {kind} is kept as reported, not converted; the fit has no SD for this profile ({NAMED})",)


def test_a_geometric_sd_is_sent_as_reported_with_its_error_type_and_a_warning(tmp_path):
    ws = _ws(tmp_path)
    _add(ws, _dataset("geo-1", _series("geometric_mean", error=(1.4, 1.5, 1.5, 1.6, 1.9), kind="SD")))
    (row,), _notes, _ = _catalog(ws)
    profile = row["profile"]
    assert profile["sd"] == [1.4, 1.5, 1.5, 1.6, 1.9]
    assert profile["sd_type"] == rules().landing.geometric_sd_sent_as == spread.GEOMETRIC_SD
    (warning,) = profile["warnings"]
    assert "geometric SD factor" in warning and "assumption" in warning
    canonical = normalize_profile(profile, 300.0)
    assert canonical["sd"] == [1.4, 1.5, 1.5, 1.6, 1.9]                                   # a factor: never scaled
    block = json.loads(_pi(row))
    assert block["error_type"] == "GeometricStdDev" and block["sd"] == [1.4, 1.5, 1.5, 1.6, 1.9]


@pytest.mark.parametrize(("statistic", "kind"), [("arithmetic_mean", "SD"), ("geometric_mean", "SD"),
                                               ("arithmetic_mean", "SE"), ("arithmetic_mean", "CV%")])
def test_a_spread_missing_at_a_kept_point_gives_no_sd_and_never_a_none_in_the_pi_spec(statistic, kind):
    """As today, an SD is given only when every kept point has a spread. Series.error cannot hold a None today; the
    Delivery landing (D6) widens it, so the series is built as it will be (model_construct)."""
    series = Series.model_construct(name="mean", statistic=statistic, times=(1.0, 2.0, 4.0), values=(30.0, 22.0, 9.0),
                                    error=(2.0, None, 1.0), error_kind=kind, n=16, n_at=None)
    judged = judged_sd(series, [0, 1, 2], unit="ng/ml")
    assert judged["sd"] is None and "sd_from" not in judged and "sd_type" not in judged
    assert judged["spread"]["values"] == [2.0, None, 1.0]
    (warning,) = judged["warnings"]
    assert "not every point has one" in warning
    profile = {"times": [1.0, 2.0, 4.0], "values": [30.0, 22.0, 9.0], "time_unit": "h", "unit": "ng/ml", "lloq": None,
               **judged}
    p = normalize_profile(profile, 300.0)
    block = pi_observed("x", p["times"], p["values"], time_unit=p["time_unit"], unit=p["unit"], mol_weight=300.0,
                        sd=p.get("sd"), lloq=p.get("lloq"), error_type=p.get("sd_type"))
    assert block["sd"] == [] and "null" not in json.dumps(block)
    # the missing spread at a point below the LLOQ, which is left out: the kept points' spreads are whole
    blq_first = Series.model_construct(name="mean", statistic=statistic, times=(0.0, 1.0, 2.0), values=(None, 30.0, 22.0),
                                       error=(None, 2.0, 1.0), error_kind=kind, n=16, n_at=None)
    assert judged_sd(blq_first, [1, 2])["sd"] is not None


def _agent_dataset(kind: str, *, state: EvidenceState = EvidenceState.PROPOSED) -> ObservedDataset:
    """As observed_data_agent.propose_profile builds one: literature, read from a table by the model (TABLE), the series
    n a free tool argument (100) that no quote checks; the study's quoted n is 12."""
    return ObservedDataset(id=new_dataset_id(), kind="profile", origin=Origin.LITERATURE, extraction="TABLE",
                           study={**_study("lit-1", n=12), "n_timepoints": 3}, state=state,
                           series=(Series(times=(1.0, 2.0, 4.0), values=(10.0, 8.0, 4.0), error=(1.0, 1.0, 0.5),
                                          error_kind=kind, n=100),))  # type: ignore[arg-type]


@pytest.mark.parametrize("kind", ["SE", "CV%"])
def test_a_reading_models_se_or_cv_is_converted_only_once_a_person_accepts_the_dataset(tmp_path, kind):
    """A proposed literature dataset counts in the catalog, but its spread kind and n were given by the reading model
    and checked against no quote: the spread is kept as reported (no SD, as before D1a) until a person accepts the
    dataset. Cells read by code (CELL) and a person's entry (MANUAL) convert at once."""
    proposed = _agent_dataset(kind)
    assert not spread_confirmed(proposed)
    assert spread_confirmed(proposed.model_copy(update={"state": EvidenceState.ACCEPTED}))
    assert spread_confirmed(proposed.model_copy(update={"extraction": "CELL"}))
    assert spread_confirmed(proposed.model_copy(update={"extraction": "MANUAL"}))
    ws = _ws(tmp_path)
    stored = _add(ws, proposed, accept=False)
    (row,), _notes, _ = _catalog(ws)
    assert row["evaluable"] is True and row["profile"]["sd"] is None and "sd_from" not in row["profile"]
    assert row["profile"]["spread"]["values"] == [1.0, 1.0, 0.5]
    (warning,) = row["profile"]["warnings"]
    assert "reading model" in warning and "accepting the dataset converts it" in warning
    assert json.loads(_pi(row))["sd"] == [] and _pi(row) == _pi(_today_catalog(ws, InputChoices())[0][0])
    assert landing_limitations([row]) == (
        f"lit-1: the reported {kind} is kept as reported, not converted; the fit has no SD for this profile ({NAMED})",)
    decide_dataset(ws, stored.id, state=EvidenceState.ACCEPTED, reason="n and the spread checked against the table", by="u")
    (row,), _notes, _ = _catalog(ws)
    expected = [10.0, 10.0, 5.0] if kind == "SE" else [spread.sd_from_cv_percent(c, m) for c, m in ((1.0, 10.0), (1.0, 8.0),
                                                                                                    (0.5, 4.0))]
    assert row["profile"]["sd"] == expected and row["profile"]["sd_from"]["kind"] == kind


def test_a_geometric_sd_below_one_is_still_sent_as_reported_and_warned_as_not_a_factor():
    """A geometric SD factor is exp(sigma) >= 1: a value below 1 says the label is likely wrong. What is sent does not
    change (the SME decides, contracts §11.5); the profile says so."""
    judged = judged_sd(_series("geometric_mean", values=(10.0, 30.0, 22.0), error=(0.4, 1.3, 0.3), kind="SD"), [0, 1, 2])
    assert judged["sd"] == [0.4, 1.3, 0.3] and judged["sd_type"] == spread.GEOMETRIC_SD
    first, second = judged["warnings"]
    assert "assumption" in first and "cannot be a geometric SD factor" in second
    assert len(judged_sd(_series("geometric_mean", values=(10.0, 30.0), error=(1.0, 1.4), kind="SD"), [0, 1])["warnings"]) == 1


# --- L-e: n per time point --------------------------------------------------------------------------------------------


def _summary_workbook(ns: tuple[int | None, ...], *, kind: str = "SD") -> bytes:
    wb = load_workbook(io.BytesIO(build_template()))
    header = [c.value.rstrip("*") for c in wb["Studies"][1]]
    values = {"study_id": "EXA-201", "design": "SD", "population": "healthy", "n": 16, "route": "oral", "dose": 10,
              "dose_unit": "mg", "formulation": "solution", "food_state": "fasted", "lloq": 0.5, "lloq_unit": "ng/ml"}
    wb["Studies"].append([values.get(h) for h in header])
    for t, mean, n in zip((1, 2, 4), (42.6, 32.1, 11.3), ns, strict=True):
        wb["PK_Summary"].append(["EXA-201", None, t, "h", "arithmetic_mean", mean, 1.5, kind, n, "ng/ml"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _observation(t: float, n: int | None) -> ConcentrationObservation:
    return ConcentrationObservation(study_id="EXA-202", analyte=DRUG, matrix="plasma", series="mean", statistic="arithmetic_mean",
                                    time=t, time_unit="h", value=10.0 / t, unit="ng/ml", sd=0.5, n=n,
                                    source=SourceRef(file_sha256="a" * 64, recipe_id="r1", recipe_version=1,
                                                     cells={"value": f"Sheet1!B{int(t) + 1}"}))


def test_n_per_time_point_is_kept_only_when_it_varies(tmp_path):
    ws = _ws(tmp_path)
    ingest(ws, DocumentLibrary(ws), _summary_workbook((16, 16, 16)), "same-n.xlsx", by="u")
    (same,) = datasets(ws)
    assert (same.series[0].n, same.series[0].n_at) == (16, None)
    assert "n_at" not in same.to_content()["series"][0]                               # the content of before: no key
    ws2 = _ws(tmp_path / "two")
    ingest(ws2, DocumentLibrary(ws2), _summary_workbook((16, 15, None)), "varying-n.xlsx", by="u")
    (varying,) = datasets(ws2)
    assert (varying.series[0].n, varying.series[0].n_at) == (16, (16, 15, None))       # n stays the first stated
    assert varying.to_content()["series"][0]["n_at"] == [16, 15, None]
    # n stated once (or at some points, all equal): one n, the series', as before; a point with no n is not another n
    ws3 = _ws(tmp_path / "three")
    ingest(ws3, DocumentLibrary(ws3), _summary_workbook((16, None, None), kind="SE"), "n-once.xlsx", by="u")
    (once,) = datasets(ws3)
    assert (once.series[0].n, once.series[0].n_at) == (16, None)
    profile = _profile(once)
    assert profile["sd"] == [spread.sd_from_se(1.5, 16)] * 3 and profile["sd_from"]["n"] == "series"
    # the recipe path, and the draft card's points
    library = DocumentLibrary(ws)
    (one_n,) = datasets_from_observations([_observation(t, 12) for t in (1, 2, 4)], study=_study("x"), sha="a" * 64,
                                          filename="f.xlsx", library=library)
    (many,) = datasets_from_observations([_observation(t, n) for t, n in ((1, 12), (2, 12), (4, 10))], study=_study("x"),
                                         sha="a" * 64, filename="f.xlsx", library=library)
    assert one_n.series[0].n_at is None and (many.series[0].n, many.series[0].n_at) == (12, (12, 12, 10))
    checked = SimpleNamespace(concentrations=[_observation(t, n) for t, n in ((1, 12), (2, 12), (4, 10))])
    (points,) = _points(checked, SimpleNamespace(lloq=None))["series"]
    assert points["n_at"] == [12, 12, 10] and points["n"] == 12
    checked = SimpleNamespace(concentrations=[_observation(t, 12) for t in (1, 2, 4)])
    assert "n_at" not in _points(checked, SimpleNamespace(lloq=None))["series"][0]
    with pytest.raises(DatasetError, match="n per time"):
        check_dataset(_dataset("x", _series(n_at=(12, 12))))


def test_a_dataset_stored_before_the_field_keeps_its_content_and_an_identical_resave_is_no_new_version(tmp_path):
    """A dataset whose n does not vary has exactly the content it had before Series.n_at existed (the key is left out
    when None), so its sha256 is unchanged and the same decision again returns the stored version, as before."""
    dataset = check_dataset(_dataset("st-9", _series(error=(1.0, 4.0, 3.0, 1.5, 0.4), kind="SD"),
                                     state=EvidenceState.ACCEPTED, decided_by="u", decision_reason="checked"))
    content = dataset.to_content()
    assert list(content["series"][0]) == ["name", "statistic", "times", "values", "error", "error_kind", "n"]  # 045ffc3's
    assert content_sha256(ObservedDataset.from_content(content).to_content()) == content_sha256(content)
    ws = _ws(tmp_path)
    stored = ws.commit(ArtifactKind.DATASET, dataset.id, content, actor="u", reason="stored before D1a")
    decide_dataset(ws, dataset.id, state=EvidenceState.ACCEPTED, reason="checked", by="u")
    assert ws.latest(ArtifactKind.DATASET, dataset.id).version == stored.version == 1


# --- template individuals: missing is not below the LLOQ --------------------------------------------------------------


def test_an_empty_template_concentration_is_no_longer_a_blq_point(tmp_path):
    ws = _ws(tmp_path)
    wb = load_workbook(io.BytesIO(build_template()))
    header = [c.value.rstrip("*") for c in wb["Studies"][1]]
    values = {"study_id": "EXA-301", "design": "SD", "population": "healthy", "n": 2, "route": "oral", "dose": 10,
              "dose_unit": "mg", "formulation": "solution", "food_state": "fasted", "lloq": 0.5, "lloq_unit": "ng/ml"}
    wb["Studies"].append([values.get(h) for h in header])
    for subject, cells in (("001", (("BLQ", None), (40.2, None), (None, None), (12.5, None))),
                           ("002", ((None, "yes"), (45.1, None), (33.3, None), (None, "no")))):
        for t, (c, flag) in zip((0, 1, 2, 6), cells, strict=True):
            wb["PK_Individual"].append(["EXA-301", None, subject, 1, t, None, "h", c, "ng/ml", flag])
    buf = io.BytesIO()
    wb.save(buf)
    sub = ingest(ws, DocumentLibrary(ws), buf.getvalue(), "individuals.xlsx", by="u")
    no_value = [i for i in sub["issues"] if i["code"] == "NO_VALUE"]
    assert [i["location"] for i in no_value] == ["PK_Individual!A4:J4", "PK_Individual!A9:J9"]
    assert all("missing is not below the LLOQ" in i["message"] for i in no_value)
    (dataset,) = datasets(ws)
    first, second = dataset.series
    assert (first.times, first.values) == ((0.0, 1.0, 6.0), (None, 40.2, 12.5))       # "BLQ" below the LLOQ, the gap out
    assert (second.times, second.values) == ((0.0, 1.0, 2.0), (None, 45.1, 33.3))     # blq_flag yes on an empty cell: BLQ


def test_an_empty_individual_row_leaves_the_subjects_times_and_the_studys_n_timepoints_as_they_were(tmp_path):
    """Whether a subject's times are actual or nominal is decided over every row read, as before: subject 001's empty last
    row has no actual time, so its times stay nominal. The study's n_timepoints counts the rows read (the sampling
    times), as before, so its MS-01 information score and the split do not move (values printed by the code at
    045ffc3: 001 at (1, 2, 4, 6) h, n_timepoints 4)."""
    data = _workbook([{"study_id": "IN-01", "n": 2}], individual=[
        *(["IN-01", None, "001", 1, nominal, actual, "h", c, "ng/ml"]
          for nominal, actual, c in ((1, 1.1, 40.2), (2, 2.2, 31.0), (4, 4.3, 12.5), (6, None, None))),
        *(["IN-01", None, "002", 1, nominal, actual, "h", c, "ng/ml"]
          for nominal, actual, c in ((1, 1.0, 38.0), (2, 2.1, 30.0), (4, 4.0, 11.0)))])
    _unused, sub, found = _ingested(tmp_path, data)
    assert [(i["code"], i["location"]) for i in sub["issues"]] == [("NO_VALUE", "PK_Individual!A5:J5")]
    first, second = found["IN-01"].series
    assert (first.times, first.values) == ((1.0, 2.0, 4.0), (40.2, 31.0, 12.5))      # nominal, as before; the gap out
    assert second.times == (1.0, 2.1, 4.0)                                          # every row has an actual time
    record = found["IN-01"].study_record()
    assert (record.n_timepoints, record.statistic) == (4, "individual")              # as today
    # every subject one row short: n_timepoints is still the rows read, not the series' length
    data = _workbook([{"study_id": "IN-02", "n": 1}], individual=[
        ["IN-02", None, "001", 1, nominal, None, "h", c, "ng/ml"] for nominal, c in ((1, 40.2), (2, 31.0), (4, 12.5), (6, None))])
    _unused, _sub, found = _ingested(tmp_path / "two", data)
    assert len(found["IN-02"].series[0].times) == 3 and found["IN-02"].study["n_timepoints"] == 4


# --- L-d: analyte and matrix ------------------------------------------------------------------------------------------


def test_the_parent_is_named_by_the_rules_or_the_briefs_names_for_the_drug(tmp_path):
    assert is_parent("parent", ()) and is_parent("", ()) and is_parent("Parent ", ())
    assert is_parent("EXAMPLEAMIDE", (DRUG,)) and is_parent("exa-1234", ("EXA 1234",))
    assert not is_parent("M1", (DRUG,)) and not is_parent(DRUG, ())
    ws = _ws(tmp_path, synonyms=["EXA-1234"])
    _add(ws, _dataset("by-name", analyte=DRUG))
    _add(ws, _dataset("by-synonym", analyte="exa 1234"))
    _add(ws, _dataset("met", analyte="Exampleamide-N-oxide"))
    assemble(ws, by="u")                                       # the brief's drug name and synonyms are the parent's names
    rows = {r["study_id"]: r for r in ws.latest(ArtifactKind.STUDY_CATALOG, "main").content["studies"]}
    assert rows["by-name"]["evaluable"] and rows["by-synonym"]["evaluable"] and "measured_analyte" not in rows["by-name"]
    assert not rows["met"]["evaluable"] and rows["met"]["measured_analyte"] == "Exampleamide-N-oxide"


def test_a_metabolite_dataset_is_listed_not_evaluable_and_never_wins_over_the_parents(tmp_path):
    ws = _ws(tmp_path)
    own = _add(ws, _dataset("met-1", analyte="M1"))
    metabolite = _add(ws, _dataset("st-1", analyte="M1"))                   # earlier and accepted: wins today
    parent = _add(ws, _dataset("st-1", _series(error=(1.0, 4.0, 3.0, 1.5, 0.4), kind="SD")), accept=False)
    rows, notes, used = _catalog(ws)
    by_sid = {r["study_id"]: r for r in rows}
    assert by_sid["met-1"]["dataset_id"] == own.id and by_sid["met-1"]["evaluable"] is False
    assert "profile" not in by_sid["met-1"] and by_sid["met-1"]["measured_analyte"] == "M1"
    assert "met-1: a profile of M1, not of the modelled compound: not evaluable without a model system" in notes
    assert by_sid["st-1"]["dataset_id"] == parent.id and by_sid["st-1"]["evaluable"] is True
    assert "measured_analyte" not in by_sid["st-1"]
    assert "st-1: the M1 profile is not used: the parent's is" in notes
    assert _today_catalog(ws, InputChoices())[0][1]["dataset_id"] == metabolite.id      # today the metabolite was judged
    assert [v.id for v in used] == [own.id, parent.id]
    assert f"met-1: measures M1, not the modelled compound: not evaluable without a model system ({NAMED})" in \
        landing_limitations(rows)


def test_a_serum_profile_is_judged_with_a_warning_and_plasma_wins_over_blood_whatever_the_order(tmp_path):
    assert [matrix_key(m) for m in ("plasma", " Plasma ", "whole blood", "Blood", "SERUM", "CSF")] == \
        ["plasma", "plasma", "blood", "blood", "serum", "csf"]
    assert judged_as_plasma("Whole blood") and judged_as_plasma("serum")
    ws = _ws(tmp_path)
    serum = _add(ws, _dataset("ser-1", _series(error=(1.0, 4.0, 3.0, 1.5, 0.4), kind="SD"), matrix="serum"))
    blood = _add(ws, _dataset("st-2", matrix="blood"))                   # created first and accepted
    plasma = _add(ws, _dataset("st-2", matrix="Plasma"), accept=False)    # any spelling of plasma is plasma
    rows, notes, _ = _catalog(ws)
    by_sid = {r["study_id"]: r for r in rows}
    assert by_sid["ser-1"]["profile"] == _today_profile(serum) and by_sid["ser-1"]["measured_matrix"] == "serum"
    assert "ser-1: measured in serum, judged against the plasma output" in notes
    assert by_sid["st-2"]["dataset_id"] == plasma.id and "measured_matrix" not in by_sid["st-2"]
    assert "st-2: the blood profile is not used: the plasma one is" in notes
    assert blood.id not in {r["dataset_id"] for r in rows}
    # the other creation order: plasma still wins
    ws2 = _ws(tmp_path / "two")
    plasma2 = _add(ws2, _dataset("st-2"))
    _add(ws2, _dataset("st-2", matrix="blood"))
    assert [r["dataset_id"] for r in _catalog(ws2)[0]] == [plasma2.id]
    assert f"ser-1: measured in serum, judged against the plasma output ({NAMED})" in landing_limitations(rows)


@pytest.mark.parametrize("spelled", ["human plasma", "Plasma (K2EDTA)", "EDTA plasma", "plasma, heparin", "blood plasma",
                                     "PLASMA"])
def test_plasma_written_as_free_text_is_plasma_and_is_judged_as_before(tmp_path, spelled):
    """The agent, document-reader and manual paths write the matrix as free text: a word of plasma in it is plasma (the
    field vocabulary's cue, plasma first), so the profile, the row and the PI block are today's, and it wins over a serum
    dataset of the same study."""
    assert matrix_key(spelled) == "plasma" and matrix_judgement(spelled) == "plasma"
    ws = _ws(tmp_path)
    _add(ws, _dataset("st-3", matrix="human serum"))                       # created first and accepted
    dataset = _add(ws, _dataset("st-3", _series(error=(1.0, 4.0, 3.0, 1.5, 0.4), kind="SD"), matrix=spelled), accept=False)
    (row,), notes, _ = _catalog(ws)
    assert row["dataset_id"] == dataset.id and row["evaluable"] is True and not NEW_ROW_KEYS & set(row)
    assert row["profile"] == _today_profile(dataset)
    assert notes == ["st-3: the human serum profile is not used: the plasma one is"]
    assert landing_limitations([row]) == ()
    assert matrix_key("human serum") == "serum" and matrix_key("whole blood") == "blood"


def test_urine_is_not_judged_and_a_matrix_the_vocabulary_does_not_name_is_judged_as_before_with_a_warning(tmp_path):
    """A urine or feces profile (a matrix the field vocabulary names, outside the rules' blood and serum) is listed, not
    judged against the plasma output. Words the vocabulary does not recognise (CSF, a blank) cannot be decided by code:
    the profile is judged as before, with the row's measured_matrix, a note and a MAP line for a person to confirm."""
    assert [matrix_judgement(m) for m in ("plasma", "blood", "serum", "urine", "Feces", "CSF", "")] == \
        ["plasma", "as_plasma", "as_plasma", "not_judged", "not_judged", "unnamed", "unnamed"]
    ws = _ws(tmp_path)
    urine = _add(ws, _dataset("ur-1", matrix="urine"))
    csf = _add(ws, _dataset("csf-1", _series(error=(1.0, 4.0, 3.0, 1.5, 0.4), kind="SD"), matrix="CSF"))
    blank = _add(ws, _dataset("bl-1", matrix=" "))
    rows, notes, _ = _catalog(ws)
    by_sid = {r["study_id"]: r for r in rows}
    assert by_sid["ur-1"]["dataset_id"] == urine.id and by_sid["ur-1"]["evaluable"] is False
    assert "profile" not in by_sid["ur-1"] and by_sid["ur-1"]["measured_matrix"] == "urine"
    assert "ur-1: measured in urine: not evaluable, no model output is judged against it" in notes
    assert by_sid["csf-1"]["profile"] == _today_profile(csf) and by_sid["csf-1"]["evaluable"] is True
    assert by_sid["csf-1"]["measured_matrix"] == "CSF"
    assert by_sid["bl-1"]["profile"] == _today_profile(blank) and by_sid["bl-1"]["measured_matrix"] == " "
    assert ("csf-1: measured in CSF, a matrix the intake rules do not name: judged against the plasma output as before, "
            "for a person to confirm") in notes
    assert ("bl-1: measured in a matrix that is not stated, a matrix the intake rules do not name: judged against the "
            "plasma output as before, for a person to confirm") in notes
    today = {r["study_id"]: r for r in _today_catalog(ws, InputChoices())[0]}
    assert _pi(by_sid["csf-1"]) == _pi(today["csf-1"]) and _pi(by_sid["bl-1"]) == _pi(today["bl-1"])
    assert landing_limitations(rows) == (
        f"ur-1: measured in urine: not judged, no model output is judged against it ({NAMED})",
        (f"csf-1: measured in CSF, a matrix the intake rules do not name: judged against the plasma output as before, "
         f"for a person to confirm ({NAMED})"),
        (f"bl-1: measured in a matrix that is not stated, a matrix the intake rules do not name: judged against the "
         f"plasma output as before, for a person to confirm ({NAMED})"),
    )


def test_a_parent_and_a_metabolite_of_one_study_are_not_called_duplicates():
    """dataset_warnings no longer asks a person to reject a metabolite (or a serum) dataset that shares its study id
    with the parent's plasma one: the catalog keeps both apart. True duplicates keep today's advice word for word."""
    parent, metabolite = _dataset("st-1"), _dataset("st-1", analyte="M1")
    (warning,) = dataset_warnings([parent, metabolite])
    assert "measure different analytes or matrices" in warning and "reject" not in warning
    assert "different analytes or matrices" in dataset_warnings([parent, _dataset("st-1", matrix="serum")])[0]
    twin = _dataset("st-1", analyte="Parent", matrix="Plasma (EDTA)")
    assert dataset_warnings([parent, twin]) == [
        f"st-1: 2 datasets share this study id ({parent.id}, {twin.id}); give each arm its own id, or reject the duplicates"]
    by_name = _dataset("st-1", analyte=DRUG)                                  # the parent by the brief's name
    assert dataset_warnings([parent, by_name], names=(DRUG,)) == [
        f"st-1: 2 datasets share this study id ({parent.id}, {by_name.id}); give each arm its own id, or reject the duplicates"]


# --- the Delivery landing's cross-file join ---------------------------------------------------------------------------


def test_a_cross_file_flag_survives_the_checks_and_names_the_join(tmp_path):
    ws = _ws(tmp_path)
    flag = "cross_file: synopsis.pdf via lk-2"
    dataset = _dataset("x-1", flags=(flag, "digitized: overlay not yet approved"))
    assert check_dataset(dataset).flags == (flag,)                       # the join kept, every check's flag recomputed
    stored = _add(ws, dataset)
    assert stored.flags == (flag,)
    changed = set_study_facts(ws, stored.id, changes={"dosing_interval_h": 12, "n_doses": 3, "design": "MD"}, by="u")
    assert changed.flags == (flag,)
    (row,), _notes, _ = _catalog(ws)
    assert row["joined_from"] == ["synopsis.pdf via lk-2"]
    assert landing_limitations([row]) == ("x-1: values joined from another file (synopsis.pdf via lk-2)",)


# --- the MAP's limitations --------------------------------------------------------------------------------------------


def _cpf() -> CPF:
    prov = Provenance(source_type="Publication", reference="review")

    def r(pid, value, unit=None, binding=None):
        return ParameterRecord(id=pid, value=value, unit=unit, status=ParameterStatus.FIXED, provenance=prov, engine_binding=binding)

    return CPF(compound=DRUG, parameters=(
        r("phys.mw", 300.0, "g/mol"), r("phys.logp", 1.2, "Log Units"), r("bind.fu", 0.3),
        r("phys.solubility.ref", 1.3, "mg/ml"), r("phys.pka.base.0", 2.3),
        r("elim.renal.gfr_fraction", 1.0, binding=EngineBinding(building_block="Compound", process="GlomerularFiltration",
                                                                parameter="GFR fraction", data_source="Literature"))))


def test_landing_limitations_name_the_rule_each_conversion_each_matrix_and_each_join_and_reach_the_map(tmp_path):
    ws = _ws(tmp_path)
    _add(ws, _dataset("iv-1", _series(values=(30.0, 22.0, 9.0, 2.5, None)),
                      study=_study("iv-1", route="iv_infusion", infusion_time_min=60, lloq=0.5)))
    _add(ws, _dataset("po-se", _series(error=(1.0, 2.0, 1.5, 0.5, 0.2), kind="SE", n=16, n_at=(16, 16, 15, 12, 9)),
                      study=_study("po-se", dose_mg=50)))
    _add(ws, _dataset("po-cv", _series(error=(10.0, 20.0, 10.0, 10.0, 40.0), kind="CV%"), study=_study("po-cv", dose_mg=25)))
    _add(ws, _dataset("po-geo", _series("geometric_mean", error=(1.4, 1.5, 1.5, 1.6, 1.9), kind="SD"),
                      study=_study("po-geo", dose_mg=10)))
    _add(ws, _dataset("po-ser", matrix="serum", study=_study("po-ser", dose_mg=75), flags=("cross_file: synopsis.pdf via lk-2",)))
    rows, _notes, _ = _catalog(ws)
    limits = landing_limitations(rows)
    assert limits == (
        f"iv-1: the points below the LLOQ are left out of the fit and of NCA, the LLOQ kept (BLQ rule 'omit', {NAMED})",
        f"po-se: the SD the fit is given is derived from the reported SE and n per time point (SD = SE × √n, spread-1; {NAMED})",
        f"po-cv: the SD the fit is given is derived from the reported CV% and the mean (SD = CV% × mean / 100, spread-1; {NAMED})",
        (f"po-geo: the SD of the geometric mean is sent as reported, as a geometric SD factor (GeometricStdDev); that it "
         f"is a geometric factor is an assumption for the SME ({NAMED})"),
        f"po-ser: measured in serum, judged against the plasma output ({NAMED})",
        "po-ser: values joined from another file (synopsis.pdf via lk-2)",
    )
    # every line a rule of the intake rules decides says it is UNVERIFIED; the join is the data's, not a rule's
    assert all(NAMED in line for line in limits if "joined from" not in line) and RULES_STATUS == "UNVERIFIED"
    assert all("omitted" not in line and " 1 " not in line for line in limits)          # no count: blinding-safe
    plan = build_default(_cpf(), rows, Structure(model_risk="medium"))
    assert plan.default_limitations[-len(limits):] == limits
    assert set(limits) <= set(map_from_plan(plan, _cpf(), rows).split_limitations)
    # a catalog no deliberate change touches: the same plan as today
    ws2 = _ws(tmp_path / "two")
    _add(ws2, _dataset("iv-1", study=_study("iv-1", route="iv_infusion", infusion_time_min=60, lloq=0.5)))
    for sid, dose in (("po-10", 10), ("po-50", 50)):
        _add(ws2, _dataset(sid, _series(error=(1.0, 4.0, 3.0, 1.5, 0.4), kind="SD"), study=_study(sid, dose_mg=dose)))
    new, today = _catalog(ws2)[0], _today_catalog(ws2, InputChoices())[0]
    assert landing_limitations(new) == ()
    assert build_default(_cpf(), new, Structure(model_risk="medium")).model_dump(exclude={"created_at"}) == \
        build_default(_cpf(), today, Structure(model_risk="medium")).model_dump(exclude={"created_at"})
