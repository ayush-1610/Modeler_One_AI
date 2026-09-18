"""Auth contract tests (T-06): token, project membership and signature step-up.

The JWKS verifier is overridden with a fake that returns claims, so the authorization rules are checked
without a live Keycloak. Acceptance: no token -> 401; wrong project -> 403; signature without loa2 -> 403
STEP_UP_REQUIRED; stale auth_time -> 403.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from modeler_api.auth import AuthError, Principal, get_verifier, principal_from_claims
from modeler_api.main import app

SHA = "a" * 64
SIG_URL = "/api/v1/projects/proj-1/signatures"
BODY = {"meaning": "Approved", "record_type": "map", "record_id": "map-1", "record_sha256": SHA}


class FakeVerifier:
    def __init__(self, claims: dict | None):
        self.claims = claims

    def verify(self, token: str) -> dict:
        if self.claims is None:
            raise AuthError("token rejected")
        return self.claims


def claims(*, tenant="t1", roles=("modeler-reviewer",), projects=("proj-1",), acr="loa2", auth_time=None) -> dict:
    return {
        "sub": "u1", "name": "Dr Lead", "tenant_id": tenant, "realm_access": {"roles": list(roles)},
        "projects": list(projects), "acr": acr, "auth_time": int(time.time()) if auth_time is None else auth_time,
    }


def client_with(claims_dict: dict | None) -> TestClient:
    app.dependency_overrides[get_verifier] = lambda: FakeVerifier(claims_dict)
    return TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def _auth(token="tok"):
    return {"Authorization": f"Bearer {token}"}


# --- principal mapping ---------------------------------------------------------------------------


def test_principal_from_claims():
    p = principal_from_claims(claims(roles=("a", "b"), projects=("p1", "p2")))
    assert isinstance(p, Principal)
    assert p.tenant_id == "t1" and p.roles == {"a", "b"} and p.projects == {"p1", "p2"}
    assert p.acr == "loa2"


def test_principal_requires_tenant():
    with pytest.raises(AuthError, match="no tenant"):
        principal_from_claims({"sub": "u1"})


# --- 401 / invalid token -------------------------------------------------------------------------


def test_no_token_is_401():
    r = client_with(claims()).post(SIG_URL, json=BODY)  # no Authorization header
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == "Bearer"


def test_invalid_token_is_401():
    r = client_with(None).post(SIG_URL, json=BODY, headers=_auth())  # verifier rejects
    assert r.status_code == 401


def test_unconfigured_verifier_is_503():
    app.dependency_overrides.clear()  # no override -> default get_verifier raises 503
    r = TestClient(app).post(SIG_URL, json=BODY, headers=_auth())
    assert r.status_code == 503


# --- 403 project membership ----------------------------------------------------------------------


def test_wrong_project_is_403():
    r = client_with(claims(projects=("other",))).post(SIG_URL, json=BODY, headers=_auth())
    assert r.status_code == 403
    assert "not a member" in r.json()["detail"]


# --- 403 step-up ---------------------------------------------------------------------------------


def test_signature_without_loa2_is_step_up_required():
    r = client_with(claims(acr="loa1")).post(SIG_URL, json=BODY, headers=_auth())
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "STEP_UP_REQUIRED"


def test_signature_with_stale_auth_time_is_403():
    r = client_with(claims(acr="loa2", auth_time=int(time.time()) - 400)).post(SIG_URL, json=BODY, headers=_auth())
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "STEP_UP_STALE"


# --- happy path ----------------------------------------------------------------------------------


@pytest.mark.req("T-06", "F-403")
def test_valid_step_up_signature_is_created():
    r = client_with(claims()).post(SIG_URL, json=BODY, headers=_auth())
    assert r.status_code == 201
    body = r.json()
    assert body["record_sha256"] == SHA
    assert body["auth_method"] == "oidc:loa2"
    assert body["manifestation"].startswith("Dr Lead | Approved")
    assert body["signed_by"] == "u1"
