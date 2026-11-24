"""The Data room's exact answer cache (plan 2026-11-24 §5 item 2): an agent's answer for one file and one stage (triage
A7, extraction A8, check A9), kept by every input that can change it, so a file already read the same way is not read
again: a demo shown again, a delivery sent again in a new project, a run again after a fix to another file.

    <root>/<tenant>/dataroom_cache/<stage>/<key sha256>.json      one answer, with its key and who wrote it

Rules:
- **Per tenant.** The cache sits beside the tenant's projects and is never read for another tenant (a client's files
  and what was read from them stay within the tenant).
- **Exact.** An entry is found by the sha256 of its whole key, and is used only when the stored key is the asked key,
  field by field: the tenant, the stage, the prompt version, the file (sha256 and path), the reader (parser, its
  version, the version of the lines and the hash of the lines the agent reads), the model (provider/model id, its
  service address, its effort), the stage's other inputs (the question card's fields its prompt uses, the triage given
  to the extractor, the extraction being checked, the page budget, the checker's feedback) and the hash of the first
  request as sent (instructions, tools, task). Never a "similar" answer.
- **Only an answer code accepted.** The stages write an entry only when the answer passed code's checks with no problem
  left, and check it again against this project's file before they use it.
- **Clearing it.** Delete the tenant's `dataroom_cache/` folder, or call `AnswerCache(ws).clear()`. Nothing else reads
  it: a cleared cache only means the next run asks the models again. (No admin page clears it yet.)
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from modeler_project.workspace import Workspace
from pbpk_domain.atomic_io import atomic_write_text

CACHE_DIR = "dataroom_cache"
CachedStage = Literal["triage", "extract", "check"]
CACHED_STAGES: tuple[str, ...] = ("triage", "extract", "check")
_TENANT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.\-]{0,127}")


def stable_sha256(value: Any) -> str:
    """The sha256 of a value as sorted, compact JSON: the same value always gives the same hash."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                                     default=str).encode()).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class AnswerKey(BaseModel):
    """Every input that can change an agent's answer for one file and one stage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant: str
    stage: CachedStage
    prompt_version: str                 # the stages' PROMPT_VERSION (their instructions and tools)
    file_sha256: str
    path: str                           # the file's path in the delivery, as the prompt names it
    reader: str                         # parser/parser version; lines version (`modeler_intake.room.LINES_VERSION`)
    text_sha256: str                    # the lines the agent reads (`modeler_intake.room.parts_sha256`)
    model: str                          # provider/model id of the model that answers first
    endpoint: str = ""                  # its service address, where one provider name serves many (OpenAI-compatible)
    effort: str = ""                    # its effort ("" for the model's own default)
    inputs: dict[str, str] = Field(default_factory=dict)   # the stage's other inputs, by name: a hash or a setting
    request_sha256: str                 # the first request as sent: the instructions, the tools and the task

    def digest(self) -> str:
        return stable_sha256(self.model_dump(mode="json"))


class CachedAnswer(BaseModel):
    """One answer as an agent submitted it and code accepted it, with who wrote it and where."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: AnswerKey
    answer: dict[str, Any]
    author: str                         # the model's label as the run showed it
    identity: str                       # provider/model id of the model that wrote it
    project: str                        # the project whose run wrote it
    run: str = ""                       # that run (when it started)
    at: str

    @property
    def note(self) -> str:
        """What the author record of a project that reused it says."""
        return (f"reused: same file, same question, same model (from project {self.project}, "
                f"run {self.run or 'not recorded'})")


class AnswerCache:
    """The tenant's cached answers (see the module docstring). Off (every lookup a miss, nothing written) when the project
    store has no file root."""

    def __init__(self, ws: Workspace):
        self.ws = ws
        root = getattr(ws.store, "root", None)
        ok = root is not None and bool(_TENANT.fullmatch(ws.tenant_id))
        self.base: Path | None = Path(root) / ws.tenant_id / CACHE_DIR if ok else None

    @property
    def available(self) -> bool:
        return self.base is not None

    def _file(self, key: AnswerKey) -> Path | None:
        if self.base is None or key.tenant != self.ws.tenant_id:
            return None              # another tenant's key is never looked up, nor written, here
        return self.base / key.stage / f"{key.digest()}.json"

    def get(self, key: AnswerKey) -> CachedAnswer | None:
        """The answer stored under exactly this key; None when there is none (or it cannot be read)."""
        path = self._file(key)
        if path is None or not path.is_file():
            return None
        try:
            entry = CachedAnswer.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError):
            return None              # an entry that cannot be read is a miss, never an answer
        return entry if entry.key == key else None

    def put(self, key: AnswerKey, answer: dict[str, Any], *, author: str, identity: str, run: str = "") -> CachedAnswer | None:
        """Keep an answer code accepted (the newest stands for its key). None when the cache is off."""
        path = self._file(key)
        if path is None:
            return None
        entry = CachedAnswer(key=key, answer=answer, author=author, identity=identity, project=self.ws.project_id,
                             run=run, at=_now())
        atomic_write_text(path, entry.model_dump_json(indent=1))
        return entry

    def clear(self, stage: str | None = None) -> int:
        """Remove the tenant's cached answers (one stage's, or all); the number removed."""
        if self.base is None or (stage is not None and stage not in CACHED_STAGES):
            return 0
        removed = 0
        for name in [stage] if stage else CACHED_STAGES:
            folder = self.base / name
            for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
                path.unlink(missing_ok=True)
                removed += 1
        return removed


__all__ = ["CACHED_STAGES", "AnswerCache", "AnswerKey", "CachedAnswer", "stable_sha256"]
