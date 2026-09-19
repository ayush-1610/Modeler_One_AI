from __future__ import annotations

import pytest

from modeler_engine.registration import RegistrationError, build_engine_image_registration

DIGEST = "sha256:" + "a" * 64
CATALOG = {
    "engine": {
        "ospsuite": "12.4.4", "parameter_identification": "2.2.0", "rSharp": "1.2.2",
        "r_version": "R version 4.6.1 (2026-06-24)", "platform": "x86_64-conda-linux-gnu",
        "snapshot_version": 80,
    },
    "process_types": ["MetabolizationSpecific_FirstOrder", "GlomerularFiltration"],
}
BENCHMARK = {"seconds_per_simulation": 0.506, "cores": 48}
GOLDEN_OK = {"roundtrip": True, "pi_smoke": True, "tasks": True}


def test_registration_record_has_schema_fields():
    rec = build_engine_image_registration(digest=DIGEST, catalog=CATALOG, benchmark=BENCHMARK, golden=GOLDEN_OK,
                                          sbom_ref="ghcr.io/x/engine@sha256:bbb")
    assert rec["digest"] == DIGEST
    assert rec["engine_id"] == "ospsuite-12.4.4"
    assert rec["snapshot_versions"] == [80]
    assert rec["status"] == "BUILT"
    assert rec["qualified_contexts"] == []
    assert rec["software_versions"]["ospsuite"] == "12.4.4"
    assert rec["benchmark"]["seconds_per_simulation"] == 0.506
    assert len(rec["catalog_sha256"]) == 64
    assert rec["sbom_ref"].endswith("sha256:bbb")


def test_catalog_sha_is_stable_regardless_of_key_order():
    reordered = {"process_types": CATALOG["process_types"], "engine": CATALOG["engine"]}
    a = build_engine_image_registration(digest=DIGEST, catalog=CATALOG, benchmark=BENCHMARK, golden=GOLDEN_OK)
    b = build_engine_image_registration(digest=DIGEST, catalog=reordered, benchmark=BENCHMARK, golden=GOLDEN_OK)
    assert a["catalog_sha256"] == b["catalog_sha256"]


def test_bad_digest_is_rejected():
    with pytest.raises(RegistrationError, match="digest must be"):
        build_engine_image_registration(digest="latest", catalog=CATALOG, benchmark=BENCHMARK, golden=GOLDEN_OK)


@pytest.mark.req("T-12")
def test_failed_golden_gate_blocks_registration():
    with pytest.raises(RegistrationError, match="golden gate failed for: tasks"):
        build_engine_image_registration(digest=DIGEST, catalog=CATALOG, benchmark=BENCHMARK,
                                        golden={"roundtrip": True, "pi_smoke": True, "tasks": False})


def test_missing_golden_result_is_rejected():
    with pytest.raises(RegistrationError, match="golden results missing for: tasks"):
        build_engine_image_registration(digest=DIGEST, catalog=CATALOG, benchmark=BENCHMARK,
                                        golden={"roundtrip": True, "pi_smoke": True})


def test_catalog_without_engine_block_is_rejected():
    with pytest.raises(RegistrationError, match="no engine block"):
        build_engine_image_registration(digest=DIGEST, catalog={"process_types": []}, benchmark=BENCHMARK,
                                        golden=GOLDEN_OK)
