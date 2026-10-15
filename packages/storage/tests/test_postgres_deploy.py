"""The server's PostgreSQL (deploy/server/postgres.sh, T-05): its roles keep the Part 11 records append-only.

The script is run as the server runs it, as an ordinary account in a scratch home, against the PostgreSQL 16 binaries
of this machine (GitHub's Ubuntu runners have them; the server installs them from conda-forge). It is skipped where
there are none, and as root, which PostgreSQL refuses to run as.
- install creates the cluster, the roles and the databases, and applies the migrations once, each with its sha256;
- the API's login (`modeler`) may insert into the append-only tables but never change or remove a row, and cannot
  switch their triggers off or drop them; it cannot touch the migration record;
- a migration changed after it was applied stops `migrate`;
- a backup restores completely into scratch databases (`restore-check`).
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.req("T-05")

ROOT = Path(__file__).resolve().parents[3]
CANDIDATES = [Path("/usr/lib/postgresql/16/bin")]


def _pg_bin() -> Path | None:
    found = shutil.which("pg_config")
    if found:
        out = subprocess.run([found, "--bindir"], capture_output=True, text=True, check=False).stdout.strip()
        CANDIDATES.insert(0, Path(out))
    return next((p for p in CANDIDATES if (p / "initdb").exists() and (p / "postgres").exists()), None)


PG_BIN = _pg_bin()
skip = pytest.mark.skipif(PG_BIN is None or os.geteuid() == 0,
                          reason="needs PostgreSQL 16 binaries and an ordinary account (initdb refuses root)")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    home = tmp_path_factory.mktemp("pghome")
    repo = home / "repo"
    shutil.copytree(ROOT / "deploy" / "server", repo / "deploy" / "server")
    shutil.copytree(ROOT / "services" / "api" / "migrations", repo / "services" / "api" / "migrations")
    (repo / "services" / "engine-worker" / "golden").mkdir(parents=True)
    shutil.copy(ROOT / "services" / "engine-worker" / "golden" / "catalog.json", repo / "services" / "engine-worker" / "golden")
    env = {"HOME": str(home), "PATH": os.environ["PATH"], "MODELER_REPO": str(repo), "MODELER_POSTGRES_BIN": str(PG_BIN),
           "MODELER_POSTGRES_PORT": str(_free_port()), "MODELER_DATA": str(home / "data"), "MODELER_LOGS": str(home / "logs"),
           "MODELER_BACKUP_DIR": str(home / "backups"), "MODELER_SECRETS_FILE": str(home / "none")}

    def script(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(repo / "deploy" / "server" / "postgres.sh"), *args], env=env,
                              capture_output=True, text=True, timeout=300, check=False)

    def psql(user: str, db: str, statement: str) -> subprocess.CompletedProcess:
        password = (home / "modeler-postgres" / "secrets" / f"{user}.pass").read_text()
        return subprocess.run([str(PG_BIN / "psql"), "-X", "-At", "-h", "127.0.0.1", "-p", env["MODELER_POSTGRES_PORT"],
                               "-U", user, "-d", db, "-c", statement],
                              env={**env, "PGPASSWORD": password}, capture_output=True, text=True, timeout=60,
                              check=False)

    installed = script("install")
    assert installed.returncode == 0, installed.stderr
    yield {"home": home, "repo": repo, "script": script, "psql": psql, "install": installed}
    script("stop")


@skip
def test_install_applies_each_migration_once_and_keeps_secrets_private(server):
    applied = server["psql"]("postgres", "modeler", "SELECT name FROM schema_migrations ORDER BY 1").stdout.split()
    assert applied == sorted(p.name for p in (server["repo"] / "services" / "api" / "migrations").glob("*.sql"))
    again = server["script"]("install")
    assert again.returncode == 0 and "applied" not in again.stdout
    secrets = server["home"] / "modeler-postgres" / "secrets"
    assert {p.name: oct(p.stat().st_mode & 0o777) for p in secrets.iterdir()} == {
        "postgres.pass": "0o600", "keycloak.pass": "0o600", "modeler.pass": "0o600"}
    assert server["psql"]("postgres", "postgres", "SHOW listen_addresses").stdout.strip() == "127.0.0.1"


@skip
def test_the_api_login_cannot_change_or_remove_part11_records(server):
    # as the API does, the session names its tenant first (row-level security on app.tenant_id)
    tenant = "SET app.tenant_id = '00000000-0000-0000-0000-000000000001'; "
    app = lambda sql: server["psql"]("modeler", "modeler", tenant + sql)
    for statement in ("UPDATE audit_events SET actor = 'x'", "DELETE FROM audit_events", "TRUNCATE audit_events",
                      "UPDATE signatures SET meaning = 'x'", "DELETE FROM signatures"):
        assert "permission denied" in app(statement).stderr, statement
    for statement in ("ALTER TABLE audit_events DISABLE TRIGGER audit_events_append_only", "DROP TABLE signatures"):
        assert "must be owner" in app(statement).stderr, statement
    assert "permission denied" in app("DELETE FROM schema_migrations").stderr
    assert app("SELECT count(*) FROM audit_events").returncode == 0  # it can read and (with a tenant) insert


@skip
def test_a_changed_migration_stops_migrate(server):
    migration = max((server["repo"] / "services" / "api" / "migrations").glob("*.sql"))
    original = migration.read_text()
    migration.write_text(original + "\n-- edited after it was applied\n")
    try:
        result = server["script"]("migrate")
        assert result.returncode != 0 and f"{migration.name} changed after it was applied" in result.stderr
    finally:
        migration.write_text(original)


@skip
def test_a_backup_restores_completely(server):
    backup = server["script"]("backup")
    assert backup.returncode == 0, backup.stderr
    dumps = list((server["home"] / "backups").glob("*/*.dump"))
    assert sorted(p.name for p in dumps) == ["keycloak.dump", "modeler.dump"]
    assert all(oct(p.stat().st_mode & 0o777) == "0o600" for p in dumps)
    check = server["script"]("restore-check")
    assert check.returncode == 0 and "restores completely" in check.stdout, check.stderr
