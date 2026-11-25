"""The Data room's files of one project, under `<root>/<tenant>/projects/<project>/dataroom/` (plan 2026-11-21 v2 §9).

    uploads.json                 the uploads: name, sha256 (bytes in the project's blobs), who, when
    files.json                   every real file of the uploads, as read (FileView, no document)
    docs/<sha256>.json.gz        each file's read document (SourceDocument), write-once per reader version
    question.json                the question card, and who confirmed it when
    triage/<sha256>.json         the triage agent's answer for one file
    extractions/<sha256>.json    the extractor's answer for one file (tables described, facts quoted), with its model
    reviews/<sha256>.json        the checker's issues with one file's tables, and the extraction they were found in
    writing.json                 the writer's finding lines and request wording (numbers checked against the room)
    decisions.jsonl              the modeler's decisions, append-only: the last line per decision id stands
    entered.jsonl                values entered by a person, append-only, with the reason
    requests.jsonl               data request edits (wording, status), append-only
    run.json                     the background run: stage, counts, per-agent model, errors; a pause (why, where, when
                                 it resumes)
    publications/<id>.json       what each "Send to the model" rested on, written once (`dataroom.publish`, its shape)

Every decision, entered value and confirmation is also written to the project's audit trail (21 CFR Part 11: who, when,
what, why). No path is built from input that is not a checked sha256. Every stored answer is written to a temporary file
and renamed into place (`atomic_write_text`), so a crash while writing leaves the previous answer whole, never half of
the next; the append-only logs skip a line a crash cut short.

The agents' answers are also kept for the whole tenant, by every input that can change them, in
`<root>/<tenant>/dataroom_cache/` (`answer_cache`), so another project's run with the same file, question and model
reuses them.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from modeler_intake.room_specs import Extraction, FileTriage, QuestionCard
from modeler_intake.source_model import SourceDocument
from modeler_project.dataroom.model import FileView, Value
from modeler_project.workspace import Workspace
from pbpk_domain.atomic_io import atomic_write_bytes, atomic_write_text, file_lock

_SHA = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[A-Za-z0-9_.:\-\s()/,&+%·]{1,200}")
_PUBLICATION = re.compile(r"pub-\d{8}T\d{6}Z-[0-9a-f]{6}")


def _sha(value: str) -> str:
    if not _SHA.fullmatch(value):
        raise KeyError(f"not a sha256: {value!r}")
    return value


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


STEP_TEXT_LIMIT = 2000   # characters of a tool's answer the agents' record keeps


class DataRoomStore:
    def __init__(self, ws: Workspace):
        self.ws = ws
        root = getattr(ws.store, "root", None)
        self.available = root is not None
        self.base: Path | None = (Path(root) / ws.tenant_id / "projects" / ws.project_id / "dataroom") if root else None

    def _path(self, *parts: str) -> Path:
        if self.base is None:
            raise RuntimeError("the project store has no file root: the Data room is off")
        return self.base.joinpath(*parts)

    def _read_json(self, *parts: str) -> Any:
        path = self._path(*parts)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def _append(self, name: str, row: dict[str, Any]) -> None:
        path = self._path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(path), path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()

    def _rows(self, name: str) -> list[dict[str, Any]]:
        path = self._path(name)
        if not path.exists():
            return []
        return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip().endswith("}")]

    def log_agent_step(self, *, stage: str, file: str, model: str, step: dict[str, Any]) -> None:
        """One turn of an agent (its model's answer, a tool's answer, a switch to another model), append-only: what the
        run's record shows of who said what (21 CFR Part 11 §11.10(e); the governance review, 2026-11-22). A tool's
        long answer (a file's lines) is kept to its first characters: the file itself is the record of its text."""
        def short(value: Any) -> Any:
            if isinstance(value, str) and len(value) > STEP_TEXT_LIMIT:
                return value[:STEP_TEXT_LIMIT] + f" … ({len(value)} characters)"
            return value
        self._append("agent_steps.jsonl", {"at": _now(), "stage": stage, "file": file, "model": model,
                                           **{k: short(v) for k, v in step.items()}})

    def agent_steps(self) -> list[dict[str, Any]]:
        return self._rows("agent_steps.jsonl")

    def record_author(self, *, stage: str, file: str, model: str, identity: str, prompt: str, note: str = "") -> None:
        """Who wrote a saved answer (a stage's, for a file or the delivery), append-only: the model's label, its
        provider/model id, the prompt version, and a note (a checker that was not a second opinion). The evidence report's
        "How this report was made" is read from it (the governance review, 2026-11-22, requirements 8 and 9)."""
        self._append("authors.jsonl", {"at": _now(), "stage": stage, "file": file, "model": model, "identity": identity,
                                       "prompt": prompt, "note": note})

    def authors(self) -> list[dict[str, Any]]:
        return self._rows("authors.jsonl")

    def append_run(self, summary: dict[str, Any]) -> None:
        """A finished run kept beside the live `run.json`, which the next run replaces."""
        self._append("runs.jsonl", summary)

    def runs(self) -> list[dict[str, Any]]:
        return self._rows("runs.jsonl")

    def audit(self, *, actor: str, action: str, resource_id: str, after: dict[str, Any], reason: str | None = None) -> None:
        self.ws.store.audit(self.ws.tenant_id).append(actor=actor, action=action, resource_type="dataroom",
                                                      resource_id=f"{self.ws.project_id}/{resource_id}", after=after,
                                                      reason=reason)

    # --- uploads and files ------------------------------------------------------------------------------------------

    def add_upload(self, name: str, data: bytes, *, by: str) -> dict[str, Any]:
        sha = self.ws.store.put_blob(self.ws.tenant_id, self.ws.project_id, data)
        uploads = self.uploads()
        if not any(u["sha256"] == sha for u in uploads):
            uploads.append({"name": name, "sha256": sha, "size_bytes": len(data), "by": by, "at": _now()})
            atomic_write_text(self._path("uploads.json"), json.dumps(uploads, indent=1, ensure_ascii=False))
            self.audit(actor=by, action="dataroom.upload", resource_id=sha, after={"name": name, "size_bytes": len(data)})
        return next(u for u in uploads if u["sha256"] == sha)

    def uploads(self) -> list[dict[str, Any]]:
        return self._read_json("uploads.json") or []

    def upload_bytes(self, sha256: str) -> bytes:
        path = self.ws.store.blob_path(self.ws.tenant_id, self.ws.project_id, _sha(sha256))
        if path is None:
            raise KeyError(sha256)
        return path.read_bytes()

    def file_bytes(self, sha256: str) -> bytes:
        """A delivered file's bytes (KeyError when no upload holds them): its own upload, else the member of an uploaded
        archive it was unpacked from (`modeler_intake.room.expand_uploads`, as the read stage unpacks them)."""
        from modeler_intake.room import expand_uploads

        wanted = _sha(sha256)
        if any(u["sha256"] == wanted for u in self.uploads()):
            return self.upload_bytes(wanted)
        for u in self.uploads():
            if not u["name"].lower().endswith(".zip"):
                continue
            expanded, _unreadable = expand_uploads([(u["name"], self.upload_bytes(u["sha256"]))])
            for _path, data in expanded:
                if hashlib.sha256(data).hexdigest() == wanted:
                    return data
        raise KeyError(sha256)

    def set_files(self, files: list[FileView]) -> None:
        atomic_write_text(self._path("files.json"), json.dumps([f.model_dump(mode="json") for f in files], indent=1,
                                                               ensure_ascii=False))

    def files(self) -> list[FileView]:
        rows = self._read_json("files.json") or []
        triage = {sha: t for sha in {r["sha256"] for r in rows} if (t := self.triage(sha)) is not None}
        return [FileView.model_validate(r).model_copy(update={"triage": triage.get(r["sha256"])}) for r in rows]

    def put_doc(self, sha256: str, doc: SourceDocument) -> None:
        atomic_write_bytes(self._path("docs", f"{_sha(sha256)}.json.gz"), gzip.compress(doc.model_dump_json(by_alias=True).encode()))

    def doc(self, sha256: str) -> SourceDocument | None:
        path = self._path("docs", f"{_sha(sha256)}.json.gz")
        if not path.exists():
            return None
        return SourceDocument.model_validate_json(gzip.decompress(path.read_bytes()))

    def docs(self) -> dict[str, SourceDocument]:
        return {f.sha256: d for f in self.files() if not f.duplicate_of and (d := self.doc(f.sha256)) is not None}

    # --- the question -------------------------------------------------------------------------------------------------

    def set_question(self, card: QuestionCard, *, by: str, confirmed: bool = False, reason: str = "") -> None:
        atomic_write_text(self._path("question.json"), json.dumps(
            {"card": card.model_dump(mode="json"), "confirmed": confirmed, "by": by, "at": _now()}, indent=1, ensure_ascii=False))
        if confirmed:
            self.audit(actor=by, action="dataroom.question.confirm", resource_id="question",
                       after={"question": card.question, "checklist": [c.id for c in card.checklist]}, reason=reason or None)

    def question(self) -> tuple[QuestionCard | None, bool]:
        row = self._read_json("question.json")
        return (QuestionCard.model_validate(row["card"]), bool(row["confirmed"])) if row else (None, False)

    def question_record(self) -> dict[str, Any]:
        """Who set the question card, and when ({} when there is none)."""
        row = self._read_json("question.json") or {}
        return {k: row[k] for k in ("confirmed", "by", "at") if k in row}

    # --- what each "Send to the model" rested on --------------------------------------------------------------------------

    def put_publication(self, publication_id: str, record: dict[str, Any]) -> None:
        """One publication's record (`dataroom.publish.publication_record`), written once: a second write of the same id
        is refused."""
        if not _PUBLICATION.fullmatch(publication_id):
            raise ValueError("not a publication id")
        path = self._path("publications", f"{publication_id}.json")
        if path.exists():
            raise ValueError(f"publication {publication_id} is already recorded")
        atomic_write_text(path, json.dumps(record, indent=1, ensure_ascii=False, sort_keys=True))

    def publication(self, publication_id: str) -> dict[str, Any] | None:
        return self._read_json("publications", f"{publication_id}.json") if _PUBLICATION.fullmatch(publication_id) else None

    def publications(self) -> list[dict[str, Any]]:
        """Every publication's record, oldest first."""
        folder = self._path("publications")
        if not folder.is_dir():
            return []
        rows = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("pub-*.json"))
                if _PUBLICATION.fullmatch(p.stem)]
        return sorted(rows, key=lambda r: (str(r.get("at", "")), str(r.get("id", ""))))

    # --- agents' answers ------------------------------------------------------------------------------------------------

    def put_triage(self, triage: FileTriage, sha256: str) -> None:
        atomic_write_text(self._path("triage", f"{_sha(sha256)}.json"), triage.model_dump_json(indent=1))

    def triage(self, sha256: str) -> FileTriage | None:
        row = self._read_json("triage", f"{_sha(sha256)}.json")
        return FileTriage.model_validate(row) if row else None

    def put_extraction(self, extraction: Extraction, sha256: str, *, agent: dict[str, str]) -> None:
        atomic_write_text(self._path("extractions", f"{_sha(sha256)}.json"), json.dumps(
            {"extraction": extraction.model_dump(mode="json"), "agent": agent, "at": _now()}, indent=1, ensure_ascii=False))

    def extraction(self, sha256: str) -> tuple[Extraction, dict[str, str]] | None:
        row = self._read_json("extractions", f"{_sha(sha256)}.json")
        return (Extraction.model_validate(row["extraction"]), row.get("agent", {})) if row else None

    def extractions(self) -> list[Extraction]:
        return [e for f in self.files() if not f.duplicate_of and (got := self.extraction(f.sha256)) for e in (got[0],)]

    def extraction_stamp(self, sha256: str) -> str:
        """The stored extraction of a file as it now stands (the sha256 of its record; "" when there is none): a review
        names the extraction it checked, so it stands until the extraction is made again."""
        path = self._path("extractions", f"{_sha(sha256)}.json")
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""

    def put_review(self, sha256: str, issues: list[dict[str, Any]], *, agent: str, extraction: str = "") -> None:
        """The checker's issues with one file's tables, and the extraction they were found in (`extraction_stamp`)."""
        atomic_write_text(self._path("reviews", f"{_sha(sha256)}.json"), json.dumps(
            {"issues": issues, "agent": agent, "at": _now(), "extraction": extraction}, indent=1, ensure_ascii=False))

    def review(self, sha256: str) -> dict[str, Any] | None:
        return self._read_json("reviews", f"{_sha(sha256)}.json")

    def review_current(self, sha256: str) -> bool:
        """Whether the file's review checked its extraction as it now stands: a run (or a paused run resumed) does not
        check it again. A review kept before reviews named their extraction is checked once more."""
        row = self.review(sha256)
        return bool(row and row.get("extraction") and row["extraction"] == self.extraction_stamp(sha256))

    def reviews(self) -> dict[str, list[dict[str, Any]]]:
        """The checker's issues per file path."""
        out = {}
        for f in self.files():
            row = self._read_json("reviews", f"{f.sha256}.json") if _SHA.fullmatch(f.sha256) else None
            if row and row.get("issues"):
                out[f.path] = row["issues"]
        return out

    def put_writing(self, findings: dict[str, str], requests: dict[str, str], *, agent: str,
                    basis: dict[str, str] | None = None) -> None:
        """The writer's lines, with code's findings they were written against (`basis`): a line is shown only while code
        still finds the same (assemble's `section`)."""
        atomic_write_text(self._path("writing.json"), json.dumps(
            {"findings": findings, "requests": requests, "basis": basis or {}, "agent": agent, "at": _now()}, indent=1,
            ensure_ascii=False))

    def writing(self) -> dict[str, dict[str, str]]:
        row = self._read_json("writing.json") or {}
        return {"findings": row.get("findings", {}), "requests": row.get("requests", {}), "basis": row.get("basis", {})}

    # --- the modeler's word -------------------------------------------------------------------------------------------------

    def decide(self, decision_id: str, chosen: str, *, by: str, reason: str = "") -> dict[str, str]:
        if not _ID.fullmatch(decision_id) or not _ID.fullmatch(chosen):
            raise ValueError("not a decision id or option id")
        row = {"id": decision_id, "chosen": chosen, "reason": reason, "by": by, "at": _now()}
        self._append("decisions.jsonl", row)
        self.audit(actor=by, action="dataroom.decide", resource_id=decision_id, after={"chosen": chosen}, reason=reason or None)
        return row

    def decisions(self) -> dict[str, dict[str, str]]:
        return {r["id"]: r for r in self._rows("decisions.jsonl")}

    def enter(self, value: Value, *, by: str, reason: str) -> None:
        if not reason.strip():
            raise ValueError("a value entered by a person needs its reason")
        row = value.model_copy(update={"status": "entered", "note": reason}).model_dump(mode="json")
        self._append("entered.jsonl", {"value": row, "by": by, "at": _now()})
        self.audit(actor=by, action="dataroom.enter", resource_id=value.key, after={"value": value.value, "unit": value.unit},
                   reason=reason)

    def entered(self) -> list[Value]:
        latest: dict[str, Value] = {}
        for r in self._rows("entered.jsonl"):
            v = Value.model_validate(r["value"])
            latest[v.key] = v
        return list(latest.values())

    def edit_request(self, request_id: str, *, by: str, wording: str | None = None, status: str | None = None) -> None:
        if not re.fullmatch(r"[ABCD]-\d{2}", request_id):
            raise ValueError("not a data request id")
        if status not in (None, "open", "not_needed", "answered"):
            raise ValueError("not a data request status")
        self._append("requests.jsonl", {"id": request_id, "wording": wording, "status": status, "by": by, "at": _now()})
        self.audit(actor=by, action="dataroom.request", resource_id=request_id, after={"status": status, "wording": wording})

    def request_edits(self) -> dict[str, dict[str, str]]:
        out: dict[str, dict[str, str]] = {}
        for r in self._rows("requests.jsonl"):
            entry = out.setdefault(r["id"], {})
            for k in ("wording", "status"):
                if r.get(k) is not None:
                    entry[k] = r[k]
        return out

    # --- the background run -----------------------------------------------------------------------------------------------

    def set_stage_notes(self, stage: str, notes: list[str]) -> None:
        """What a stage could not do, file by file (shown with the run)."""
        if not re.fullmatch(r"[a-z]+", stage):
            raise ValueError("not a stage")
        atomic_write_text(self._path("notes", f"{stage}.json"), json.dumps(notes, indent=1, ensure_ascii=False))

    def stage_notes(self, stage: str) -> list[str]:
        return (self._read_json("notes", f"{stage}.json") or []) if re.fullmatch(r"[a-z]+", stage) else []

    def set_run(self, run: dict[str, Any]) -> None:
        atomic_write_text(self._path("run.json"), json.dumps(run, indent=1, ensure_ascii=False, default=str))

    def run(self) -> dict[str, Any]:
        return self._read_json("run.json") or {"state": "idle"}
