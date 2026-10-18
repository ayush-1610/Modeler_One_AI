"""What a campaign start checks before anything runs (run integrity, 2026-10-18).

The MAP is the signed contract the campaign follows (MS-01; ICH M15). A pilot or production deployment starts a
campaign only on a MAP a person signed: the MAP document itself (Approve and Sign in the model plan, P5), or an
approval signature recorded on its exact bytes (`campaign:prepare` followed by a `map_approval` signature; every
signature is an audit event, `modeler_api.part11.record_signature`). A development deployment (tests, the reference
runs in CI) may start an unsigned one: its DEV verifier signs nothing that counts.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlparse

from fastapi import HTTPException

from modeler_contracts.runtime import runtime_env

if TYPE_CHECKING:
    from modeler_api.config import Settings


def _map_bytes(map_uri: str) -> bytes | None:
    parsed = urlparse(map_uri)
    if parsed.scheme != "file":
        return None
    path = Path(unquote(parsed.path))
    return path.read_bytes() if path.is_file() else None


def map_signed(settings: Settings, tenant_id: str, map_uri: str) -> bool:
    """Whether a person signed the MAP at `map_uri`: its document carries the signature, or the audit trail holds a
    `map_approval` signature on its SHA-256."""
    data = _map_bytes(map_uri) if map_uri else None
    if data is None:
        return False
    try:
        doc = json.loads(data)
    except ValueError:
        return False
    if doc.get("status") == "SIGNED" and doc.get("signature"):
        return True
    if not settings.read_root:
        return False
    from modeler_project import FileProjectStore

    sha = hashlib.sha256(data).hexdigest()
    return any(r.event.action == "signature.create" and r.event.resource_type == "map_approval"
               and (r.event.after or {}).get("record_sha256") == sha
               for r in FileProjectStore(settings.read_root).audit(tenant_id).records())


def require_signed_map(settings: Settings, tenant_id: str, map_uri: str) -> None:
    """409 unless the MAP is signed, on a pilot or production deployment."""
    if runtime_env().deployment_kind == "development":
        return
    if not map_signed(settings, tenant_id, map_uri):
        raise HTTPException(status_code=409, detail="This campaign's MAP is not signed. Approve and sign it in the model "
                                                    "plan before the campaign can start.")
