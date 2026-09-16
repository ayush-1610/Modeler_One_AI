"""T-08: ingest a real OSP run (golden Aciclovir output) and reproduce its PK table; verify idempotency
and the DuckDB query path. The sample CSVs were produced by ospsuite 12.4.4 (services/engine-worker/
golden/results_sample)."""

from __future__ import annotations

from pathlib import Path

import pytest

from modeler_api.results import ingest_results, parse_pk_csv
from modeler_api.results.query import concentration_series, output_paths, query_results

SAMPLE = Path(__file__).parents[3] / "services" / "engine-worker" / "golden" / "results_sample"
RESULTS_CSV = SAMPLE / "results.csv"
PK_CSV = SAMPLE / "pk_analyses.csv"
PLASMA = "Organism|PeripheralVenousBlood|Aciclovir|Plasma (Peripheral Venous Blood)"


@pytest.fixture(scope="module")
def sample_exists():
    if not RESULTS_CSV.exists() or not PK_CSV.exists():
        pytest.skip("golden results sample not present")


def test_ingest_writes_long_parquet(sample_exists, tmp_path):
    result = ingest_results(RESULTS_CSV, PK_CSV, tmp_path, run_id="run-1")
    series = concentration_series(result.parquet.path, PLASMA, individual_id=0)
    # wide -> long: two output paths, so rows == 2 x the number of time points
    assert result.parquet.n_rows == 2 * len(series)
    assert series[0] == (0.0, 0.0)
    assert series[1] == pytest.approx((1.0, 3.254684))
    assert set(output_paths(result.parquet.path)) == {
        PLASMA, "Organism|VenousBlood|Plasma|Aciclovir|Plasma Unbound"
    }


def test_reproduces_pk_table(sample_exists, tmp_path):
    result = ingest_results(RESULTS_CSV, PK_CSV, tmp_path, run_id="run-2")
    by_param = {v.parameter: v for v in result.pk_values if v.quantity_path == PLASMA}
    assert by_param["C_max"].value == pytest.approx(50.25272)
    assert by_param["C_max"].unit == "µmol/l"
    assert by_param["t_max"].value == pytest.approx(0.18333334)
    assert by_param["t_max"].unit == "h"
    assert by_param["AUC_tEnd"].value == pytest.approx(4064.1245)
    # the parsed PK values equal a direct parse of the CSV (no rows lost/added)
    assert len(result.pk_values) == len(parse_pk_csv(PK_CSV))


def test_ingestion_is_idempotent(sample_exists, tmp_path):
    first = ingest_results(RESULTS_CSV, PK_CSV, tmp_path / "a", run_id="r")
    second = ingest_results(RESULTS_CSV, PK_CSV, tmp_path / "b", run_id="r")
    assert first.parquet.sha256 == second.parquet.sha256
    assert first.parquet.n_rows == second.parquet.n_rows


def test_query_results_filters_by_path(sample_exists, tmp_path):
    result = ingest_results(RESULTS_CSV, PK_CSV, tmp_path, run_id="run-3")
    rows = query_results(result.parquet.path, path=PLASMA, individual_id=0)
    assert len(rows) == result.parquet.n_rows // 2
    assert all(r["path"] == PLASMA for r in rows)
    assert rows[0]["time"] == 0.0
    assert rows[0]["time_unit"] == "min"
    assert rows[0]["unit"] == "µmol/l"
