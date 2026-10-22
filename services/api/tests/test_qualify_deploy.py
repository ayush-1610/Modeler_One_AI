"""The server's Installation Qualification (deploy/server/qualify.py, validation pack V1, T-32).

Run on a scratch copy of the repository, as the server runs it, with the network and the commands replaced: what is
installed is checked against what the repository says, a missing piece is "not checked" (never a pass), and a changed
locked file, a branch other than main, the wrong engine or a pilot deployment fail.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.req("T-32")
ROOT = Path(__file__).resolve().parents[3]


def _qualify():
    spec = importlib.util.spec_from_file_location("qualify", ROOT / "deploy" / "server" / "qualify.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def repo(tmp_path):
    repo = tmp_path / "repo"
    manifest = json.loads((ROOT / "docs" / "architecture" / "locked-files.json").read_text(encoding="utf-8"))
    for rel in [f["path"] for f in manifest["files"]] + ["docs/architecture/locked-files.json", "uv.lock",
                                                         "apps/web/package-lock.json", "deploy/server/keycloak.sh"]:
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, repo / rel)
    shutil.copytree(ROOT / "services" / "api" / "migrations", repo / "services" / "api" / "migrations", dirs_exist_ok=True)
    return repo


def _catalog_digest(repo: Path) -> str:
    data = json.loads((repo / "services" / "engine-worker" / "golden" / "catalog.json").read_text(encoding="utf-8"))
    return "catalog:sha256:" + hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _engine_run(repo: Path):
    catalog = json.loads((repo / "services" / "engine-worker" / "golden" / "catalog.json").read_text(encoding="utf-8"))["engine"]

    def run(cmd):
        if cmd[0] == "Rscript":
            return 0, (f"ospsuite {catalog['ospsuite']} \nospsuite.parameteridentification "
                       f"{catalog['parameter_identification']} ")
        if cmd[0] == "node":
            return 0, "v22.0.0"
        return 127, f"{cmd[0]}: not found"
    return run


def _health(deployment: str, verifier: str):
    def fetch(url):
        if url.endswith("/health"):
            return 200, json.dumps({"status": "ok", "deployment": deployment, "verifier": verifier})
        return 200, "<html>"
    return fetch


def test_a_production_install_from_main_passes_what_it_has_and_says_what_it_lacks(repo, tmp_path):
    q = _qualify()
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True,
                            check=False).stdout.strip()
    (repo / ".deployed.json").write_text(json.dumps({"commit": commit, "branch": "main", "clean": True,
                                                     "deployed_at": "2026-10-22T10:00:00Z"}))
    env = {"HOME": str(tmp_path), "MODELER_IMAGE_DIGEST": _catalog_digest(repo)}
    record = q.qualify(repo, env, fetch=_health("production", "oidc"), run=_engine_run(repo))
    results = {c["id"]: c["result"] for c in record["checks"]}
    assert record["schema"] == "iq/1" and len(results) == 10
    assert results == {"IQ-01": "pass", "IQ-02": "pass", "IQ-03": "recorded", "IQ-04": "pass", "IQ-05": "pass",
                       "IQ-06": "not_checked", "IQ-07": "not_checked", "IQ-08": "pass", "IQ-09": "pass", "IQ-10": "pass"}
    assert q.verdict(record) == "INCOMPLETE"          # no PostgreSQL and no Keycloak here: never a pass by omission
    keycloak = repo.parent / "modeler-keycloak"
    version = next(line.split("=", 1)[1] for line in (repo / "deploy" / "server" / "keycloak.sh").read_text().splitlines()
                   if line.startswith("KC_VERSION="))
    (keycloak / f"keycloak-{version}" / "bin").mkdir(parents=True)
    (keycloak / f"keycloak-{version}" / "bin" / "kc.sh").write_text("")
    kc = q.keycloak(repo, {**env, "MODELER_KEYCLOAK_HOME": str(keycloak)})
    assert kc["result"] == "pass" and kc["found"] == version


def test_a_changed_locked_file_another_branch_the_wrong_engine_and_a_pilot_fail(repo, tmp_path):
    q = _qualify()
    (repo / ".deployed.json").write_text(json.dumps({"commit": "abc", "branch": "feature", "clean": False}))
    locked = json.loads((repo / "docs" / "architecture" / "locked-files.json").read_text())["files"][0]["path"]
    (repo / locked).write_text("changed")

    def old_engine(cmd):
        return (0, "ospsuite 12.3.0 \nospsuite.parameteridentification 2.2.0 ") if cmd[0] == "Rscript" else (127, "")
    record = q.qualify(repo, {"HOME": str(tmp_path), "MODELER_IMAGE_DIGEST": "sha256:" + "0" * 64},
                       fetch=_health("pilot", "dev"), run=old_engine)
    checks = {c["id"]: c for c in record["checks"]}
    assert checks["IQ-01"]["result"] == "fail" and "deploy only from main" in checks["IQ-01"]["note"]
    assert checks["IQ-02"]["result"] == "fail" and f"changed: {locked}" in checks["IQ-02"]["note"]
    assert checks["IQ-04"]["result"] == "fail" and "12.3.0" in checks["IQ-04"]["found"]
    assert checks["IQ-05"]["result"] == "fail"
    assert checks["IQ-09"]["result"] == "fail" and "never Part 11" in checks["IQ-09"]["note"]
    assert q.verdict(record) == "FAIL"
    (repo / ".deployed.json").unlink()
    assert q.deployed(repo)["result"] == "not_checked"


def test_postgres_migrations_are_checked_against_their_files(repo, tmp_path):
    q = _qualify()
    home = tmp_path / "pg"
    (home / "data").mkdir(parents=True)
    (home / "data" / "PG_VERSION").write_text("16")
    files = sorted((repo / "services" / "api" / "migrations").glob("*.sql"))
    rows = "\n".join(f"{p.name} {hashlib.sha256(p.read_bytes()).hexdigest()}" for p in files)
    env = {"HOME": str(tmp_path), "MODELER_POSTGRES_HOME": str(home)}
    assert q.postgres(repo, env, lambda cmd: (0, f"16.4\n{rows}"))["result"] == "pass"
    tampered = q.postgres(repo, env, lambda cmd: (0, f"16.4\n{files[0].name} {'f' * 64}"))
    assert tampered["result"] == "fail" and "sha256 differs" in tampered["note"]
    assert q.postgres(repo, env, lambda cmd: (1, "not running"))["result"] == "fail"


def test_the_command_writes_the_record_and_fails_on_a_failed_check(repo, tmp_path, monkeypatch, capsys):
    q = _qualify()
    monkeypatch.setattr(q, "_fetch", lambda url: (0, "connection refused"))   # nothing answers: the API is down
    monkeypatch.setattr(q, "_run", lambda cmd: (127, "not found"))
    monkeypatch.setenv("HOME", str(tmp_path))
    out = tmp_path / "iq.json"
    assert q.main(["iq", "--repo", str(repo), "--out", str(out)]) == 1
    assert json.loads(out.read_text())["schema"] == "iq/1" and "IQ FAIL" in capsys.readouterr().out
