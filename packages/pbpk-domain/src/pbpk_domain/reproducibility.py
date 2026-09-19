"""Reproducibility gate and submission bundle (task T-23).

A submission bundle is the set of files a regulator needs to re-run the model: the CPF, the snapshots, the
engine results and PK tables, the MAP, the parameter-identification specs, the audit chain and the reports.
`assemble_bundle` records each file's SHA-256 in a manifest; `verify_bundle_integrity` re-checks those hashes
so any later tampering fails with a diff; `verify_reproduction` compares a fresh engine re-run to the original —
byte-exact for deterministic files, and within a numeric tolerance for PK/results tables, where a re-run can
differ in the last digits. The comparison never trusts a hash alone for a numeric table: it parses and compares
the values, so a tiny solver difference passes but a real change fails.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class BundleFile:
    path: str            # logical path inside the bundle
    sha256: str
    size_bytes: int
    numeric: bool = False  # a PK/results table compared within tolerance, not byte-exact, on a re-run


@dataclass(frozen=True)
class BundleManifest:
    bundle_id: str
    campaign: str
    files: tuple[BundleFile, ...]
    engine_image_digest: str = ""
    software_versions: dict[str, str] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def content_sha256(self) -> str:
        """A single hash over the file list, so the manifest itself can be signed/compared."""
        payload = "\n".join(f"{f.path}:{f.sha256}:{f.size_bytes}:{int(f.numeric)}" for f in sorted(self.files, key=lambda x: x.path))
        return sha256_bytes(payload.encode("utf-8"))

    def file(self, path: str) -> BundleFile | None:
        return next((f for f in self.files if f.path == path), None)


def assemble_bundle(
    bundle_id: str, campaign: str, files: dict[str, bytes], *,
    numeric_paths: set[str] | None = None, engine_image_digest: str = "", software_versions: dict[str, str] | None = None,
) -> BundleManifest:
    """Hash every file into a manifest; `numeric_paths` marks the PK/results tables compared within tolerance."""
    numeric = numeric_paths or set()
    entries = tuple(
        BundleFile(path=path, sha256=sha256_bytes(data), size_bytes=len(data), numeric=path in numeric)
        for path, data in sorted(files.items())
    )
    return BundleManifest(
        bundle_id=bundle_id, campaign=campaign, files=entries,
        engine_image_digest=engine_image_digest, software_versions=dict(software_versions or {}),
    )


@dataclass(frozen=True)
class FileVerdict:
    path: str
    status: str  # "match" | "within_tolerance" | "mismatch" | "missing" | "unexpected"
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status in ("match", "within_tolerance")


@dataclass(frozen=True)
class ReproReport:
    passes: bool
    verdicts: tuple[FileVerdict, ...]

    def failures(self) -> list[FileVerdict]:
        return [v for v in self.verdicts if not v.ok]


def verify_bundle_integrity(manifest: BundleManifest, files: dict[str, bytes]) -> ReproReport:
    """Every file in the bundle still hashes to its manifest entry (tamper detection at rest)."""
    verdicts: list[FileVerdict] = []
    for entry in manifest.files:
        data = files.get(entry.path)
        if data is None:
            verdicts.append(FileVerdict(entry.path, "missing", "file is absent from the bundle"))
            continue
        actual = sha256_bytes(data)
        if actual == entry.sha256:
            verdicts.append(FileVerdict(entry.path, "match"))
        else:
            verdicts.append(FileVerdict(entry.path, "mismatch", f"sha256 {actual[:12]}… != manifest {entry.sha256[:12]}…"))
    extra = set(files) - {f.path for f in manifest.files}
    verdicts.extend(FileVerdict(p, "unexpected", "file is not listed in the manifest") for p in sorted(extra))
    return ReproReport(passes=all(v.ok for v in verdicts), verdicts=tuple(verdicts))


def _tables_close(original: bytes, rerun: bytes, *, tol: float) -> tuple[bool, str]:
    """Compare two CSVs cell by cell: numbers within `tol` (relative or absolute), everything else exact."""
    a = list(csv.reader(io.StringIO(original.decode("utf-8-sig"))))
    b = list(csv.reader(io.StringIO(rerun.decode("utf-8-sig"))))
    if len(a) != len(b):
        return False, f"row count {len(a)} != {len(b)}"
    for r, (row_a, row_b) in enumerate(zip(a, b, strict=True)):
        if len(row_a) != len(row_b):
            return False, f"row {r}: column count {len(row_a)} != {len(row_b)}"
        for c, (cell_a, cell_b) in enumerate(zip(row_a, row_b, strict=True)):
            if cell_a == cell_b:
                continue
            try:
                fa, fb = float(cell_a), float(cell_b)
            except ValueError:
                return False, f"row {r} col {c}: {cell_a!r} != {cell_b!r}"
            if not math.isclose(fa, fb, rel_tol=tol, abs_tol=tol):
                return False, f"row {r} col {c}: {fa} != {fb} (>|{tol}|)"
    return True, ""


def verify_reproduction(
    manifest: BundleManifest, original_files: dict[str, bytes], rerun_files: dict[str, bytes], *, pk_tol: float = 1e-6,
) -> ReproReport:
    """Compare a fresh re-run to the original bundle: byte-exact for deterministic files, within `pk_tol` for
    the tables marked numeric in the manifest."""
    verdicts: list[FileVerdict] = []
    for entry in manifest.files:
        rerun = rerun_files.get(entry.path)
        if rerun is None:
            verdicts.append(FileVerdict(entry.path, "missing", "the re-run did not produce this file"))
            continue
        if sha256_bytes(rerun) == entry.sha256:
            verdicts.append(FileVerdict(entry.path, "match"))
            continue
        if entry.numeric and entry.path in original_files:
            close, detail = _tables_close(original_files[entry.path], rerun, tol=pk_tol)
            verdicts.append(FileVerdict(entry.path, "within_tolerance" if close else "mismatch", detail))
        else:
            verdicts.append(FileVerdict(entry.path, "mismatch", f"re-run hash {sha256_bytes(rerun)[:12]}… != original {entry.sha256[:12]}…"))
    return ReproReport(passes=all(v.ok for v in verdicts), verdicts=tuple(verdicts))


def bundle_snapshots(manifest: BundleManifest) -> tuple[str, ...]:
    """The snapshot files in the bundle (``snapshots/*.json``), in a stable order."""
    return tuple(sorted(f.path for f in manifest.files if f.path.startswith("snapshots/") and f.path.endswith(".json")))


def generate_rerun_script(manifest: BundleManifest) -> str:
    """Emit ``rerun_all.R``: it re-runs every snapshot in the bundle in a fresh engine, so a reviewer can
    reproduce the results independently. Usage inside the engine pod: ``Rscript rerun_all.R <bundle_dir> <out_dir>``.
    Each snapshot's canonical result CSVs land in ``<out_dir>/<snapshot stem>/`` for comparison against the
    bundle's numeric tables (verify_reproduction, 1e-6 tolerance)."""
    snapshots = bundle_snapshots(manifest)
    listed = ",\n  ".join(f'"{path}"' for path in snapshots)
    return f'''#!/usr/bin/env Rscript
# rerun_all.R — regenerate every simulation in bundle {manifest.bundle_id} ({manifest.campaign}) and export
# results for an independent reproduction check (task T-23). Generated from the bundle manifest; do not edit.
# Requires the pinned engine image (digest {manifest.engine_image_digest or "UNSET"}).
suppressPackageStartupMessages({{ library(ospsuite); library(jsonlite) }})

args <- commandArgs(trailingOnly = TRUE)
bundle_dir <- if (length(args) >= 1) args[[1]] else "."
out_dir <- if (length(args) >= 2) args[[2]] else file.path(bundle_dir, "rerun")
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

initPKSim()
snapshots <- c(
  {listed}
)
for (rel in snapshots) {{
  snap <- file.path(bundle_dir, rel)
  stem <- tools::file_path_sans_ext(basename(rel))
  od <- file.path(out_dir, stem)
  dir.create(od, recursive = TRUE, showWarnings = FALSE)
  cat(sprintf("RERUN %s\\n", rel)); flush(stdout())
  runSimulationsFromSnapshot(snap, output = od, exportCSV = TRUE, exportPKML = FALSE)
}}
cat("RERUN COMPLETE\\n")
'''


def write_bundle_zip(manifest: BundleManifest, files: dict[str, bytes]) -> bytes:
    """Pack the bundle (files + a manifest.json) into a deterministic ZIP for export."""
    import json

    buffer = io.BytesIO()
    manifest_json = json.dumps(
        {
            "bundle_id": manifest.bundle_id, "campaign": manifest.campaign,
            "engine_image_digest": manifest.engine_image_digest, "software_versions": manifest.software_versions,
            "content_sha256": manifest.content_sha256(),
            "files": [{"path": f.path, "sha256": f.sha256, "size_bytes": f.size_bytes, "numeric": f.numeric} for f in manifest.files],
        },
        indent=2, sort_keys=True,
    ).encode("utf-8")
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", manifest_json)
        if bundle_snapshots(manifest):  # ship the reproduction driver so the bundle is self-contained (T-23)
            zf.writestr("rerun_all.R", generate_rerun_script(manifest))
        for path in sorted(files):
            zf.writestr(path, files[path])
    return buffer.getvalue()
