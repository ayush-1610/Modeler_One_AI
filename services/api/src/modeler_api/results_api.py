"""Serve ingested run results (GET /runs/{id}/results, task T-08 API surface).

Reads the run's Parquet with DuckDB (`pbpk_domain`/results.query). Results are scoped to the caller's tenant
from the token — the tenant is part of the Parquet path — so a principal only reads its own tenant's runs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from modeler_api.auth import CurrentPrincipal
from modeler_api.config import get_settings
from modeler_api.results.query import concentration_series, output_paths, query_results

router = APIRouter(prefix="/api/v1", tags=["results"])


def get_results_dir() -> Path | None:
    """Local base directory of ingested results when the store is a file:// root, else None."""
    settings = get_settings()
    uri = settings.results_root or settings.object_store_uri
    prefix = "file://"
    return Path(uri[len(prefix):]) if uri.startswith(prefix) else None


def _run_parquet(results_dir: Path, tenant_id: str, run_id: str) -> Path:
    return results_dir / "tenants" / tenant_id / "runs" / run_id / "results.parquet"


@router.get("/runs/{run_id}/results")
def get_run_results(
    run_id: str,
    principal: CurrentPrincipal,
    results_dir: Annotated[Path | None, Depends(get_results_dir)],
    path: str | None = Query(default=None, description="output path; omit to list the available paths"),
    individual_id: int = 0,
    limit: int = Query(default=1000, ge=1, le=50000),
) -> dict[str, Any]:
    if results_dir is None:
        raise HTTPException(status_code=503, detail="Result storage is not a local path; reads go through the storage adapter.")
    parquet = _run_parquet(results_dir, principal.tenant_id, run_id)
    if not parquet.exists():
        raise HTTPException(status_code=404, detail=f"no ingested results for run {run_id}")
    if path is None:
        return {"run_id": run_id, "output_paths": output_paths(parquet)}
    series = concentration_series(parquet, path, individual_id=individual_id)
    if not series:
        # path present but no rows: report the rows that do exist so the caller can see valid paths
        rows = query_results(parquet, individual_id=individual_id, limit=limit)
        raise HTTPException(status_code=404, detail=f"no series for path {path!r} (individual {individual_id}); {len(rows)} rows for other paths")
    return {
        "run_id": run_id, "path": path, "individual_id": individual_id,
        "series": [{"time": t, "value": v} for t, v in series],
    }
