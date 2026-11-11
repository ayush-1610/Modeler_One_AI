"""The people and companies of the admin console (docs/plans/2026-11-10-admin-console.md, F), kept in Keycloak.

The console reaches Keycloak's admin API on the local back channel (`MODELER_OIDC_JWKS_URL`'s host, `127.0.0.1:8080`)
as the realm's service account `modeler-admin-api`, whose client secret the owner stores under Keys (provider
`keycloak`, sealed under the master key). The account holds only `realm-management`'s `view-realm`, `view-users`,
`query-users` and `manage-users` (deploy/keycloak/README.md).

What it never does (CLAUDE.md, the plan's §2): it never sets, reads or sends a password. A new person sets their own:
through the link Keycloak emails them when the realm has a mail server, or, without one, after the owner sets a
temporary password in Keycloak's own console (the console links to the person's Credentials page). It never deletes a
person: people are disabled. It never grants `modeler-admin`, held by the platform's owner alone.

`Directory` is what the routes use; the tests replace it with an in-memory one.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Annotated, Any, Protocol

from fastapi import Depends

from modeler_api import platform_settings as ps
from modeler_api.config import Settings, SettingsDep

SERVICE_CLIENT = "modeler-admin-api"
# The roles the console gives and takes; `modeler-admin` (the platform's owner) only in Keycloak's own console.
ROLES = ("modeler-viewer", "modeler-curator", "modeler-reviewer", "modeler-qa")
SHOWN_ROLES = (*ROLES, "modeler-admin")
FIRST_SIGN_IN = ("UPDATE_PASSWORD", "CONFIGURE_TOTP")      # a new person's own password and authenticator
EMAIL_LINK_SECONDS = 12 * 3600
TIMEOUT_S = 20


class DirectoryError(RuntimeError):
    """Keycloak refused, or is not reachable or not set up for the console; the message says which and what to do."""


class Directory(Protocol):
    problem: str | None

    def smtp(self) -> bool: ...
    def people(self) -> list[dict[str, Any]]: ...
    def create(self, *, username: str, email: str, first_name: str, last_name: str, tenant_id: str,
               roles: list[str]) -> str: ...
    def set_enabled(self, user_id: str, enabled: bool) -> None: ...
    def set_tenant(self, user_id: str, tenant_id: str) -> None: ...
    def set_roles(self, user_id: str, *, add: list[str], remove: list[str]) -> None: ...
    def require(self, user_id: str, actions: list[str]) -> None: ...
    def email_actions(self, user_id: str, actions: list[str]) -> None: ...
    def remove_authenticator(self, user_id: str) -> int: ...
    def console_link(self, user_id: str, tab: str = "credentials") -> str: ...


def _realm_urls(settings: Settings) -> tuple[str, str, str]:
    """(back channel base, realm, public base) from the API's own Keycloak settings."""
    jwks, issuer = settings.oidc_jwks_url or "", settings.oidc_issuer or ""
    if "/realms/" not in jwks or "/realms/" not in issuer:
        raise DirectoryError("this deployment does not sign in through Keycloak (MODELER_OIDC_JWKS_URL and "
                             "MODELER_OIDC_ISSUER unset): people are managed only on a production server")
    base, rest = jwks.split("/realms/", 1)
    return base, rest.split("/", 1)[0], issuer.split("/realms/", 1)[0]


class KeycloakDirectory:
    """Keycloak's admin REST API, as the service account (urllib: no client library is added for it)."""

    def __init__(self, base: str, realm: str, public: str, client_id: str, client_secret: str):
        self.problem: str | None = None
        self._base, self._realm, self._public = base.rstrip("/"), realm, public.rstrip("/")
        self._client = (client_id, client_secret)
        self._token: str | None = None

    # --- transport ---------------------------------------------------------------------------------------------------

    def _send(self, request: urllib.request.Request) -> tuple[int, dict[str, str], Any]:
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as answer:   # the configured back channel only
                raw = answer.read()
                return answer.status, dict(answer.headers), json.loads(raw) if raw.strip() else None
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            try:
                parsed = json.loads(detail)
                detail = parsed.get("errorMessage") or parsed.get("error_description") or parsed.get("error") or detail
            except (ValueError, AttributeError):
                pass
            if exc.code in (401, 403):
                raise DirectoryError(f"Keycloak refused the service account ({exc.code}: {detail}): check its secret "
                                     f"under Keys and its realm-management roles") from exc
            if exc.code == 409:
                raise DirectoryError(f"Keycloak already has that person ({detail})") from exc
            raise DirectoryError(f"Keycloak answered {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise DirectoryError(f"Keycloak does not answer at {self._base} ({exc}): is it running?") from exc

    def _bearer(self) -> str:
        if self._token is None:
            form = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": self._client[0],
                                           "client_secret": self._client[1]}).encode()
            url = f"{self._base}/realms/{self._realm}/protocol/openid-connect/token"
            _, _, body = self._send(urllib.request.Request(url, data=form, method="POST"))
            self._token = str(body["access_token"])
        return self._token

    def _call(self, method: str, path: str, body: Any = None, query: dict[str, Any] | None = None) -> tuple[dict, Any]:
        url = f"{self._base}/admin/realms/{self._realm}{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(url, data=data, method=method,
                                         headers={"Authorization": f"Bearer {self._bearer()}",
                                                  "Content-Type": "application/json"})
        _, headers, answer = self._send(request)
        return headers, answer

    # --- the directory -----------------------------------------------------------------------------------------------

    def check(self) -> None:
        """One read with the service account: its secret and its roles work."""
        self._call("GET", "/users", query={"max": 1})

    def smtp(self) -> bool:
        _, realm = self._call("GET", "")
        return bool((realm or {}).get("smtpServer", {}).get("host"))

    def people(self) -> list[dict[str, Any]]:
        _, users = self._call("GET", "/users", query={"briefRepresentation": "false", "max": 2000})
        holders: dict[str, set[str]] = {}
        for role in SHOWN_ROLES:
            _, members = self._call("GET", f"/roles/{role}/users", query={"max": 2000})
            for member in members or []:
                holders.setdefault(member["id"], set()).add(role)
        return [{"id": u["id"], "username": u.get("username", ""), "email": u.get("email") or "",
                 "first_name": u.get("firstName") or "", "last_name": u.get("lastName") or "",
                 "tenant_id": ((u.get("attributes") or {}).get("tenant_id") or [""])[0],
                 "enabled": bool(u.get("enabled")), "authenticator": bool(u.get("totp")),
                 "required_actions": list(u.get("requiredActions") or []),
                 "created_ms": u.get("createdTimestamp"), "roles": sorted(holders.get(u["id"], set()))}
                for u in users or [] if not str(u.get("username", "")).startswith("service-account-")]

    def _user(self, user_id: str) -> dict[str, Any]:
        _, user = self._call("GET", f"/users/{user_id}")
        return user

    def _put_user(self, user: dict[str, Any]) -> None:
        # the whole representation back: a partial one would drop the attributes it leaves out (`projects`)
        self._call("PUT", f"/users/{user['id']}", user)

    def create(self, *, username: str, email: str, first_name: str, last_name: str, tenant_id: str,
               roles: list[str]) -> str:
        headers, _ = self._call("POST", "/users", {
            "username": username, "email": email, "firstName": first_name, "lastName": last_name, "enabled": True,
            "emailVerified": True, "attributes": {"tenant_id": [tenant_id]}, "requiredActions": list(FIRST_SIGN_IN)})
        location = headers.get("Location") or headers.get("location") or ""
        user_id = location.rstrip("/").rsplit("/", 1)[-1]
        if not user_id:
            raise DirectoryError("Keycloak created the person but did not say their id")
        self.set_roles(user_id, add=roles, remove=[])
        return user_id

    def set_enabled(self, user_id: str, enabled: bool) -> None:
        user = self._user(user_id)
        user["enabled"] = enabled
        self._put_user(user)

    def set_tenant(self, user_id: str, tenant_id: str) -> None:
        user = self._user(user_id)
        user["attributes"] = {**(user.get("attributes") or {}), "tenant_id": [tenant_id]}
        self._put_user(user)

    def set_roles(self, user_id: str, *, add: list[str], remove: list[str]) -> None:
        for method, names in (("POST", add), ("DELETE", remove)):
            if names:
                reps = [self._call("GET", f"/roles/{name}")[1] for name in names]
                self._call(method, f"/users/{user_id}/role-mappings/realm", [{"id": r["id"], "name": r["name"]} for r in reps])

    def require(self, user_id: str, actions: list[str]) -> None:
        user = self._user(user_id)
        user["requiredActions"] = sorted({*(user.get("requiredActions") or []), *actions})
        self._put_user(user)

    def email_actions(self, user_id: str, actions: list[str]) -> None:
        self._call("PUT", f"/users/{user_id}/execute-actions-email", list(actions), query={"lifespan": EMAIL_LINK_SECONDS})

    def remove_authenticator(self, user_id: str) -> int:
        _, credentials = self._call("GET", f"/users/{user_id}/credentials")
        otp = [c for c in credentials or [] if c.get("type") == "otp"]
        for credential in otp:
            self._call("DELETE", f"/users/{user_id}/credentials/{credential['id']}")
        return len(otp)

    def console_link(self, user_id: str, tab: str = "credentials") -> str:
        return f"{self._public}/admin/master/console/#/{self._realm}/users/{user_id}/{tab}"


class _Unavailable:
    """The console's people page without Keycloak: every change refused with the reason, the page says what to set up."""

    def __init__(self, problem: str):
        self.problem = problem

    def __getattr__(self, name: str) -> Any:
        def refuse(*_args: Any, **_kwargs: Any) -> Any:
            raise DirectoryError(self.problem or "Keycloak is not set up for the console")
        return refuse


def directory_for(settings: Settings, fields: dict[str, str] | None = None) -> KeycloakDirectory:
    """The directory as the service account: the given key fields (a key test), else the active `keycloak` key."""
    base, realm, public = _realm_urls(settings)
    if fields is None:
        fields = ps.KeyStore(settings.read_root, settings.master_key).active("keycloak")
        if fields is None:
            raise DirectoryError(f"no active Keycloak service-account key: add the client secret of `{SERVICE_CLIENT}` "
                                 "under Keys (provider: Keycloak service account) and make it active")
    return KeycloakDirectory(base, realm, public, fields.get("client_id") or SERVICE_CLIENT, fields["client_secret"])


def test_key(settings: Settings, fields: dict[str, str]) -> tuple[bool, str]:
    """A key test for the Keys page: a token for the service account, then one read of the realm's people."""
    try:
        directory_for(settings, fields).check()
    except (DirectoryError, KeyError, ps.SettingsError) as exc:
        return False, str(exc)
    return True, "Keycloak answers: the service account can read the realm's people"


def get_directory(settings: SettingsDep) -> Directory:
    try:
        return directory_for(settings)
    except (DirectoryError, ps.SettingsError) as exc:
        return _Unavailable(str(exc))


DirectoryDep = Annotated[Directory, Depends(get_directory)]

TENANT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")
