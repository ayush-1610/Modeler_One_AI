"""`deploy/server/keycloak.sh connect` (the owner, 2026-11-27: the admin console set up and used without Keycloak's own
console): the shell does Keycloak's steps with kcadm, and `modeler_api.keycloak_connect` keeps the new secret as the
console's active key, tested first and audited on the owner's chain, never written anywhere in clear."""

from __future__ import annotations

import base64
import json
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

from modeler_api import keycloak_admin as kc
from modeler_api import keycloak_connect
from modeler_api import platform_settings as ps
from modeler_api.config import Settings

pytestmark = pytest.mark.req("T-05", "T-06")

REPO = Path(__file__).resolve().parents[3]
MASTER = base64.b64encode(b"k" * 32).decode()
SECRET = "Zq9-new-client-secret-7781"


class _Directory:
    def people(self):
        return [{"id": "o", "tenant_id": "platform", "roles": ["modeler-admin"]},
                {"id": "a", "tenant_id": "acme", "roles": ["modeler-viewer"]}]


def _settings(tmp_path: Path) -> Settings:
    return Settings(read_root=str(tmp_path), master_key=MASTER,
                    oidc_jwks_url="http://127.0.0.1:9/realms/modeler/protocol/openid-connect/certs",
                    oidc_issuer="https://kc.example.test:8443/realms/modeler")


def _events(tmp_path: Path, tenant: str) -> list[dict]:
    path = tmp_path / tenant / "audit.jsonl"
    return [json.loads(line)["event"] for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_a_working_secret_becomes_the_consoles_active_key_and_is_audited_on_the_owners_chain(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    store = ps.KeyStore(settings.read_root, MASTER)
    old = store.add("keycloak", "by hand", {"client_id": kc.SERVICE_CLIENT, "client_secret": "old-secret-1234"}, by="owner")
    store.activate(old["id"])
    monkeypatch.setattr(kc, "test_key", lambda _s, fields: (fields["client_secret"] == SECRET, "Keycloak answers"))
    monkeypatch.setattr(kc, "directory_for", lambda _s, fields=None: _Directory())

    told = keycloak_connect.connect(settings, SECRET, by="keycloak:admin via keycloak.sh connect on adt-server")
    assert "connected" in told and "…7781" in told and f"replacing {old['id']}" in told
    assert store.active("keycloak") == {"client_id": kc.SERVICE_CLIENT, "client_secret": SECRET}
    assert {r["id"]: r["state"] for r in store.records()}[old["id"]] == "retired"
    events = [e for e in _events(tmp_path, "platform") if e["action"].startswith("admin.key.")]
    assert [e["action"] for e in events] == ["admin.key.add", "admin.key.activate"]
    assert events[0]["actor"] == "keycloak:admin via keycloak.sh connect on adt-server"
    assert events[1]["after"]["last4"] == {"client_secret": "7781"} and events[1]["after"]["retired"] == old["id"]
    assert _events(tmp_path, "acme") == []                              # the owner's chain only
    assert not [f for f in tmp_path.rglob("*") if f.is_file() and SECRET in f.read_text(encoding="utf-8", errors="ignore")]


def test_a_secret_that_does_not_work_is_not_stored(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    monkeypatch.setattr(kc, "test_key", lambda _s, _f: (False, "Keycloak refused the service account (401)"))
    with pytest.raises(keycloak_connect.ConnectError, match="not stored: Keycloak refused"):
        keycloak_connect.connect(settings, SECRET, by="x")
    assert ps.KeyStore(settings.read_root, MASTER).records() == []


# --- the shell, with stand-ins for kcadm.sh and uv ------------------------------------------------------------------

KCADM = r'''#!/usr/bin/env bash
# a stand-in for Keycloak's kcadm.sh: logs each call, answers as Keycloak would
printf '%s\n' "$*" >> "$LOG"
config="$(echo "$*" | sed 's/.*--config \([^ ]*\).*/\1/')"
[ -f "$config" ] || [ "$1" = config ] || { echo "no session: run config credentials first" >&2; exit 1; }
case "$(echo "$*" | sed 's/--config [^ ]* //')" in
  "config credentials"*) touch "$config";;
  *"get clients -r modeler -q clientId=modeler-admin-api"*) ;;
  *"create clients -r modeler -i"*) echo admin-api-id;;
  *"get clients -r modeler -q clientId=modeler-web"*) echo web-id;;
  *"get clients/web-id"*) echo '{"redirectUris": ["http://localhost:3000/*"]}';;
  *"get clients/admin-api-id/client-secret"*) echo '{"type": "secret", "value": "Zq9-new-client-secret-7781"}';;
esac
'''
UV = r'''#!/usr/bin/env bash
# a stand-in for uv: what keycloak_connect would get on stdin, and its arguments
cat > "$STDIN_COPY"; printf '%s\n' "$*" > "$ARGS_COPY"; echo "connected (stand-in)"
'''


def _executable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_connect_does_keycloaks_steps_and_pipes_the_new_secret_to_the_console_only(tmp_path):
    home, kc_root, logs = tmp_path / "home", tmp_path / "kc", tmp_path / "logs"
    kc_home = kc_root / "keycloak-26.7.5"
    _executable(kc_home / "bin" / "kcadm.sh", KCADM)
    (kc_home / "themes" / "modeler-one").mkdir(parents=True)
    _executable(kc_root / "jdk" / "bin" / "java", "#!/bin/sh\necho 'version \"21.0.1\"'\n")
    _executable(home / ".local" / "bin" / "uv", UV)
    logs.mkdir()
    (logs / "keycloak.pid").write_text(str(os.getpid()))              # a live process: Keycloak counts as running
    secrets = tmp_path / "secrets.env"
    secrets.write_text("export MODELER_OIDC_ISSUER=https://kc.example.test:8443/realms/modeler\n"
                       f"export MODELER_MASTER_KEY={MASTER}\nexport MODELER_WEB_URL=https://kc.example.test:3000\n")
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "MODELER_REPO": str(REPO), "MODELER_DATA": str(tmp_path / "data"),
           "MODELER_LOGS": str(logs), "MODELER_SECRETS_FILE": str(secrets), "MODELER_KEYCLOAK_HOME": str(kc_root),
           "MODELER_KEYCLOAK_HOST": "kc.example.test", "LOG": str(tmp_path / "kcadm.log"),
           "STDIN_COPY": str(tmp_path / "stdin"), "ARGS_COPY": str(tmp_path / "args")}
    done = subprocess.run(["bash", str(REPO / "deploy/server/keycloak.sh"), "connect"], env=env, capture_output=True,
                          text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    raw = (tmp_path / "kcadm.log").read_text().splitlines()
    assert raw[0].startswith("config credentials --config ") and "--realm master --user admin" in raw[0]
    assert all(" --config " in c for c in raw)                         # every call on this run's own session file
    calls = [re.sub(r"--config \S+ ", "", c) for c in raw]
    assert any("create clients -r modeler -i -s clientId=modeler-admin-api" in c and "serviceAccountsEnabled=true" in c
               and "directAccessGrantsEnabled=false" in c for c in calls)
    roles = next(c for c in calls if c.startswith("add-roles"))
    assert all(f"--rolename {r}" in roles for r in ("manage-users", "query-users", "view-realm", "view-users"))
    assert '-s redirectUris=["http://localhost:3000/*", "https://kc.example.test:3000/*"]' in "\n".join(calls)
    assert any("update realms/modeler" in c and "loginTheme=modeler-one" in c for c in calls)
    assert any(c.startswith("create clients/admin-api-id/client-secret") for c in calls)
    # the secret reaches the console's step on stdin only: never an argument, never left in kcadm's session file
    assert (tmp_path / "stdin").read_text() == SECRET
    assert SECRET not in "\n".join(calls) and SECRET not in (tmp_path / "args").read_text()
    assert "--by keycloak:admin via keycloak.sh connect on" in (tmp_path / "args").read_text()
    assert list(kc_root.glob("kcadm-*.config")) == []
    assert "connected (stand-in)" in done.stdout and SECRET not in done.stdout + done.stderr


def _refused(tmp_path: Path, *, installed: bool) -> subprocess.CompletedProcess:
    secrets = tmp_path / "secrets.env"
    secrets.write_text("export MODELER_OIDC_ISSUER=https://kc.example.test:8443/realms/modeler\n")
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "keycloak.pid").write_text(str(os.getpid()))
    if installed:
        _executable(tmp_path / "kc" / "keycloak-26.7.5" / "bin" / "kcadm.sh", "#!/bin/sh\nexit 1\n")
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin", "MODELER_REPO": str(REPO), "MODELER_DATA": str(tmp_path / "d"),
           "MODELER_LOGS": str(logs), "MODELER_SECRETS_FILE": str(secrets), "MODELER_KEYCLOAK_HOME": str(tmp_path / "kc")}
    return subprocess.run(["bash", str(REPO / "deploy/server/keycloak.sh"), "connect"], env=env, capture_output=True,
                          text=True, timeout=60, check=False)


def test_connect_refuses_before_asking_for_a_password_when_the_console_cannot_keep_a_key(tmp_path):
    done = _refused(tmp_path, installed=True)
    assert done.returncode != 0 and "MODELER_MASTER_KEY is not set" in done.stderr


def test_connect_run_off_the_server_says_where_to_run_it(tmp_path):
    """The owner ran it on the Mac (2026-11-27): it stops first, and says to run it on the server over ssh."""
    done = _refused(tmp_path, installed=False)
    assert done.returncode != 0 and "Keycloak is not installed on this machine" in done.stderr
    assert "ssh -t <the server> 'bash ~/Modeler_One_AI/deploy/server/keycloak.sh connect'" in done.stderr
