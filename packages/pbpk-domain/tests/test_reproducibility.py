from __future__ import annotations

import io
import zipfile

import pytest

from pbpk_domain.reproducibility import (
    assemble_bundle,
    sha256_bytes,
    verify_bundle_integrity,
    verify_reproduction,
    write_bundle_zip,
)

RESULTS = b"IndividualId,Time [min],Plasma\n0,0,0\n0,1,3.254684\n0,2,10.44706\n"


def _files() -> dict[str, bytes]:
    return {
        "cpf.json": b'{"compound":"Drug","version":3}',
        "snapshots/S1-r1.json": b'{"Version":80}',
        "results/S1-r1.csv": RESULTS,
        "audit/chain.jsonl": b'{"seq":1}\n{"seq":2}\n',
    }


def _manifest():
    return assemble_bundle("bnd-1", "Drug", _files(), numeric_paths={"results/S1-r1.csv"})


# --- assembly + integrity ------------------------------------------------------------------------


def test_assemble_records_hashes_and_marks_numeric():
    m = _manifest()
    assert {f.path for f in m.files} == set(_files())
    assert m.file("cpf.json").sha256 == sha256_bytes(_files()["cpf.json"])
    assert m.file("results/S1-r1.csv").numeric is True
    assert m.file("cpf.json").numeric is False
    assert len(m.content_sha256()) == 64


def test_integrity_passes_for_untouched_bundle():
    m = _manifest()
    assert verify_bundle_integrity(m, _files()).passes


@pytest.mark.req("T-23")
def test_tampered_file_fails_integrity_with_a_diff():
    m = _manifest()
    tampered = _files()
    tampered["cpf.json"] = b'{"compound":"Drug","version":4}'  # someone edited the CPF
    report = verify_bundle_integrity(m, tampered)
    assert report.passes is False
    (bad,) = [v for v in report.failures() if v.path == "cpf.json"]
    assert bad.status == "mismatch" and "!=" in bad.detail


def test_missing_and_unexpected_files_fail_integrity():
    m = _manifest()
    files = _files()
    del files["audit/chain.jsonl"]
    files["extra.txt"] = b"stray"
    statuses = {v.path: v.status for v in verify_bundle_integrity(m, files).verdicts}
    assert statuses["audit/chain.jsonl"] == "missing"
    assert statuses["extra.txt"] == "unexpected"


# --- reproduction gate ---------------------------------------------------------------------------


def test_identical_rerun_reproduces():
    m = _manifest()
    assert verify_reproduction(m, _files(), _files()).passes


def test_pk_table_within_tolerance_passes():
    m = _manifest()
    rerun = _files()
    # a re-run differs only in the last digits of the concentrations -> within 1e-6
    rerun["results/S1-r1.csv"] = b"IndividualId,Time [min],Plasma\n0,0,0\n0,1,3.2546841\n0,2,10.4470601\n"
    report = verify_reproduction(m, _files(), rerun)
    assert report.passes
    assert next(v for v in report.verdicts if v.path == "results/S1-r1.csv").status == "within_tolerance"


def test_pk_table_beyond_tolerance_fails_with_a_diff():
    m = _manifest()
    rerun = _files()
    rerun["results/S1-r1.csv"] = b"IndividualId,Time [min],Plasma\n0,0,0\n0,1,3.9\n0,2,10.44706\n"  # a real change
    report = verify_reproduction(m, _files(), rerun)
    assert report.passes is False
    (bad,) = [v for v in report.failures() if v.path == "results/S1-r1.csv"]
    assert bad.status == "mismatch" and "3.254684" in bad.detail


def test_deterministic_file_change_fails_even_if_small():
    m = _manifest()
    rerun = _files()
    rerun["cpf.json"] = b'{"compound":"Drug","version":30}'  # not a numeric table -> byte-exact required
    report = verify_reproduction(m, _files(), rerun)
    assert not report.passes
    assert next(v for v in report.verdicts if v.path == "cpf.json").status == "mismatch"


def test_missing_rerun_output_fails():
    m = _manifest()
    rerun = _files()
    del rerun["results/S1-r1.csv"]
    assert not verify_reproduction(m, _files(), rerun).passes


# --- zip export ----------------------------------------------------------------------------------


def test_zip_export_contains_files_and_manifest():
    m = _manifest()
    blob = write_bundle_zip(m, _files())
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = set(zf.namelist())
        assert "manifest.json" in names and "cpf.json" in names and "results/S1-r1.csv" in names
        assert zf.read("cpf.json") == _files()["cpf.json"]
        import json
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["content_sha256"] == m.content_sha256()
        assert manifest["campaign"] == "Drug"

# --- rerun driver generation (T-23 BundleWorkflow) -----------------------------------------------


def test_bundle_snapshots_are_listed_in_order():
    from pbpk_domain.reproducibility import bundle_snapshots

    files = {
        "snapshots/S2-r1.json": b"{}", "snapshots/S1-r1.json": b"{}",
        "results/S1-r1.csv": RESULTS, "cpf.json": b"{}",
    }
    m = assemble_bundle("b", "Drug", files, numeric_paths={"results/S1-r1.csv"})
    assert bundle_snapshots(m) == ("snapshots/S1-r1.json", "snapshots/S2-r1.json")


@pytest.mark.req("T-23")
def test_generate_rerun_script_covers_every_snapshot():
    from pbpk_domain.reproducibility import generate_rerun_script

    files = {"snapshots/S1-r1.json": b'{"Version":80}', "snapshots/S2-r1.json": b'{"Version":80}',
             "results/S1-r1.csv": RESULTS}
    m = assemble_bundle("bnd-1", "Aciclovir", files, numeric_paths={"results/S1-r1.csv"},
                        engine_image_digest="sha256:abc")
    script = generate_rerun_script(m)
    assert "runSimulationsFromSnapshot" in script and "initPKSim()" in script
    assert '"snapshots/S1-r1.json"' in script and '"snapshots/S2-r1.json"' in script
    assert "sha256:abc" in script  # pins the engine image in a comment


def test_zip_includes_rerun_driver_when_snapshots_present():
    files = {"snapshots/S1-r1.json": b'{"Version":80}', "results/S1-r1.csv": RESULTS, "cpf.json": b"{}"}
    m = assemble_bundle("b", "Drug", files, numeric_paths={"results/S1-r1.csv"})
    with zipfile.ZipFile(io.BytesIO(write_bundle_zip(m, files))) as zf:
        assert "rerun_all.R" in zf.namelist()
        assert b"RERUN COMPLETE" in zf.read("rerun_all.R")
