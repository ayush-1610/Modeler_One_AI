"""Part 11 records in PostgreSQL (production readiness P2; docs/plans/2026-10-15-part11-records-postgres.md).

Against a real PostgreSQL 16 set up by deploy/server/postgres.sh, used through the API's own login (`modeler`), as in
production. Skipped where there is no PostgreSQL 16 or under root (initdb refuses it); GitHub's runners have it.
- every audit event reaches the database with the file chain's own hashes, and `verify` finds nothing wrong;
- the pilot's history (events written before the switch) is copied first, in order;
- when the database refuses, the file is not written and the action fails;
- a file line rewritten after the fact is reported by `verify`; a file chain behind the database stops the append;
- a signature taken through the API is a row, once.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from modeler_project import FileProjectStore
from modeler_storage.part11 import Part11Error, Part11Store, read_file_chain

pytestmark = pytest.mark.req("T-05", "T-06")

ROOT = Path(__file__).resolve().parents[3]


def _pg_bin() -> Path | None:
    candidates = [Path("/usr/lib/postgresql/16/bin")]
    if found := shutil.which("pg_config"):
        candidates.insert(0, Path(subprocess.run([found, "--bindir"], capture_output=True, text=True, check=False).stdout.strip()))
    return next((p for p in candidates if (p / "initdb").exists()), None)


PG_BIN = _pg_bin()
pytestmark = [pytestmark, pytest.mark.skipif(PG_BIN is None or os.geteuid() == 0,
                                             reason="needs PostgreSQL 16 binaries and an ordinary account")]


@pytest.fixture(scope="module")
def database_url(tmp_path_factory):
    home = tmp_path_factory.mktemp("pg")
    repo = home / "repo"
    shutil.copytree(ROOT / "deploy" / "server", repo / "deploy" / "server")
    shutil.copytree(ROOT / "services" / "api" / "migrations", repo / "services" / "api" / "migrations")
    (repo / "services" / "engine-worker" / "golden").mkdir(parents=True)
    shutil.copy(ROOT / "services" / "engine-worker" / "golden" / "catalog.json", repo / "services" / "engine-worker" / "golden")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {"HOME": str(home), "PATH": os.environ["PATH"], "MODELER_REPO": str(repo), "MODELER_POSTGRES_BIN": str(PG_BIN),
           "MODELER_POSTGRES_PORT": str(port), "MODELER_DATA": str(home / "data"), "MODELER_LOGS": str(home / "logs"),
           "MODELER_SECRETS_FILE": str(home / "none")}
    script = repo / "deploy" / "server" / "postgres.sh"
    installed = subprocess.run(["bash", str(script), "install"], env=env, capture_output=True, text=True, timeout=300, check=False)
    assert installed.returncode == 0, installed.stderr
    password = (home / "modeler-postgres" / "secrets" / "modeler.pass").read_text()
    yield f"postgresql+asyncpg://modeler:{password}@127.0.0.1:{port}/modeler"
    subprocess.run(["bash", str(script), "stop"], env=env, capture_output=True, timeout=120, check=False)


def _append(store: FileProjectStore, tenant: str, n: int) -> None:
    for i in range(n):
        store.audit(tenant).append(actor="u1", action="test.event", resource_type="project", resource_id=f"p-{i}",
                                   after={"value": i, "when": datetime(2026, 10, 15, tzinfo=UTC)}, reason="a test")


def test_audit_events_reach_the_database_with_the_file_chains_hashes(database_url, tmp_path):
    db = Part11Store(database_url)
    store = FileProjectStore(tmp_path, audit_mirror=db.mirror_audit)
    _append(store, "acme", 3)
    file_lines = read_file_chain(tmp_path / "acme" / "audit.jsonl")
    assert [r["row_hash"] for r in db.audit_rows("acme")] == [line["row_hash"] for line in file_lines]
    assert db.verify("acme", file_lines) == []
    assert store.audit("acme").verify() is None


def test_the_pilots_history_is_copied_first_in_order(database_url, tmp_path):
    _append(FileProjectStore(tmp_path), "pilot-co", 2)  # written before the switch: files only
    db = Part11Store(database_url)
    _append(FileProjectStore(tmp_path, audit_mirror=db.mirror_audit), "pilot-co", 1)
    assert [r["event"]["seq"] for r in db.audit_rows("pilot-co")] == [1, 2, 3]
    assert db.verify("pilot-co", read_file_chain(tmp_path / "pilot-co" / "audit.jsonl")) == []


def test_a_refusing_database_leaves_the_file_unwritten(database_url, tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        closed = s.getsockname()[1]
    nowhere = Part11Store(database_url.rsplit("@", 1)[0] + f"@127.0.0.1:{closed}/modeler")
    store = FileProjectStore(tmp_path, audit_mirror=nowhere.mirror_audit)
    with pytest.raises(OSError):
        _append(store, "down-co", 1)
    assert read_file_chain(tmp_path / "down-co" / "audit.jsonl") == []


def test_a_rewritten_file_line_is_reported_and_a_shortened_chain_stops(database_url, tmp_path):
    db = Part11Store(database_url)
    store = FileProjectStore(tmp_path, audit_mirror=db.mirror_audit)
    _append(store, "tamper-co", 3)
    path = tmp_path / "tamper-co" / "audit.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    second = json.loads(lines[1])
    second["event"]["actor"] = "someone-else"  # a rewrite after the fact (its own hash left as it was)
    path.write_text("\n".join([lines[0], json.dumps(second), lines[2]]) + "\n", encoding="utf-8")
    assert any("event 2 differs" in p for p in db.verify("tamper-co", read_file_chain(path)))
    path.write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")  # the last event removed from the file
    with pytest.raises(Part11Error, match="already holds"):
        _append(store, "tamper-co", 1)


def test_a_signature_through_the_api_is_a_row_once(database_url, tmp_path, api_settings):
    from modeler_api.main import app

    api_settings(read_root=str(tmp_path), dev_auth=True, part11_store="postgres", database_url=database_url)
    body = {"meaning": "Approved", "record_type": "map", "record_id": "p1/plan-v1", "record_sha256": "c" * 64}
    with TestClient(app) as client:
        answer = client.post("/api/v1/projects/p1/signatures", json=body, headers={"Authorization": "Bearer dev"})
    assert answer.status_code == 201, answer.text
    db = Part11Store(database_url)

    async def rows():
        import asyncpg

        from modeler_storage.part11 import asyncpg_dsn

        conn = await asyncpg.connect(asyncpg_dsn(database_url))
        try:
            async with conn.transaction():
                await conn.execute("SELECT set_config('app.tenant_id', (SELECT id::text FROM tenants WHERE slug = 'dev'), true)")
                return await conn.fetch("SELECT id::text, record_id, auth_method, printed_name FROM signatures")
        finally:
            await conn.close()

    found = db._loop.run(rows())
    assert [(r["id"], r["record_id"]) for r in found] == [(answer.json()["signature_id"], "p1/plan-v1")]
    assert found[0]["auth_method"].startswith("oidc:") and found[0]["printed_name"] == "Dev User"
    with pytest.raises(Exception, match="duplicate key"):
        db.record_signature("dev", signature_id=answer.json()["signature_id"], signer_subject="dev-user",
                            printed_name="Dev User", meaning="Approved", signed_at=datetime.now(UTC), record_type="map",
                            record_id="p1/plan-v1", record_sha256="c" * 64, auth_method="oidc:loa2")


def test_the_verify_command_checks_every_tenant_with_the_deployments_settings(database_url, tmp_path, api_settings, capsys):
    from modeler_api.part11 import main

    db = Part11Store(database_url)
    _append(FileProjectStore(tmp_path, audit_mirror=db.mirror_audit), "cli-co", 2)
    api_settings(read_root=str(tmp_path), part11_store="postgres", database_url=database_url)
    assert main(["verify"]) == 0
    assert "1 tenant(s), OK" in capsys.readouterr().out
