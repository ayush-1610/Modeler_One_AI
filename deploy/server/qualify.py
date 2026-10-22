"""Installation Qualification (IQ) of a Modeler One server (GAMP 5; validation pack V1, T-32).

What is installed, checked against what the repository says should be, as an ``iq/1`` record the validation pack renders
(`pbpk_domain.report.validation_pack`). Read-only: it changes nothing, and it never prints a secret. Run it through
``deploy/server/qualify.sh iq``, which sets the server's environment (`_env.sh`). Standard library only, so it runs
before anything else is known to work.

  IQ-01 deployed from `main`, a clean tree (the record `deploy/dev/deploy_to_server.sh` writes)
  IQ-02 every locked file matches its recorded sha256 (`docs/architecture/locked-files.json`)
  IQ-03 the dependency locks (`uv.lock`, the web's `package-lock.json`), the Python and Node versions: recorded
  IQ-04 the PK-Sim R packages match the engine catalog the builder's names were harvested from
  IQ-05 the engine identity the API stamps on every run is that catalog's hash
  IQ-06 PostgreSQL 16 holds every migration, each with the sha256 of its file
  IQ-07 Keycloak is installed at the version `keycloak.sh` pins (its download's checksum is checked by `install`)
  IQ-08 the API answers `/health`
  IQ-09 the deployment is production: Keycloak sign-in, every signature Part 11
  IQ-10 the web answers
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import socket
import subprocess
import sys
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from glob import glob
from pathlib import Path

SCHEMA = "iq/1"
Fetch = Callable[[str], tuple[int, str]]
Run = Callable[[list[str]], tuple[int, str]]


def _check(id_: str, item: str, expected: str, found: str, result: str, note: str = "") -> dict[str, str]:
    return {"id": id_, "item": item, "expected": expected, "found": found, "result": result, "note": note}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fetch(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:  # a 127.0.0.1 address this script builds
            return response.status, response.read().decode("utf-8", "replace")
    except OSError as exc:
        return 0, str(exc)


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    return done.returncode, (done.stdout + done.stderr).strip()


def deployed(repo: Path) -> dict[str, str]:
    record = repo / ".deployed.json"
    if not record.is_file():
        return _check("IQ-01", "Deployed from main, a clean tree", "branch main, no local change", "no deployment record",
                      "not_checked", "deployed before deploy_to_server.sh recorded it: deploy again from main")
    d = json.loads(record.read_text(encoding="utf-8"))
    found = f"{d.get('branch')} @ {str(d.get('commit', ''))[:12]}, {'clean' if d.get('clean') else 'local changes'}, " \
            f"{d.get('deployed_at', '')}"
    ok = d.get("branch") == "main" and bool(d.get("clean"))
    return _check("IQ-01", "Deployed from main, a clean tree", "branch main, no local change", found, "pass" if ok else "fail",
                  "" if ok else "CLAUDE.md: deploy only from main")


def locked_files(repo: Path) -> dict[str, str]:
    manifest = json.loads((repo / "docs" / "architecture" / "locked-files.json").read_text(encoding="utf-8"))
    recorded = {f["path"]: f["sha256"] for f in manifest["files"]}
    missing = sorted(p for p in recorded if not (repo / p).is_file())
    changed = sorted(p for p in recorded if (repo / p).is_file() and _sha256(repo / p) != recorded[p])
    found = f"{len(recorded) - len(missing) - len(changed)} of {len(recorded)} match"
    problems = [f"changed: {p}" for p in changed] + [f"missing: {p}" for p in missing]
    return _check("IQ-02", "Locked files (engine scripts, golden files, rulesets, CPF schema, audit, signatures, …)",
                  f"all {len(recorded)} match their recorded sha256", found, "fail" if problems else "pass",
                  "; ".join(problems[:10]) + (f"; and {len(problems) - 10} more" if len(problems) > 10 else ""))


def dependencies(repo: Path, run: Run) -> dict[str, str]:
    locks = [p for p in (repo / "uv.lock", repo / "apps" / "web" / "package-lock.json") if p.is_file()]
    node = run(["node", "--version"])
    found = "; ".join(f"{p.relative_to(repo)} sha256 {_sha256(p)[:16]}…" for p in locks)
    found += f"; Python {platform.python_version()}; Node {node[1] if node[0] == 0 else 'not found'}"
    return _check("IQ-03", "Dependency locks and runtimes", "uv.lock and package-lock.json present", found,
                  "recorded" if len(locks) == 2 else "fail", "" if len(locks) == 2 else "a dependency lock file is missing")


def engine_packages(repo: Path, run: Run) -> dict[str, str]:
    catalog = json.loads((repo / "services" / "engine-worker" / "golden" / "catalog.json").read_text(encoding="utf-8"))
    want = {"ospsuite": catalog["engine"]["ospsuite"],
            "ospsuite.parameteridentification": catalog["engine"]["parameter_identification"]}
    expected = ", ".join(f"{k} {v}" for k, v in want.items())
    script = "for (p in c('ospsuite', 'ospsuite.parameteridentification')) cat(p, as.character(packageVersion(p)), '\\n')"
    code, out = run(["Rscript", "-e", script])
    if code != 0:
        return _check("IQ-04", "PK-Sim engine (R packages)", expected, out.splitlines()[-1] if out else "Rscript failed",
                      "fail", "the engine is not installed or not on the PATH _env.sh sets")
    have = dict(line.split()[:2] for line in out.splitlines() if len(line.split()) >= 2)
    ok = all(have.get(k) == v for k, v in want.items())
    return _check("IQ-04", "PK-Sim engine (R packages)", expected, ", ".join(f"{k} {have.get(k, '?')}" for k in want),
                  "pass" if ok else "fail", "" if ok else "the installed engine is not the one the catalog was harvested from")


def engine_identity(repo: Path, env: dict[str, str]) -> dict[str, str]:
    data = json.loads((repo / "services" / "engine-worker" / "golden" / "catalog.json").read_text(encoding="utf-8"))
    want = "catalog:sha256:" + hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    have = env.get("MODELER_IMAGE_DIGEST", "")
    return _check("IQ-05", "Engine identity stamped on every run", want[:31] + "…", (have[:31] + "…") if have else "not set",
                  "pass" if have == want else "fail")


def postgres(repo: Path, env: dict[str, str], run: Run) -> dict[str, str]:
    home = Path(env.get("MODELER_POSTGRES_HOME") or Path(env.get("HOME", "~")) / "modeler-postgres")
    files = {p.name: _sha256(p) for p in sorted((repo / "services" / "api" / "migrations").glob("*.sql"))}
    expected = f"PostgreSQL 16; {len(files)} migration(s), each with its file's sha256"
    if not (home / "data" / "PG_VERSION").is_file():
        return _check("IQ-06", "PostgreSQL (Part 11 records)", expected, "not installed", "not_checked",
                      "no PostgreSQL on this server: the Part 11 records stay in files (pilot); see deploy/server/postgres.sh")
    code, out = run(["bash", str(repo / "deploy" / "server" / "postgres.sh"), "applied"])
    if code != 0:
        return _check("IQ-06", "PostgreSQL (Part 11 records)", expected, out.splitlines()[-1] if out else "no answer", "fail",
                      "postgres.sh applied failed: is it running (postgres.sh status)?")
    lines = out.splitlines()
    version = lines[0] if lines else ""
    applied = dict(line.split()[:2] for line in lines[1:] if len(line.split()) >= 2)
    problems = [f"{n}: not applied" for n in files if n not in applied]
    problems += [f"{n}: sha256 differs from its file" for n in files if n in applied and applied[n] != files[n]]
    ok = version.startswith("16") and not problems
    return _check("IQ-06", "PostgreSQL (Part 11 records)", expected, f"PostgreSQL {version}; {len(applied)} applied",
                  "pass" if ok else "fail", "; ".join(problems))


def keycloak(repo: Path, env: dict[str, str]) -> dict[str, str]:
    script = (repo / "deploy" / "server" / "keycloak.sh").read_text(encoding="utf-8")
    match = re.search(r"^KC_VERSION=([\w.]+)", script, re.MULTILINE)
    pinned = match.group(1) if match else "?"
    home = Path(env.get("MODELER_KEYCLOAK_HOME") or Path(env.get("HOME", "~")) / "modeler-keycloak")
    installed = sorted(Path(p).parents[1].name.removeprefix("keycloak-") for p in glob(str(home / "keycloak-*" / "bin" / "kc.sh")))
    if not installed:
        return _check("IQ-07", "Keycloak (sign-in, step-up)", f"Keycloak {pinned}", "not installed", "not_checked",
                      "no Keycloak on this server: the DEV verifier signs (pilot)")
    ok = pinned in installed
    return _check("IQ-07", "Keycloak (sign-in, step-up)", f"Keycloak {pinned}", ", ".join(installed),
                  "pass" if ok else "fail", "" if ok else "the installed Keycloak is not the version keycloak.sh pins")


def api_health(env: dict[str, str], fetch: Fetch) -> tuple[dict[str, str], dict[str, str]]:
    port = env.get("MODELER_API_PORT", "8000")
    status, body = fetch(f"http://127.0.0.1:{port}/health")
    try:
        health = json.loads(body) if status == 200 else {}
    except ValueError:
        health = {}
    up = _check("IQ-08", "API", "/health answers ok", f"HTTP {status}: {health.get('status', body[:80])}",
                "pass" if health.get("status") == "ok" else "fail")
    deployment, verifier = health.get("deployment"), health.get("verifier")
    production = deployment == "production" and verifier == "oidc"
    mode = _check("IQ-09", "Deployment and sign-in", "production, OIDC (Keycloak): every signature Part 11",
                  f"{deployment or 'unknown'}, {verifier or 'unknown'}",
                  "pass" if production else ("not_checked" if not health else "fail"),
                  "" if production else ("the API did not answer" if not health
                                         else "a pilot signs with the DEV verifier, never Part 11 (continuation §4.4)"))
    return up, mode


def web(env: dict[str, str], fetch: Fetch) -> dict[str, str]:
    port = int(env.get("MODELER_WEB_PORT", "3000"))
    if env.get("MODELER_WEB_TLS"):  # HTTPS with the server's own certificate: whether it listens is what is checked here
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=10):
                found, ok = f"listening on {port} (HTTPS)", True
        except OSError as exc:
            found, ok = str(exc), False
    else:
        status, _ = fetch(f"http://127.0.0.1:{port}/")
        found, ok = f"HTTP {status}", status == 200
    return _check("IQ-10", "Web application", "answers", found, "pass" if ok else "fail")


def qualify(repo: Path, env: dict[str, str], *, fetch: Fetch = _fetch, run: Run = _run) -> dict:
    checks = [deployed(repo), locked_files(repo), dependencies(repo, run), engine_packages(repo, run),
              engine_identity(repo, env), postgres(repo, env, run), keycloak(repo, env), *api_health(env, fetch), web(env, fetch)]
    return {"schema": SCHEMA, "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "subject": f"{socket.gethostname()} ({platform.system()} {platform.release()}), {repo}", "checks": checks}


def verdict(record: dict) -> str:
    results = [c["result"] for c in record["checks"]]
    return "FAIL" if "fail" in results else ("INCOMPLETE" if "not_checked" in results else "PASS")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Installation Qualification of this server (read-only).")
    parser.add_argument("command", choices=("iq",))
    parser.add_argument("--repo", default=os.environ.get("MODELER_REPO", str(Path.home() / "Modeler_One_AI")))
    parser.add_argument("--out", help="the JSON record [<MODELER_DATA>/qualification/iq-<UTC time>.json]")
    args = parser.parse_args(argv)
    record = qualify(Path(args.repo), dict(os.environ), fetch=_fetch, run=_run)
    out = Path(args.out) if args.out else (Path(os.environ.get("MODELER_DATA", Path.home() / "modeler-data")) / "qualification"
                                           / f"iq-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for c in record["checks"]:
        print(f"{c['id']}  {c['result']:<11} {c['item']}: {c['found']}" + (f" ({c['note']})" if c["note"] else ""))
    print(f"IQ {verdict(record)}; record: {out}")
    return 1 if verdict(record) == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
