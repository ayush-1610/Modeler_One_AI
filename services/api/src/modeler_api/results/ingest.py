"""Turn the engine's CSV outputs into columnar results and PK parameter rows (task T-08).

Two OSP CSV shapes (verified against ospsuite 12.4.4 output):
- results.csv is wide: columns ``IndividualId``, ``Time [min]`` and one column per output, each header
  ``<path> [<unit>]``. It becomes a long Parquet table (individual_id, time, time_unit, path, unit, value)
  under ``runs/{run_id}/results/`` — the shape the API and evaluation read.
- pk_analyses.csv is long: ``IndividualId, QuantityPath, Parameter, Value, Unit`` — one PK parameter per
  row, kept as ``pk_parameter_values``.

Ingestion is deterministic: the same CSVs always produce the same Parquet bytes (same sha256), so re-running
a run's ingestion is idempotent.
"""

from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

_HEADER_UNIT = re.compile(r"^(?P<name>.*?)(?: \[(?P<unit>.*)\])?$")


@dataclass(frozen=True)
class PkParameterValue:
    individual_id: int
    quantity_path: str
    parameter: str
    value: float
    unit: str | None


@dataclass(frozen=True)
class ParquetInfo:
    path: str
    n_rows: int
    sha256: str


@dataclass(frozen=True)
class IngestResult:
    parquet: ParquetInfo
    pk_values: tuple[PkParameterValue, ...]


def _split_header(header: str) -> tuple[str, str | None]:
    """`"Organism|…|Plasma (…) [µmol/l]"` -> (path, "µmol/l"); `"Time [min]"` -> ("Time", "min")."""
    match = _HEADER_UNIT.match(header.strip())
    assert match is not None  # the pattern always matches
    return match.group("name").strip(), match.group("unit")


_RESULTS_SCHEMA = pa.schema([
    ("individual_id", pa.int32()),
    ("time", pa.float64()),
    ("time_unit", pa.string()),
    ("path", pa.string()),
    ("unit", pa.string()),
    ("value", pa.float64()),
])


def parse_results_csv(path: str | Path) -> pa.Table:
    """Read a wide results CSV and return the long results table."""
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        if len(header) < 2 or _split_header(header[0])[0] != "IndividualId":
            raise ValueError("results CSV must start with IndividualId and a Time column")
        _, time_unit = _split_header(header[1])
        outputs = [(*_split_header(h), col) for col, h in enumerate(header[2:], start=2)]

        individual_id: list[int] = []
        time: list[float] = []
        out_path: list[str] = []
        out_unit: list[str | None] = []
        value: list[float] = []
        for row in reader:
            if not row:
                continue
            iid, t = int(row[0]), float(row[1])
            for opath, ounit, col in outputs:
                individual_id.append(iid)
                time.append(t)
                out_path.append(opath)
                out_unit.append(ounit)
                value.append(float(row[col]))

    return pa.table(
        {
            "individual_id": pa.array(individual_id, pa.int32()),
            "time": pa.array(time, pa.float64()),
            "time_unit": pa.array([time_unit] * len(time), pa.string()),
            "path": pa.array(out_path, pa.string()),
            "unit": pa.array(out_unit, pa.string()),
            "value": pa.array(value, pa.float64()),
        },
        schema=_RESULTS_SCHEMA,
    )


def parse_pk_csv(path: str | Path) -> list[PkParameterValue]:
    """Read a pk_analyses CSV into PK parameter values."""
    values: list[PkParameterValue] = []
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            unit = (row.get("Unit") or "").strip() or None
            values.append(PkParameterValue(
                individual_id=int(row["IndividualId"]),
                quantity_path=row["QuantityPath"],
                parameter=row["Parameter"],
                value=float(row["Value"]),
                unit=unit,
            ))
    return values


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_results_parquet(table: pa.Table, destination: str | Path) -> ParquetInfo:
    """Write the long results table to Parquet deterministically (stable bytes -> stable sha256)."""
    dest = Path(destination)
    dest.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, dest, compression="zstd", version="2.6", store_schema=True)
    return ParquetInfo(path=str(dest), n_rows=table.num_rows, sha256=_sha256(dest))


def ingest_results(results_csv: str | Path, pk_csv: str | Path, out_dir: str | Path, *, run_id: str = "run") -> IngestResult:
    """Ingest one run's CSV outputs: write the results Parquet and parse the PK parameter values."""
    table = parse_results_csv(results_csv)
    parquet = write_results_parquet(table, Path(out_dir) / "runs" / run_id / "results" / "results.parquet")
    pk_values = tuple(parse_pk_csv(pk_csv))
    return IngestResult(parquet=parquet, pk_values=pk_values)
