"""Read ingested results back with DuckDB (serves `GET /runs/{id}/results`, task T-08).

DuckDB reads the Parquet directly, so a concentration-time series or a filtered slice is a single query
with no data loaded into the API process beyond the rows returned.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb


def query_results(parquet_path: str | Path, *, path: str | None = None,
                  individual_id: int | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    """Return result rows, optionally filtered by output path and/or individual, ordered by time."""
    clauses, params = [], []
    if path is not None:
        clauses.append("path = ?")
        params.append(path)
    if individual_id is not None:
        clauses.append("individual_id = ?")
        params.append(individual_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    tail = f"LIMIT {int(limit)}" if limit is not None else ""
    sql = f"SELECT individual_id, time, time_unit, path, unit, value FROM read_parquet(?) {where} ORDER BY path, individual_id, time {tail}"
    with duckdb.connect() as conn:
        cursor = conn.execute(sql, [str(parquet_path), *params])
        columns = [c[0] for c in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def concentration_series(parquet_path: str | Path, path: str, *, individual_id: int = 0) -> list[tuple[float, float]]:
    """Return the (time, value) series for one output path and individual."""
    with duckdb.connect() as conn:
        rows = conn.execute(
            "SELECT time, value FROM read_parquet(?) WHERE path = ? AND individual_id = ? ORDER BY time",
            [str(parquet_path), path, individual_id],
        ).fetchall()
    return [(float(t), float(v)) for t, v in rows]


def output_paths(parquet_path: str | Path) -> list[str]:
    with duckdb.connect() as conn:
        rows = conn.execute("SELECT DISTINCT path FROM read_parquet(?) ORDER BY path", [str(parquet_path)]).fetchall()
    return [r[0] for r in rows]
