"""The production deployment's Part 11 records in PostgreSQL (production readiness P2; plan
docs/plans/2026-10-15-part11-records-postgres.md).

With ``MODELER_PART11_STORE=postgres`` (a production deployment must set it, `config.check_part11`), every audit
event is copied into the database before its file line is written (the project store's audit mirror), and every
signature becomes a row as soon as it is taken. Pilot and development deployments keep the files only.
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from modeler_storage.part11 import Part11Store, verify_all

if TYPE_CHECKING:
    from modeler_api.compliance.signatures import Signature
    from modeler_api.config import Settings
    from modeler_project.audit import AuditMirror


@lru_cache
def _store(database_url: str) -> Part11Store:
    return Part11Store(database_url)


def part11_store(settings: Settings) -> Part11Store | None:
    """The Part 11 database of this deployment, or None when it keeps the files only."""
    return _store(settings.database_url) if settings.part11_store == "postgres" else None


def audit_mirror(settings: Settings) -> AuditMirror | None:
    store = part11_store(settings)
    return store.mirror_audit if store is not None else None


def record_signature(settings: Settings, tenant_id: str, signature: Signature) -> None:
    """The signature as a Part 11 row (no-op without the database). Called right after the signature is taken and
    before the record it signs is applied, so a refusal here stops the action."""
    store = part11_store(settings)
    if store is None:
        return
    store.record_signature(
        tenant_id, signature_id=signature.signature_id, signer_subject=signature.signer_id,
        printed_name=signature.printed_name, meaning=str(signature.meaning), signed_at=signature.signed_at,
        record_type=signature.record_type, record_id=signature.record_id, record_sha256=signature.record_sha256,
        auth_method=signature.auth_method)


def main(argv: list[str] | None = None) -> int:
    """``python -m modeler_api.part11 verify``: the Part 11 copy against the file chains, with this deployment's settings
    (MODELER_READ_ROOT, MODELER_DATABASE_URL: the URL holds a password, so it is never a command-line argument)."""
    from modeler_api.config import get_settings

    if (argv if argv is not None else sys.argv[1:]) != ["verify"]:
        print("usage: python -m modeler_api.part11 verify", file=sys.stderr)
        return 2
    settings = get_settings()
    if settings.part11_store != "postgres" or not settings.read_root:
        print("part11 verify: this deployment keeps its Part 11 records in files only (MODELER_PART11_STORE)")
        return 0
    tenants, problems = verify_all(Path(settings.read_root), settings.database_url)
    for problem in problems:
        print(problem)
    print(f"part11 verify: {tenants} tenant(s), {'OK' if not problems else f'{len(problems)} problem(s)'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
