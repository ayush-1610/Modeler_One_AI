"""Whether the engine answers, for System status (R-N08; design-review/BACKEND_CHANGE_REQUIREMENTS.md).

The configured engine command is started **without a job**, its lightest call: `run_job.R` loads R and its packages
(jsonlite, digest, ospsuite) and stops on its usage line; `docker_engine.sh` stops on its usage line before Docker is
asked; the development stub starts and stops. Nothing is simulated. The answer is kept a minute beside the platform's
settings (`<read root>/_platform/engine-check.json`, so every API process reads the same one), and the page can be read
again without starting the engine each time. The engine scripts are locked: they are only called, never changed. A
software fixture is named as one: its numbers are never PBPK results (CLAUDE.md).
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from modeler_contracts.runtime import PLACEHOLDER_DIGEST, ConfigurationError, engine_kind, runtime_env
from pbpk_domain.atomic_io import atomic_write_text

TIMEOUT_S = 20                    # the R runner loads ospsuite before its usage line: a few seconds on the server
KEEP_S = 60
_FILE = Path("_platform") / "engine-check.json"
# what an engine that cannot start says (R's own words); its usage line is what one that can says
_LOAD_FAILURES = ("there is no package called", "Error in library", "cannot open file", "No such file or directory")
_SCRIPT = (".R", ".py", ".sh")


def forget(root: str | Path | None) -> None:
    """Drop the kept answer (tests; a configuration change takes a minute otherwise)."""
    if root:
        (Path(root) / _FILE).unlink(missing_ok=True)


def _kept(root: str | Path | None, command: str) -> dict[str, Any] | None:
    """The answer kept for this command, if it is under a minute old."""
    if not root:
        return None
    try:
        kept = json.loads((Path(root) / _FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if kept.get("command_line") != command or time.time() - float(kept.get("at", 0)) >= KEEP_S:
        return None
    return kept.get("answer")


def engine_status(development_command: str, root: str | Path | None) -> dict[str, Any]:
    """The engine's identity and whether it answers: `kind` (pksim, software-fixture, unknown), the command's words,
    the engine id and image digest it records (the digest null while it is the development placeholder), `reachable`
    and `detail` (what was checked, in words), and when. `root`: the read root the answer is kept under."""
    env = runtime_env()
    try:
        command = env.resolved_engine_command(development_command)
    except ConfigurationError as exc:
        return _answer(kind="unknown", command=None, engine_id=None, digest=None, reachable=False, detail=str(exc))
    kept = _kept(root, command)
    if kept is not None:
        return kept
    argv = shlex.split(command)
    kind = engine_kind(command)
    digest = env.image_digest if env.image_digest and env.image_digest != PLACEHOLDER_DIGEST else None
    reachable, detail = _probe(argv, kind)
    answer = _answer(kind=kind, command=" ".join(Path(w).name for w in argv), engine_id=env.resolved_engine_id(command),
                     digest=digest, reachable=reachable, detail=detail)
    if root:
        path = Path(root) / _FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, json.dumps({"command_line": command, "at": time.time(), "answer": answer}))
    return answer


def _answer(**fields: Any) -> dict[str, Any]:
    fields["image_digest"] = fields.pop("digest")
    return {**fields, "checked_at": datetime.now(UTC).isoformat(), "timeout_s": TIMEOUT_S}


def _probe(argv: list[str], kind: str) -> tuple[bool, str]:
    """Start the command without a job and read its answer."""
    if not argv:
        return False, "the engine command is empty"
    program = argv[0]
    if not (shutil.which(program) or Path(program).is_file()):
        return False, f"{Path(program).name} is not found on this server"
    missing = [w for w in argv[1:] if w.endswith(_SCRIPT) and not Path(w).is_file()]
    if missing:
        return False, f"{Path(missing[0]).name} is not found at {missing[0]}"
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT_S, stdin=subprocess.DEVNULL, check=False)
    except subprocess.TimeoutExpired:
        return False, f"it did not answer within {TIMEOUT_S} s"
    except OSError as exc:
        return False, f"it could not be started: {exc}"
    lines = [ln.strip() for ln in f"{done.stderr}\n{done.stdout}".splitlines() if ln.strip()]
    failed = next((ln for ln in lines if any(f in ln for f in _LOAD_FAILURES)), None)
    said = next((ln for ln in lines if "usage" in ln.lower()), lines[-1] if lines else "")
    if kind == "software-fixture":
        return True, ("it starts (a software fixture, not PK-Sim: its numbers are never PBPK results); started without a "
                      "job, nothing is simulated")
    if failed:
        return False, f"it starts but cannot load: “{failed}”"
    if "usage" in said.lower():
        loads = " R and its packages load;" if Path(argv[-1]).name == "run_job.R" or "Rscript" in program else ""
        return True, f"it answers “{said}”;{loads} started without a job, nothing is simulated"
    return False, f"it answered without its usage line: “{said or 'nothing'}”"
