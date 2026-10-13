"""The Keycloak realm the deployment imports (T-06): what a token must carry for the API to accept it.

Each rule here was found by importing the realm into Keycloak 26.7.5 and signing in through it (2026-10-13). The file
is data Keycloak reads strictly, so a regression is silent until someone cannot sign in or sign:
- an unknown top-level key (the old ``__comment``) stops the import;
- a ``clientScopes`` list replaces Keycloak's built-in scopes, so tokens lose ``sub``, ``auth_time``, ``acr`` and roles;
- attributes the user profile does not declare (``tenant_id``, ``projects``) are dropped, so the API finds no tenant;
- without the audience mapper the API refuses every token (audience ``modeler-api``);
- the step-up (loa2) must ask for the password and the TOTP again at every signature (max age 0).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from modeler_api.auth import STEP_UP_ACR

pytestmark = pytest.mark.req("T-06")
REALM = json.loads((Path(__file__).parents[3] / "deploy" / "keycloak" / "realm-modeler.json").read_text(encoding="utf-8"))


def _client(client_id: str) -> dict:
    return next(c for c in REALM["clients"] if c["clientId"] == client_id)


def _flow(alias: str) -> dict:
    return next(f for f in REALM["authenticationFlows"] if f["alias"] == alias)


def test_the_realm_carries_only_keys_keycloak_imports_and_keeps_its_built_in_scopes():
    assert not [k for k in REALM if k.startswith("_")]
    assert "clientScopes" not in REALM
    assert "defaultClientScopes" not in _client("modeler-web")


def test_web_tokens_carry_the_tenant_the_projects_and_the_api_as_audience():
    mappers = {m["name"]: m for m in _client("modeler-web")["protocolMappers"]}
    assert mappers["tenant_id"]["config"]["claim.name"] == "tenant_id"
    assert mappers["projects"]["config"]["multivalued"] == "true"
    assert mappers["modeler-api audience"]["config"]["included.client.audience"] == "modeler-api"
    profile = json.loads(REALM["components"]["org.keycloak.userprofile.UserProfileProvider"][0]["config"]
                         ["kc.user.profile.config"][0])
    declared = {a["name"]: a for a in profile["attributes"]}
    for name in ("tenant_id", "projects"):
        assert declared[name]["permissions"]["edit"] == ["admin"]  # a person never changes their own tenant or projects


def test_the_web_client_is_public_with_pkce_and_no_password_grant():
    web = _client("modeler-web")
    assert web["publicClient"] and web["attributes"]["pkce.code.challenge.method"] == "S256"
    assert not web["directAccessGrantsEnabled"] and not web["implicitFlowEnabled"]


def test_the_signing_step_up_asks_for_the_password_and_the_totp_every_time():
    assert json.loads(REALM["attributes"]["acr.loa.map"])[STEP_UP_ACR] == 2
    assert REALM["browserFlow"] == "modeler browser"
    configs = {c["alias"]: c["config"] for c in REALM["authenticatorConfig"]}
    steps = [e.get("authenticator") for e in _flow("modeler loa2 signing")["authenticationExecutions"]]
    assert steps == ["conditional-level-of-authentication", "auth-password-form", "auth-otp-form"]
    level = _flow("modeler loa2 signing")["authenticationExecutions"][0]["authenticatorConfig"]
    assert configs[level] == {"loa-condition-level": "2", "loa-max-age": "0"}
