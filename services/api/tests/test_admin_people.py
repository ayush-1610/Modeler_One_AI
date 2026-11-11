"""The admin console's F (docs/plans/2026-11-10-admin-console.md): companies and their people, kept in Keycloak and
changed from the console as the realm's service account. Only `modeler-admin`, a fresh step-up and a reason for every
change; each an audit event on the company's own chain. No password ever passes through the platform; nobody is
deleted; `modeler-admin` is never given from the console; the owner cannot lock themselves out."""

from __future__ import annotations

import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient

from modeler_api import keycloak_admin as kc
from modeler_api import platform_settings as ps
from modeler_api.auth import get_verifier
from modeler_api.main import app

pytestmark = pytest.mark.req("T-05", "T-06")

PEOPLE = {"owner": ("platform", ["modeler-admin"]), "ana": ("acme", ["modeler-viewer", "modeler-curator"])}


class _Verifier:
    def verify(self, token: str) -> dict:
        who = token.removesuffix("-stale")
        tenant, roles = PEOPLE[who]
        fresh = not token.endswith("-stale")
        return {"sub": who, "name": who.title(), "tenant_id": tenant, "realm_access": {"roles": roles}, "projects": [],
                "acr": "loa2" if fresh else "loa1", "auth_time": int(time.time()) if fresh else None}


class FakeDirectory:
    """Keycloak's people as the routes see them, in memory."""

    def __init__(self, smtp: bool = False):
        self.problem: str | None = None
        self.mail = smtp
        self.users: dict[str, dict[str, Any]] = {}
        self.emails: list[tuple[str, list[str]]] = []

    def add_existing(self, user_id: str, username: str, tenant_id: str, roles: list[str], *, enabled: bool = True,
                     authenticator: bool = True) -> None:
        self.users[user_id] = {"id": user_id, "username": username, "email": f"{username}@example.test",
                               "first_name": username.title(), "last_name": "Person", "tenant_id": tenant_id,
                               "enabled": enabled, "authenticator": authenticator, "required_actions": [],
                               "created_ms": 1_700_000_000_000, "roles": list(roles)}

    def smtp(self) -> bool:
        return self.mail

    def people(self) -> list[dict[str, Any]]:
        return [dict(u, roles=list(u["roles"])) for u in self.users.values()]

    def create(self, *, username, email, first_name, last_name, tenant_id, roles) -> str:
        if any(u["username"] == username for u in self.users.values()):
            raise kc.DirectoryError("Keycloak already has that person (User exists with same username)")
        user_id = str(uuid.uuid4())
        self.users[user_id] = {"id": user_id, "username": username, "email": email, "first_name": first_name,
                               "last_name": last_name, "tenant_id": tenant_id, "enabled": True, "authenticator": False,
                               "required_actions": list(kc.FIRST_SIGN_IN), "created_ms": 1_700_000_000_000,
                               "roles": list(roles)}
        return user_id

    def set_enabled(self, user_id, enabled) -> None:
        self.users[user_id]["enabled"] = enabled

    def set_tenant(self, user_id, tenant_id) -> None:
        self.users[user_id]["tenant_id"] = tenant_id

    def set_roles(self, user_id, *, add, remove) -> None:
        roles = self.users[user_id]["roles"]
        self.users[user_id]["roles"] = [r for r in roles if r not in remove] + [r for r in add if r not in roles]

    def require(self, user_id, actions) -> None:
        self.users[user_id]["required_actions"] = sorted({*self.users[user_id]["required_actions"], *actions})

    def email_actions(self, user_id, actions) -> None:
        self.emails.append((user_id, list(actions)))

    def remove_authenticator(self, user_id) -> int:
        had = self.users[user_id]["authenticator"]
        self.users[user_id]["authenticator"] = False
        return int(had)

    def console_link(self, user_id, tab="credentials") -> str:
        return f"https://kc.example.test:8443/admin/master/console/#/modeler/users/{user_id}/{tab}"


@pytest.fixture
def directory() -> FakeDirectory:
    return FakeDirectory()


@pytest.fixture
def client(tmp_path, api_settings, directory):
    api_settings(read_root=str(tmp_path))
    app.dependency_overrides[get_verifier] = _Verifier
    app.dependency_overrides[kc.get_directory] = lambda: directory
    yield TestClient(app)
    app.dependency_overrides.clear()


def _as(who: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {who}"}


def _events(tmp_path, tenant: str) -> list[dict]:
    path = tmp_path / tenant / "audit.jsonl"
    return [json.loads(line)["event"] for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def _company(client: TestClient, tenant_id: str = "acme", name: str = "Acme Pharma") -> object:
    return client.post("/api/v1/admin/companies", json={"tenant_id": tenant_id, "name": name, "reason": "new client"},
                       headers=_as("owner"))


NEW = {"username": "rita", "email": "rita@acme.test", "first_name": "Rita", "last_name": "Rao", "tenant_id": "acme",
       "roles": ["modeler-viewer", "modeler-reviewer"], "reason": "reviewer for the Renal project"}


def test_a_company_is_added_with_its_name_and_its_own_audit_chain(client, tmp_path):
    page = _company(client)
    assert page.status_code == 200, page.text
    assert (page.json()["data"]["tenant_id"], page.json()["data"]["name"]) == ("acme", "Acme Pharma")
    (event,) = [e for e in _events(tmp_path, "acme") if e["action"] == "admin.company.add"]
    assert event["after"] == {"name": "Acme Pharma"} and event["actor"] == "owner"
    row = next(c for c in client.get("/api/v1/admin/overview", headers=_as("owner")).json()["data"]["companies"]
               if c["tenant_id"] == "acme")
    assert (row["name"], row["disabled"]) == ("Acme Pharma", False)
    for wrong, why in (("acme", "exists already"), ("Acme Pharma", "lowercase letters")):
        assert why in _company(client, wrong).json()["detail"]


def test_a_person_is_added_and_sets_their_own_password_by_email_or_through_keycloaks_console(client, tmp_path, directory):
    _company(client)
    page = client.post("/api/v1/admin/people", json=NEW, headers=_as("owner")).json()["data"]
    (rita,) = [p for p in page["people"] if p["username"] == "rita"]
    assert (rita["tenant_id"], rita["roles"], rita["required_actions"]) == (
        "acme", ["modeler-viewer", "modeler-reviewer"], ["UPDATE_PASSWORD", "CONFIGURE_TOTP"])
    # no mail server: the owner sets a temporary password in Keycloak's own console, never here
    assert "no mail server" in page["notice"] and page["notice_link"].endswith(f"/users/{rita['id']}/credentials")
    assert "password" not in json.dumps(NEW) and directory.emails == []
    (event,) = [e for e in _events(tmp_path, "acme") if e["action"] == "admin.person.add"]
    assert event["after"]["roles"] == ["modeler-viewer", "modeler-reviewer"] and event["reason"] == NEW["reason"]

    directory.mail = True                                           # with a mail server, Keycloak emails the link
    page = client.post("/api/v1/admin/people", json=NEW | {"username": "sam", "email": "sam@acme.test"},
                       headers=_as("owner")).json()["data"]
    assert "emailed" in page["notice"] and page["notice_link"] is None
    assert directory.emails[-1][1] == ["UPDATE_PASSWORD", "CONFIGURE_TOTP"]


def test_adding_a_person_is_refused_without_a_step_up_a_company_or_with_the_admin_role(client):
    _company(client)
    stale = client.post("/api/v1/admin/people", json=NEW, headers=_as("owner-stale"))
    assert stale.status_code == 403 and stale.json()["detail"]["code"] == "STEP_UP_REQUIRED"
    assert client.post("/api/v1/admin/people", json=NEW, headers=_as("ana")).status_code == 403
    for wrong, why in (({"tenant_id": "nope"}, "no company"), ({"roles": ["modeler-admin"]}, "stays with the platform's owner"),
                       ({"roles": []}, "at least one role")):
        refused = client.post("/api/v1/admin/people", json=NEW | wrong, headers=_as("owner"))
        assert refused.status_code == 409 and why in refused.json()["detail"], (wrong, refused.text)
    client.post("/api/v1/admin/people", json=NEW, headers=_as("owner"))
    again = client.post("/api/v1/admin/people", json=NEW, headers=_as("owner"))
    assert again.status_code == 409 and "already has that person" in again.json()["detail"]


def test_a_person_is_disabled_given_roles_and_moved_and_the_owner_cannot_lock_themselves_out(client, tmp_path, directory):
    _company(client)
    _company(client, "beta", "Beta Labs")
    directory.add_existing("u-ana", "ana", "acme", ["modeler-viewer", "modeler-curator"])
    directory.add_existing("owner", "owner", "platform", ["modeler-admin"])
    change = client.post("/api/v1/admin/people/u-ana:change", headers=_as("owner"), json={
        "add_roles": ["modeler-qa"], "remove_roles": ["modeler-curator"], "enabled": False, "reason": "QA only now"})
    assert change.status_code == 200, change.text
    assert (directory.users["u-ana"]["roles"], directory.users["u-ana"]["enabled"]) == (["modeler-viewer", "modeler-qa"], False)
    (event,) = [e for e in _events(tmp_path, "acme") if e["action"] == "admin.person.change"]
    assert event["before"]["roles"] == ["modeler-viewer", "modeler-curator"] and event["after"]["enabled"] is False
    moved = client.post("/api/v1/admin/people/u-ana:change", json={"tenant_id": "beta", "reason": "joined Beta"},
                        headers=_as("owner"))
    assert moved.status_code == 200 and directory.users["u-ana"]["tenant_id"] == "beta"
    assert [e["after"]["tenant_id"] for e in _events(tmp_path, "beta") if e["action"] == "admin.person.change"] == ["beta"]
    for body, why in (({"enabled": False}, "cannot disable yourself"), ({"tenant_id": "acme"}, "cannot disable yourself"),
                      ({"add_roles": ["modeler-admin"]}, "stays with the platform's owner")):
        refused = client.post("/api/v1/admin/people/owner:change", json=body | {"reason": "x"}, headers=_as("owner"))
        assert refused.status_code == 409 and why in refused.json()["detail"], (body, refused.text)
    assert client.post("/api/v1/admin/people/u-ana:change", json={"reason": "x"}, headers=_as("owner")).status_code == 409
    assert client.post("/api/v1/admin/people/nobody:change", json={"enabled": True, "reason": "x"},
                       headers=_as("owner")).status_code == 404


def test_a_lost_authenticator_is_removed_and_a_forgotten_password_set_again_outside_the_platform(client, tmp_path, directory):
    _company(client)
    directory.add_existing("u-ana", "ana", "acme", ["modeler-viewer"])
    page = client.post("/api/v1/admin/people/u-ana:reset", json={"authenticator": True, "password": True,
                                                                "reason": "lost her phone"}, headers=_as("owner")).json()["data"]
    assert directory.users["u-ana"]["authenticator"] is False and "CONFIGURE_TOTP" in directory.users["u-ana"]["required_actions"]
    assert "authenticator is removed" in page["notice"] and page["notice_link"].endswith("/users/u-ana/credentials")
    (event,) = [e for e in _events(tmp_path, "acme") if e["action"] == "admin.person.reset"]
    assert event["after"] == {"username": "ana", "authenticators_removed": 1, "password": "link given to set it in Keycloak"}
    assert client.post("/api/v1/admin/people/u-ana:reset", json={"reason": "x"}, headers=_as("owner")).status_code == 409


def test_a_company_is_disabled_with_its_people_and_enabled_again_with_the_same_people(client, tmp_path, directory):
    _company(client)
    directory.add_existing("u-ana", "ana", "acme", ["modeler-viewer"])
    directory.add_existing("u-old", "old", "acme", ["modeler-viewer"], enabled=False)     # left before: stays disabled
    directory.add_existing("u-ben", "ben", "beta", ["modeler-viewer"])
    page = client.post("/api/v1/admin/companies/acme:disable", json={"reason": "contract ended"}, headers=_as("owner"))
    assert page.status_code == 200 and page.json()["data"]["disabled_reason"] == "contract ended"
    assert [u["enabled"] for u in (directory.users["u-ana"], directory.users["u-old"], directory.users["u-ben"])] == [False, False, True]
    assert ps.CompanyRegistry(str(tmp_path)).get("acme")["disabled"]["people"] == ["u-ana"]
    refused = client.post("/api/v1/admin/people", json=NEW, headers=_as("owner"))
    assert refused.status_code == 409 and "is disabled" in refused.json()["detail"]
    client.post("/api/v1/admin/companies/acme:enable", json={"reason": "renewed"}, headers=_as("owner"))
    assert [directory.users[u]["enabled"] for u in ("u-ana", "u-old")] == [True, False]
    actions = [e["action"] for e in _events(tmp_path, "acme")]
    assert actions.count("admin.company.disable") == 1 and actions.count("admin.company.enable") == 1
    own = client.post("/api/v1/admin/companies/platform:disable", json={"reason": "x"}, headers=_as("owner"))
    assert own.status_code == 409 and "lock you out" in own.json()["detail"]


def test_without_keycloak_set_up_the_page_says_what_to_do(tmp_path, api_settings):
    app.dependency_overrides[get_verifier] = _Verifier
    try:
        api_settings(read_root=str(tmp_path))
        page = TestClient(app).get("/api/v1/admin/people", headers=_as("owner")).json()["data"]
        assert page["ready"] is False and "does not sign in through Keycloak" in page["problem"]
        api_settings(read_root=str(tmp_path), oidc_jwks_url="http://127.0.0.1:9/realms/modeler/protocol/openid-connect/certs",
                     oidc_issuer="https://kc.example.test:8443/realms/modeler")
        page = TestClient(app).get("/api/v1/admin/people", headers=_as("owner")).json()["data"]
        assert page["ready"] is False and "no active Keycloak service-account key" in page["problem"]
        refused = TestClient(app).post("/api/v1/admin/people", json=NEW, headers=_as("owner"))
        assert refused.status_code == 409
    finally:
        app.dependency_overrides.clear()


# --- the real client against a stand-in for Keycloak's admin API ---------------------------------------------------


class _Keycloak(BaseHTTPRequestHandler):
    """Just enough of Keycloak's admin REST API to check what `KeycloakDirectory` sends."""

    users: ClassVar[dict[str, dict[str, Any]]] = {}
    calls: ClassVar[list[tuple[str, str, Any]]] = []

    def log_message(self, *_args):
        pass

    def _answer(self, status: int, body: Any = None, headers: dict[str, str] | None = None) -> None:
        raw = json.dumps(body).encode() if body is not None else b""
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> Any:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        return json.loads(raw) if raw and self.headers.get("Content-Type") == "application/json" else raw.decode()

    def _route(self, method: str) -> None:
        body = self._body()
        path = self.path.split("?")[0]
        type(self).calls.append((method, path, body))
        prefix = "/admin/realms/modeler"
        if path == "/realms/modeler/protocol/openid-connect/token":
            ok = "client_secret=s3cret" in body
            return self._answer(200 if ok else 401, {"access_token": "t"} if ok else {"error": "unauthorized_client"})
        if self.headers.get("Authorization") != "Bearer t":
            return self._answer(401, {"error": "no token"})
        if path == prefix:
            return self._answer(200, {"realm": "modeler", "smtpServer": {}})
        if path == f"{prefix}/users" and method == "POST":
            user_id = "new-1"
            type(self).users[user_id] = {"id": user_id, **body}
            return self._answer(201, None, {"Location": f"http://x{prefix}/users/{user_id}"})
        if path == f"{prefix}/users":
            return self._answer(200, list(type(self).users.values()))
        if path.startswith(f"{prefix}/roles/") and path.endswith("/users"):
            return self._answer(200, [])
        if path.startswith(f"{prefix}/roles/"):
            name = path.rsplit("/", 1)[-1]
            return self._answer(200, {"id": f"id-{name}", "name": name})
        if path.startswith(f"{prefix}/users/") and path.endswith("/role-mappings/realm"):
            return self._answer(204)
        if path.startswith(f"{prefix}/users/"):
            user_id = path.split("/")[5]
            if method == "PUT":
                type(self).users[user_id] = body
                return self._answer(204)
            return self._answer(200, type(self).users[user_id])
        return self._answer(404, {"error": "not here"})

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def do_PUT(self):
        self._route("PUT")

    def do_DELETE(self):
        self._route("DELETE")


@pytest.fixture
def keycloak():
    _Keycloak.users, _Keycloak.calls = {}, []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Keycloak)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_the_client_creates_a_person_as_the_service_account_and_keeps_their_other_attributes(keycloak):
    directory = kc.KeycloakDirectory(keycloak, "modeler", "https://kc.example.test:8443", "modeler-admin-api", "s3cret")
    user_id = directory.create(username="rita", email="rita@acme.test", first_name="Rita", last_name="Rao",
                               tenant_id="acme", roles=["modeler-viewer"])
    assert user_id == "new-1"
    created = _Keycloak.users["new-1"]
    assert created["attributes"] == {"tenant_id": ["acme"]} and created["requiredActions"] == ["UPDATE_PASSWORD", "CONFIGURE_TOTP"]
    assert "credentials" not in created                                   # no password is ever sent
    assert ("POST", "/admin/realms/modeler/users/new-1/role-mappings/realm",
            [{"id": "id-modeler-viewer", "name": "modeler-viewer"}]) in _Keycloak.calls
    _Keycloak.users["new-1"]["attributes"]["projects"] = ["p-1"]
    directory.set_tenant("new-1", "beta")                                 # the whole representation goes back
    assert _Keycloak.users["new-1"]["attributes"] == {"tenant_id": ["beta"], "projects": ["p-1"]}
    assert directory.smtp() is False
    assert directory.console_link("new-1") == "https://kc.example.test:8443/admin/master/console/#/modeler/users/new-1/credentials"
    wrong = kc.KeycloakDirectory(keycloak, "modeler", "https://x", "modeler-admin-api", "nope")
    with pytest.raises(kc.DirectoryError, match="refused the service account"):
        wrong.people()
