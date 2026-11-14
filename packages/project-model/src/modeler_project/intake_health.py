"""Pipeline health for the administrator (plan §7.8, contracts §6.6, §8.10): where the intake pipeline is blind,
per company and in all, before a model is wrong.

`summary` reads only what the pipeline itself logged: the `RunRecord` lines of every project's `intake/runs.jsonl`
(each run's latest line; each file's latest run) and, for the file names, the `file` lines of `intake/files.jsonl`.
It opens no client file, no ledger and no coverage file, and it answers with counts only: no file name, no value, no
project name. A run line's coverage is the snapshot "at run end" (§4.6); a person's later decisions are on the
project's own Delivery page, not here.

Per company (`companies`, sorted by tenant id) and pooled (`all`):
- `projects`, `files`, `runs`: projects with an intake log, files with a run, runs counted;
- `files_by_state`: each file by its latest run: `read`, `partly_read`, `unsupported`, `unreadable` (the parsed
  document's state), `failed` (the run ended failed), `waiting` (queued or running);
- `mapping` and `mapping_shares`: tables mapped from the cache, by a rule, by the LLM, and left `unread`, as counts and
  as shares of their sum (the cache hit rate is `mapping_shares.cache`);
- `parser_failures`: files whose latest run failed at the `parse` stage, or parsed as `unreadable`;
- `unsupported_by_extension`: the unsupported files by their extension, as written, lower-cased ("" → "(none)");
- `regions`, `regions_unread`, `silent_loss`, `outside_items`, `outside_numeric`, `anchors_checked`,
  `anchors_unresolved`, `needs_ocr_pages`, `values`, `llm_runs`: sums over the files' latest finished runs;
- `stage_seconds`: per stage, the number of timings, their median and their 90th percentile (nearest rank), pooled
  over the samples (never a median of medians);
- `damaged_logs`: logs that could not be read (a line that is not a log line); they are counted, never repaired.

`since` keeps the runs queued at or after that moment. `tenant` keeps one company: it is compared with the directory
names the root lists, and no path is ever built from it.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePath
from typing import Any

from pydantic import ValidationError

from modeler_project.intake_records import FileRecord, RunRecord
from modeler_project.intake_store import ChainedLog

FILE_STATES = ("read", "partly_read", "unsupported", "unreadable", "failed", "waiting")
MAPPING_SOURCES = ("cache", "rule", "llm", "unread")
_SUMS = ("regions", "regions_unread", "silent_loss", "outside_items", "outside_numeric", "anchors_checked",
         "anchors_unresolved", "needs_ocr_pages", "values", "llm_runs")
NO_EXTENSION = "(none)"


@dataclass
class _Counts:
    """What one company's (or every company's) run lines add up to."""

    projects: int = 0
    files: int = 0
    runs: int = 0
    damaged_logs: int = 0
    parser_failures: int = 0
    states: Counter[str] = field(default_factory=Counter)
    mapping: Counter[str] = field(default_factory=Counter)
    unsupported: Counter[str] = field(default_factory=Counter)
    sums: Counter[str] = field(default_factory=Counter)
    stages: dict[str, list[float]] = field(default_factory=dict)

    def add(self, other: _Counts) -> None:
        self.projects += other.projects
        self.files += other.files
        self.runs += other.runs
        self.damaged_logs += other.damaged_logs
        self.parser_failures += other.parser_failures
        for name in ("states", "mapping", "unsupported", "sums"):
            getattr(self, name).update(getattr(other, name))
        for stage, seconds in other.stages.items():
            self.stages.setdefault(stage, []).extend(seconds)

    def view(self) -> dict[str, Any]:
        mapped = sum(self.mapping[s] for s in MAPPING_SOURCES)
        return {
            "projects": self.projects, "files": self.files, "runs": self.runs,
            "files_by_state": {state: self.states[state] for state in FILE_STATES},
            "mapping": {source: self.mapping[source] for source in MAPPING_SOURCES},
            "mapping_shares": {source: (self.mapping[source] / mapped if mapped else 0.0) for source in MAPPING_SOURCES},
            "parser_failures": self.parser_failures,
            "unsupported_by_extension": dict(sorted(self.unsupported.items())),
            **{name: self.sums[name] for name in _SUMS},
            "stage_seconds": {stage: {"n": len(seconds), "median": statistics.median(seconds), "p90": _p90(seconds)}
                              for stage, seconds in sorted(self.stages.items())},
            "damaged_logs": self.damaged_logs,
        }


def _p90(samples: list[float]) -> float:
    """The 90th percentile by nearest rank: the smallest sample at or above 90 % of them."""
    ordered = sorted(samples)
    return ordered[max(0, math.ceil(0.9 * len(ordered)) - 1)]


def _moment(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        found = datetime.fromisoformat(text)
    except ValueError:
        return None
    return found if found.tzinfo else found.replace(tzinfo=UTC)


def _lines(path: Path, counts: _Counts, kind: str | None = None) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        return [entry.body for entry in ChainedLog(path).entries(kind)]
    except ValueError:                                     # a damaged log is counted, never repaired here
        counts.damaged_logs += 1
        return []


def _extension(name: str) -> str:
    return PurePath(name).suffix.lower() or NO_EXTENSION


def _project(intake: Path, since: datetime | None) -> _Counts:
    """One project's counts: each run's latest line, then each file's latest run."""
    counts = _Counts(projects=1)
    names: dict[str, str] = {}
    for body in _lines(intake / "files.jsonl", counts, "file"):
        try:
            record = FileRecord.model_validate(body)
        except ValidationError:
            continue
        names.setdefault(record.sha256, record.name)
    runs: dict[str, RunRecord] = {}
    for body in _lines(intake / "runs.jsonl", counts):
        try:
            run = RunRecord.model_validate(body)
        except ValidationError:
            continue
        runs.pop(run.run_id, None)                         # the latest line of a run is its state, in log order
        runs[run.run_id] = run
    kept = [run for run in runs.values()
            if since is None or ((queued := _moment(run.queued_at)) is not None and queued >= since)]
    counts.runs = len(kept)
    latest: dict[str, RunRecord] = {}
    for run in kept:                                       # in log order: a file's later run replaces its earlier one
        latest[run.sha256] = run
    counts.files = len(latest)
    for sha, run in latest.items():
        failed_at_parse = any(s.stage == "parse" and not s.ok for s in run.stages)
        if run.state in ("queued", "running"):
            state = "waiting"
        elif run.state == "failed":
            state = "failed"
        else:
            state = run.coverage.state if run.coverage is not None else "read"
        counts.states[state] += 1
        if failed_at_parse or state == "unreadable":
            counts.parser_failures += 1
        if state == "unsupported":
            counts.unsupported[_extension(names.get(sha, ""))] += 1
        for timing in run.stages:
            counts.stages.setdefault(timing.stage, []).append(timing.seconds)
        if state == "waiting":
            continue
        tally = run.counters
        counts.mapping.update({"cache": tally.mapped_by_cache, "rule": tally.mapped_by_rule, "llm": tally.mapped_by_llm,
                               "unread": tally.unmapped})
        counts.sums.update({"regions": tally.regions, "outside_items": tally.outside_items,
                            "anchors_checked": tally.anchors_checked, "anchors_unresolved": tally.anchors_unresolved,
                            "needs_ocr_pages": tally.needs_ocr_pages, "values": tally.values, "llm_runs": tally.llm_runs})
        if run.coverage is not None:
            counts.sums.update({"regions_unread": run.coverage.regions_unread, "silent_loss": run.coverage.silent_loss,
                                "outside_numeric": run.coverage.outside_numeric})
    return counts


def summary(root: Path, *, tenant: str | None = None, since: datetime | None = None) -> dict[str, Any]:
    """Pipeline health over a store root (see the module docstring): `{"since", "generated_at", "companies": [{"tenant",
    ...counts}], "all": {...counts}}`. Counts only. `tenant`: one company (an id the root does not list gives no
    company); `since`: the runs queued at or after it (a naive moment is read as UTC)."""
    root = Path(root)
    if since is not None and since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    listed = sorted(p.name for p in root.iterdir() if (p / "projects").is_dir()) if root.is_dir() else []
    total = _Counts()
    companies = []
    for name in listed:
        if tenant is not None and name != tenant:          # compared, never joined into a path
            continue
        company = _Counts()
        for project in sorted(p for p in (root / name / "projects").iterdir() if (p / "intake").is_dir()):
            company.add(_project(project / "intake", since))
        companies.append({"tenant": name, **company.view()})
        total.add(company)
    return {"since": since.isoformat() if since is not None else None,
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "companies": companies, "all": total.view()}
