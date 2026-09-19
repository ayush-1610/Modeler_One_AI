"""Engine-image registration record (task T-12).

After the engine image is built and its golden scripts pass, CI records an ``engine_images`` row so every
run and campaign can pin the engine by digest. This module builds that record from the artifacts produced
inside the image (the harvested catalog, the benchmark, and the golden-gate results) and enforces the
qualification gate: a build whose golden scripts did not all pass cannot be registered, so a PR that breaks
a golden test can never publish a usable image.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
# The golden scripts that qualify an image; all must pass before a row is written (F-405).
REQUIRED_GOLDEN = ("roundtrip", "pi_smoke", "tasks")


class RegistrationError(Exception):
    pass


def build_engine_image_registration(
    *,
    digest: str,
    catalog: dict[str, Any],
    benchmark: dict[str, Any],
    golden: dict[str, bool],
    sbom_ref: str | None = None,
) -> dict[str, Any]:
    """Return the ``engine_images`` registration record (status ``BUILT``).

    ``catalog`` is the parsed golden/catalog.json (its ``engine`` block supplies versions and the supported
    snapshot version); ``benchmark`` is the parsed benchmark.json; ``golden`` maps each required golden script
    to whether it passed. Raises ``RegistrationError`` if the digest is malformed or any golden gate failed.
    """
    if not _DIGEST_RE.match(digest):
        raise RegistrationError(f"digest must be 'sha256:<64 hex>', got {digest!r}")

    missing = [name for name in REQUIRED_GOLDEN if name not in golden]
    if missing:
        raise RegistrationError(f"golden results missing for: {', '.join(missing)}")
    failed = [name for name in REQUIRED_GOLDEN if not golden[name]]
    if failed:
        raise RegistrationError(f"golden gate failed for: {', '.join(failed)}; image cannot be registered")

    engine = catalog.get("engine")
    if not engine or "ospsuite" not in engine:
        raise RegistrationError("catalog has no engine block with an ospsuite version")

    snapshot_version = engine.get("snapshot_version")
    if not isinstance(snapshot_version, int):
        raise RegistrationError("catalog engine block has no integer snapshot_version")

    software_versions = {
        "ospsuite": engine["ospsuite"],
        "parameter_identification": engine.get("parameter_identification"),
        "rSharp": engine.get("rSharp"),
        "r_version": engine.get("r_version"),
    }
    software_versions = {k: v for k, v in software_versions.items() if v is not None}

    return {
        "digest": digest,
        "engine_id": f"ospsuite-{engine['ospsuite']}",
        "snapshot_versions": [snapshot_version],
        "status": "BUILT",
        "qualified_contexts": [],
        "platform": engine.get("platform"),
        "software_versions": software_versions,
        "catalog_sha256": _sha256_json(catalog),
        "benchmark": benchmark,
        "sbom_ref": sbom_ref,
        "golden": {name: bool(golden[name]) for name in REQUIRED_GOLDEN},
    }


def _sha256_json(obj: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
