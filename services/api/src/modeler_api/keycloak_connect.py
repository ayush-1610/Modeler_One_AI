"""The last step of `deploy/server/keycloak.sh connect`: the console's Keycloak service account, connected from the server
once, so no step is ever done in Keycloak's own console (the owner, 2026-11-27: "enable from here only").

The shell script creates (or repairs) the client `modeler-admin-api`, gives its service account `realm-management`'s
four user roles and has Keycloak generate a new secret. The secret reaches this module on standard input only (never on
a command line, in the environment or in a file). Here it is tested first, as the Keys page tests a key: a token for
the service account, then one read of the realm's people. A secret that fails is not stored. One that works is sealed
under the master key as a new `keycloak` key and made active, retiring the one before it. Both steps are audit events
(`admin.key.add`, `admin.key.activate`) on the platform owner's chain, the chain the console's own key changes go to,
naming the key by its last 4 characters and the Keycloak administrator who ran the script.

    printf %s "$SECRET" | uv run python -m modeler_api.keycloak_connect --by "keycloak:admin via keycloak.sh connect"
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from modeler_api import keycloak_admin as kc
from modeler_api import platform_settings as ps
from modeler_api.config import Settings, get_settings
from modeler_api.part11 import audit_mirror
from modeler_project import FileProjectStore

LABEL = "Keycloak service account (keycloak.sh connect)"
REASON = "the console connected to Keycloak from the server (keycloak.sh connect)"
OWNER_ROLE = "modeler-admin"
NO_OWNER_CHAIN = "_platform"      # a folder name `_companies` never lists as a company


class ConnectError(RuntimeError):
    """The secret does not work, or the platform cannot keep it; the message says what to do."""


def _named(record: dict[str, Any]) -> dict[str, Any]:
    """A key as the audit trail names it (as the Keys routes do): never a secret."""
    return {"provider": record["provider"], "label": record["label"], "state": record["state"],
            "last4": {f: v["last4"] for f, v in record["secret"].items()}}


def owner_chains(directory: kc.Directory) -> list[str]:
    """The companies of the people holding the platform owner's role: where the console's own changes are audited."""
    return sorted({p["tenant_id"] for p in directory.people() if OWNER_ROLE in p["roles"] and p["tenant_id"]})


def connect(settings: Settings, secret: str, *, by: str, reason: str = REASON) -> str:
    """Test the secret, store it as the active `keycloak` key, audit both steps. What happened, in words."""
    if not settings.read_root:
        raise ConnectError("MODELER_READ_ROOT is not set: run this through deploy/server/keycloak.sh, which reads the "
                           "server's settings")
    fields = {"client_id": kc.SERVICE_CLIENT, "client_secret": secret.strip()}
    ok, message = kc.test_key(settings, fields)
    if not ok:
        raise ConnectError(f"the new secret does not work, so it was not stored: {message}")
    store = ps.KeyStore(settings.read_root, settings.master_key)
    try:
        added = store.add("keycloak", LABEL, fields, by=by)
        store.record_test(added["id"], ok, message)
        active, replaced = store.activate(added["id"])
    except ps.SettingsError as exc:
        raise ConnectError(f"the platform could not keep the secret: {exc}") from exc
    chains = owner_chains(kc.directory_for(settings)) or [NO_OWNER_CHAIN]
    audit = FileProjectStore(settings.read_root, audit_mirror=audit_mirror(settings))
    for tenant in chains:
        trail = audit.audit(tenant)
        trail.append(actor=by, action="admin.key.add", resource_type="platform", resource_id=added["id"],
                     after=_named(added), reason=reason)
        trail.append(actor=by, action="admin.key.activate", resource_type="platform", resource_id=added["id"],
                     after=_named(active) | {"retired": replaced}, reason=reason)
    was = f", replacing {replaced}" if replaced else ""
    return (f"connected: {message}. Key {added['id']} (…{fields['client_secret'][-4:]}) is active{was}; audited on "
            f"{', '.join(chains)}. Admin → People now adds and changes people.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m modeler_api.keycloak_connect",
                                     description="Store the console's Keycloak service-account secret, read from stdin.")
    parser.add_argument("--by", required=True, help="who connected it, for the audit trail")
    parser.add_argument("--reason", default=REASON)
    args = parser.parse_args(argv)
    secret = sys.stdin.read().strip()
    if not secret:
        print("keycloak connect: no secret on standard input", file=sys.stderr)
        return 2
    try:
        print(connect(get_settings(), secret, by=args.by, reason=args.reason))
    except (ConnectError, kc.DirectoryError, ps.SettingsError) as exc:
        print(f"keycloak connect: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
