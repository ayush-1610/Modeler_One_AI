"""A study's bioequivalence computed by code, beside the CSR's (plan 2026-11-26 §7 phase 3; the corpus audit's R01,
R50, R55; decision D3). The delivery is the made-up Exampleamide one (a 2×2 crossover, reference A, test B); the CSR's
BE table is written here. No model is called."""

from __future__ import annotations

from pathlib import Path

import pytest

from modeler_intake.room_specs import ColumnSpec, Extraction, TableDescription
from modeler_project.dataroom import DataRoomStore, room_inputs
from modeler_project.dataroom.assemble import assemble
from modeler_project.dataroom.bestats import be_results, csr_metric, csr_values
from modeler_project.dataroom.reading import read_uploads
from modeler_project.dataroom.rules import load_rules
from modeler_project.dataroom.synthetic import FOLDER, delivery, seed
from modeler_project.store import FileProjectStore
from modeler_project.workspace import Workspace

pytestmark = pytest.mark.req("T-47")
CSR = f"{FOLDER}/Clinical/EX-01 BE statistics.tsv"


def _room(tmp_path: Path, csr: str | None = None) -> DataRoomStore:
    store = DataRoomStore(Workspace(FileProjectStore(tmp_path / "root"), "t1", "p1"))
    files = dict(delivery())
    if csr is not None:
        files[CSR] = csr.encode()
    for name, data in files.items():
        store.add_upload(name, data, by="user:m")
    read_uploads(store, use_ocr=False, workers=1)
    seed(store, confirmed=True)
    if csr is not None:
        f = next(x for x in store.files() if x.path == CSR)
        store.put_extraction(Extraction(file=CSR, tables=[TableDescription(
            file=CSR, kind="be_statistics", about="EX-01", part=f"sheet:{Path(CSR).stem}", header_lines=[1], first_line=2,
            last_line=csr.count("\n"), columns=[ColumnSpec(index=i, role=r) for i, r in enumerate(
                ("parameter", "ratio", "ci_low", "ci_high", "cv"), start=1)])]), f.sha256, agent={"agent": "A8", "model": "m"})
    return store


def test_the_study_bioequivalence_is_computed_from_our_nca_and_the_clients_on_the_chosen_set(tmp_path):
    study = assemble(room_inputs(_room(tmp_path))).studies[0]
    ours = {b.metric: b for b in study.be if b.source == "ours"}
    assert set(ours) == {"cmax", "auc_t", "auc_inf"}
    auc = ours["auc_t"]
    assert (auc.test, auc.reference, auc.analysis_set) == ("B", "A", "modeling")
    # Cmax on the modeling set; the AUCs on its subjects with complete profiles (the AUC set: one subject misses its
    # last sample), as the CSRs do (P03's were reproduced so)
    assert ours["cmax"].n_by_group == (3, 3) and auc.n_by_group == (2, 3) and "(the AUC set)" in auc.rule
    assert auc.design == "2x2 crossover" and auc.df == auc.n - 2
    assert auc.ci_low_percent <= auc.gmr_percent <= auc.ci_high_percent and auc.cv_percent is not None
    assert auc.within_limits and auc.conclusion.startswith("the 90 % CI ") and "bioequivalent on AUC0–t" in auc.conclusion
    assert auc.zone_low_percent < auc.zone_high_percent                         # R55, from this CVw and n
    assert "rules 0.4, UNVERIFIED" in auc.rule and auc.csr_status == "none"     # no CSR table in this delivery
    assert any(b.source == "client" for b in study.be)                         # the client's NCA of the same subjects


def _csr_lines(study, *, off_pp: float = 0.0) -> str:
    """The CSR's BE table: our numbers from the client's NCA (Cmax exactly, AUC0–t's GMR moved by `off_pp`)."""
    rows = ["Parameter\tRatio (%)\t90% CI lower\t90% CI upper\tIntra-subject CV (%)"]
    for b in study.be:
        if b.source == "client":
            shift = off_pp if b.metric == "auc_t" else 0.0
            rows.append(f"ln({b.label})\t{b.gmr_percent + shift:.2f}\t{b.ci_low_percent:.2f}\t{b.ci_high_percent:.2f}\t"
                        f"{b.cv_percent:.1f}")
    return "\n".join(rows) + "\n"


def test_the_csrs_gmr_and_ci_are_reproduced_within_half_a_percentage_point_or_said(tmp_path):
    first = assemble(room_inputs(_room(tmp_path / "a"))).studies[0]
    same = assemble(room_inputs(_room(tmp_path / "b", _csr_lines(first)))).studies[0]
    client = {b.metric: b for b in same.be if b.source == "client"}
    assert client["auc_t"].csr_status == "reproduced" and client["auc_t"].csr_difference_pp["ratio"] == 0.0
    assert "cv" in client["auc_t"].csr_difference_pp                           # D3: the CRO's CV beside ours
    assert not any(p.code == "BE_CSR_DIFFERS" for p in same.problems)

    off = assemble(room_inputs(_room(tmp_path / "c", _csr_lines(first, off_pp=1.0)))).studies[0]
    client = {b.metric: b for b in off.be if b.source == "client"}
    assert client["auc_t"].csr_status == "differs" and client["auc_t"].csr_difference_pp["ratio"] == -1.0
    said = [p.message for p in off.problems if p.code == "BE_CSR_DIFFERS"]
    assert len(said) == 1 and said[0].startswith("EX-01, AUC0–t: the CSR's GMR") and "from the client NCA" in said[0]


def test_bioequivalence_is_not_computed_without_one_test_and_one_reference_or_for_a_replicate(tmp_path):
    study = assemble(room_inputs(_room(tmp_path))).studies[0]
    rules = load_rules()
    got, said = be_results(study.model_copy(update={"arms": ()}), set_name="modeling", csr={}, rules=rules)
    assert got == () and [p.code for p in said] == ["BE_NOT_COMPUTED"] and "test and reference" in said[0].message
    twice = study.nca + tuple(r.model_copy(update={"period": "3"}) for r in study.nca if r.treatment == "B")
    got, said = be_results(study.model_copy(update={"nca": twice}), set_name="modeling", csr={}, rules=rules)
    assert got == () and "replicate design" in said[0].message


@pytest.mark.parametrize(("text", "metric"), [("ln(Cmax)", "cmax"), ("Cmax", "cmax"), ("AUC0-t", "auc_t"),
                                              ("Log AUCinf", "auc_inf"), ("AUC0-inf", "auc_inf"), ("Tmax", ""),
                                              ("AUC0-24", "")])
def test_a_csr_line_is_known_by_its_metric(text, metric):
    assert csr_metric(text) == metric


def test_a_csr_ratio_written_as_a_fraction_or_a_percent_is_one_percent():
    from modeler_project.dataroom.bestats import _percent

    assert _percent("0.935") == _percent("93.5") == _percent("93.5 %") == 93.5
    assert _percent("0.21", cv=True) == 21.0 and _percent("21", cv=True) == 21.0
    assert csr_values([]) == {}
