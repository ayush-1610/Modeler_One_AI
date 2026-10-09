"""Published reference models (OSP library) as CPFs and studies — the pipeline's real-data ground truth.

`import_osp_snapshot` and `import_osp_system` here are the importer's own (`osp_import`) with the recorded dataset
exclusions applied (`exclusions.yaml`, MS-01 D5); every caller imports through them.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from pbpk_domain.reference import osp_import
from pbpk_domain.reference.exclusions import without_excluded
from pbpk_domain.reference.osp_import import ReferenceImport, ReferenceImportError, SystemImport


def import_osp_snapshot(snapshot: dict[str, Any], *args: Any, **kwargs: Any) -> ReferenceImport:
    kept, excluded = without_excluded(snapshot)
    imported = osp_import.import_osp_snapshot(kept, *args, **kwargs)
    return replace(imported, skipped=(*imported.skipped, *excluded)) if excluded else imported


def import_osp_system(snapshot: dict[str, Any], *args: Any, **kwargs: Any) -> SystemImport:
    kept, excluded = without_excluded(snapshot)
    imported = osp_import.import_osp_system(kept, *args, **kwargs)
    return replace(imported, skipped=(*imported.skipped, *excluded)) if excluded else imported


__all__ = ["ReferenceImport", "ReferenceImportError", "SystemImport", "import_osp_snapshot", "import_osp_system"]
