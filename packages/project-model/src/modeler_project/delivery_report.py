"""What the agents made of a client's delivery, and how close it is to what a person reads in the files (plan
2026-11-10, R6).

The report reads a project as the server keeps it and says, per client file: how far its reading got (the reading
queue), what the delivery map says it is, what its readings proposed (datasets, study facts, dissolution rows, links,
sheets saved and sheets read but waiting for a person's answers), what code refused and why, and the figures suggested.
Then, for the project: the studies with a concentration-time profile (saved, or read and waiting for a person), the
dissolution profiles (likewise), the links between names, and every file not read or failed.

With an answer key (YAML, written by a person who has read the files), it scores the map and the readings: each field
of each file the key states is found, wrong or missing (names compared exactly, case, spaces and punctuation aside);
each study and each dissolution condition the key expects is found or missing, under the key's names or a name a
person confirmed (a link only proposed is shown, not counted); what was found and the key does not name is listed; and
whatever the key says that the score cannot use is listed, never dropped. The key is the person's reading, not a fact:
a mismatch is a question to look at, either way. Read-only: nothing is written.

    uv run python -m modeler_project.delivery_report --root ~/modeler-data/read-root --project <id> [--key key.yaml]
        [--json] [--out report.md]
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path
from typing import Any

import yaml

from modeler_intake.document_reading import name_key
from modeler_project.client_data import delivery_map, document_links, submissions
from modeler_project.client_review import ALIASES
from modeler_project.client_review import record as review_record
from modeler_project.dataset_register import datasets
from modeler_project.delivery_map import FIELDS, file_line
from modeler_project.dissolution_register import profiles
from modeler_project.documents import DocumentLibrary
from modeler_project.evidence import EvidenceState
from modeler_project.figure_suggestions import open_suggestions
from modeler_project.reading_queue import ReadingQueue
from modeler_project.sheet_intake import drafts
from modeler_project.store import FileProjectStore
from modeler_project.workspace import Workspace

TOP_REFUSALS = 8
# the names a person may write a key's field by (the report's own labels among them): each means one map field
FIELD_NAMES = {**{f: f for f in FIELDS}, "strength": "strength_mg", "food": "food_state", "study_id": "study"}
KEY_SECTIONS = ("files", "studies", "dissolution")
FILE_KEYS = ("name", "sheets")


class AnswerKeyError(ValueError):
    """The answer key is not as the scorer reads it; the message names the entry."""


# ---- the report ---------------------------------------------------------------------------------------------------

def _latest_items(ws: Workspace) -> dict[str, dict[str, Any]]:
    """Each file's latest reading-queue item (where its reading stands)."""
    return {i.sid: i.model_dump(mode="json") for i in ReadingQueue(ws).items()}


def _npoints(points: Any) -> int:
    """How many time points a draft's points hold (a dataset's content: series with their times)."""
    if isinstance(points, dict):
        return sum(len(series.get("times", [])) for series in points.get("series", []))
    return int(points or 0) if isinstance(points, (int, float)) else 0


def _draft_ph(subs: dict[str, dict[str, Any]], sid: str, sheet: str) -> float | None:
    form = ((subs.get(sid) or {}).get("readings") or {}).get(sheet, {}).get("form", {})
    try:
        return float(form.get("constants", {}).get("ph"))
    except (TypeError, ValueError):
        return None


def _studies(ws: Workspace, waiting: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The studies with a concentration-time profile: saved datasets not rejected, and sheets read but waiting for a
    person's answers (a profile sheet always needs one), each with its points and sources."""
    out: dict[str, dict[str, Any]] = {}

    def entry(study: str) -> dict[str, Any]:
        return out.setdefault(study, {"study": study, "datasets": 0, "waiting": 0, "points": 0, "series": 0,
                                      "sources": set(), "states": set()})

    for d in datasets(ws):
        if d.state is EvidenceState.REJECTED or d.kind != "profile":
            continue
        e = entry(str(d.study.get("study_id", "")))
        e["datasets"] += 1
        e["series"] += len(d.series)
        e["points"] += sum(len(s.times) for s in d.series)
        e["sources"].add(d.source.title if d.source else "")
        e["states"].add(d.state.value)
    for w in waiting:
        if w["kind"] != "concentration_time":
            continue
        e = entry(w["study_id"])
        e["waiting"] += 1
        e["points"] += _npoints(w.get("points"))
        e["sources"].add(f"{w['file']} ({w['sheet']})")
        e["states"].add("WAITING FOR A PERSON")
    return [{**e, "sources": sorted(x for x in e["sources"] if x), "states": sorted(e["states"])} for e in out.values()]


def report(ws: Workspace) -> dict[str, Any]:
    """The delivery as the agents left it, per file and for the project (plain data, for JSON or Markdown)."""
    library = DocumentLibrary(ws)
    entries = library.entries() if library.has_record else {}
    items = _latest_items(ws)
    mapped = delivery_map(ws)
    subs = {sub["id"]: sub for sub in submissions(ws)}
    waiting = drafts(ws)
    files = []
    for sid, sub in subs.items():
        entry = entries.get(sub["sha256"])
        reads = sub.get("document_reads", [])
        last = reads[-1] if reads else {}
        saved = {t.get("sheet") for m in sub.get("mappings", []) if not m.get("replaced_by")
                 for t in m.get("recipe", {}).get("tables", [])}
        item = items.get(sid)
        files.append({
            "sid": sid, "file": sub["file"], "kind": sub.get("kind", ""), "template": bool(sub.get("template")),
            "tag": entry.tag.kind if entry and entry.tag else "", "withdrawn": bool(entry and entry.withdrawn),
            "reading": {"state": item["state"], "task": item["task"], "note": item["note"], "found": item["found"],
                        "attempts": item["attempts"]} if item else None,
            "map": mapped["files"].get(sid, {}), "map_line": file_line(mapped["files"].get(sid, {})),
            "map_looked_at": sid in mapped["looked_at"], "map_tries": mapped["tries"].get(sid, 0),
            "datasets": len(sub.get("datasets", [])), "study_facts": len(sub.get("study_facts", [])),
            "dissolution_rows": len(sub.get("dissolution", [])), "links": len(sub.get("study_links", [])),
            "sheets": [t["sheet"] for t in sub.get("triage", [])],
            "sheets_saved": sorted(s for s in saved if s),
            "sheets_waiting": [{"sheet": w["sheet"], "kind": w["kind"], "study_id": w["study_id"], "needs": w["needs"],
                                "points": _npoints(w.get("points"))} for w in waiting if w["sid"] == sid],
            "agent_readings": len(reads), "refused": list(last.get("refused", []))[:TOP_REFUSALS],
            "figures": len(sub.get("figure_suggestions", [])),
        })
    dissolution = [{"product": p.get("key", {}).get("product", ""), "role": p.get("key", {}).get("role", ""),
                    "ph": p.get("key", {}).get("ph"), "medium": p.get("key", {}).get("medium", ""),
                    "batch": p.get("key", {}).get("batch", ""), "points": len(p.get("times_min", [])),
                    "files": p.get("files", []), "saved": True} for p in profiles(ws)]
    dissolution += [{"product": w["answers"].get("product", ""), "role": w["answers"].get("role", ""),
                     "ph": _draft_ph(subs, w["sid"], w["sheet"]), "medium": w["answers"].get("medium", ""),
                     "batch": w["answers"].get("batch", ""), "points": _npoints(w.get("points")),
                     "files": [f"{w['file']} ({w['sheet']})"], "saved": False}
                    for w in waiting if w["kind"] == "dissolution"]
    links = [{"kind": kind, "names": link["names"], "file": link.get("file", ""), "quote": link.get("quote", "")}
             for kind in ("study", "product", "batch") for link in document_links(ws, kind)]
    live = [f for f in files if not f["withdrawn"]]   # a withdrawn file is counted apart, never as read or failed

    def state(f: dict[str, Any]) -> str | None:
        return f["reading"]["state"] if f["reading"] else None

    return {
        "project": ws.project_id, "files": files, "studies": _studies(ws, waiting), "dissolution": dissolution,
        "links": links, "figures": open_suggestions(ws),
        "map_runs": [{k: r.get(k) for k in ("run_id", "status", "facts", "links", "summary")} | {
            "tried": len(r.get("tried", [])), "refused": len(r.get("refused", []))} for r in mapped["runs"]],
        "counts": {
            "files": len(files), "withdrawn": len(files) - len(live),
            "read": sum(1 for f in live if state(f) == "done"),
            "failed": sum(1 for f in live if state(f) == "failed"),
            "waiting": sum(1 for f in live if state(f) in ("queued", "reading")),
            "never_queued": sum(1 for f in live if state(f) is None),
            "mapped": sum(1 for f in live if f["map_looked_at"]),
            "sheets_waiting": sum(len(f["sheets_waiting"]) for f in live),
        },
    }


# ---- the answer key and the score -----------------------------------------------------------------------------------

def _phs(spec: dict[str, Any]) -> list[Any]:
    """The pH of each profile a dissolution entry expects; none given: the product's presence alone is checked."""
    value = spec.get("ph")
    if value in (None, "", []):
        return [None]
    return value if isinstance(value, list) else [value]


def load_key(path: Path) -> dict[str, Any]:
    """A person's reading of the delivery (YAML): `files` (name, and the fields each states, per sheet too),
    `studies` (each with a concentration-time profile expected, and its other names), `dissolution` (product and the
    pH of each profile expected). A malformed key is refused with the entry named."""
    key = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(key, dict):
        raise AnswerKeyError("the key is a mapping with files, studies and dissolution")
    for n, spec in enumerate(key.get("files") or []):
        if not isinstance(spec, dict) or not spec.get("name"):
            raise AnswerKeyError(f"files[{n}]: each file is a mapping with its name")
        if spec.get("sheets") is not None and not isinstance(spec["sheets"], dict):
            raise AnswerKeyError(f"files[{n}] ({spec['name']}): sheets is a mapping of sheet name to fields")
    for n, spec in enumerate(key.get("studies") or []):
        if not isinstance(spec, dict) or not spec.get("id"):
            raise AnswerKeyError(f"studies[{n}]: each study is a mapping with its id")
    for n, spec in enumerate(key.get("dissolution") or []):
        if not isinstance(spec, dict) or not spec.get("product"):
            raise AnswerKeyError(f"dissolution[{n}]: each entry is a mapping with its product")
        for ph in _phs(spec):
            if ph is not None and (isinstance(ph, bool) or not isinstance(ph, (int, float))):
                raise AnswerKeyError(f"dissolution[{n}] ({spec['product']}): each pH is a number, not {ph!r}")
    return key


def _same(field: str, expected: Any, found: Any) -> bool:
    """Whether the map's value is the key's: numbers equal, a choice the same word, a name the same name (case, spaces
    and punctuation aside; never a part of it: APL 50 is not APL 500). A key may list several spellings."""
    if found is None:
        return False
    for want in expected if isinstance(expected, list) else [expected]:
        if field in ("strength_mg", "ph"):
            try:
                if abs(float(want) - float(found)) < 1e-6:
                    return True
            except (TypeError, ValueError):
                continue
        elif field in ("role", "food_state"):
            if str(want).strip() and str(want).strip().lower() == str(found).strip().lower():
                return True
        elif name_key(str(want)) and name_key(str(want)) == name_key(str(found)):
            return True
    return False


def _norm(name: str) -> str:
    """A file or sheet name as a person may type it: Unicode NFC, spaces collapsed, case aside."""
    return " ".join(unicodedata.normalize("NFC", str(name)).split()).casefold()


def _groups(ws: Workspace, kind: str) -> tuple[list[set[str]], list[set[str]]]:
    """Names one study (or product) goes by: (the aliases a person confirmed, the links only proposed: neither refused
    by a person nor from a withdrawn file)."""
    scope = {"study": "link", "product": "plink"}[kind]
    review = review_record(ws)
    confirmed = [{name_key(a), name_key(b)} for a, b in review.get(ALIASES[scope], {}).items()]
    refused = {name_key(issue.split("|", 1)[1]) for issue, chosen in review.get("selections", {}).items()
               if issue.startswith(f"{scope}|") and chosen.get("option") == "different"}
    library = DocumentLibrary(ws)
    files = {sub["id"]: sub for sub in submissions(ws)}
    proposed = []
    for link in document_links(ws, kind):
        sub = files.get(link.get("sid", ""))
        if sub is not None and library.has_record and library.entry(sub["sha256"]).withdrawn is not None:
            continue
        keys = {name_key(n) for n in link["names"]}
        if not keys & refused:
            proposed.append(keys)
    return confirmed, proposed


def _grow(keys: set[str], groups: list[set[str]]) -> set[str]:
    keys = set(keys)
    grew = True
    while grew:
        grew = False
        for group in groups:
            if group & keys and not group <= keys:
                keys |= group
                grew = True
    return {k for k in keys if k}


def _wanted(where: str, entries: dict[str, Any], unused: list[str], skip: tuple[str, ...] = ()) -> dict[str, Any]:
    """The fields a key entry states, by the map's names; anything else is listed as not used, never dropped."""
    out = {}
    for k, v in entries.items():
        if k in skip:
            continue
        field = FIELD_NAMES.get(str(k).lower())
        if field is None:
            unused.append(f"{where}: {k!r} is not a field ({', '.join(FIELDS)})")
        else:
            out[field] = v
    return out


def score(ws: Workspace, data: dict[str, Any], key: dict[str, Any]) -> dict[str, Any]:
    """The report scored against the key: per field found / wrong / missing; studies and dissolution expected found or
    missing; what was found that the key does not name; what in the key the score could not use."""
    by_name = {_norm(f["file"]): f for f in data["files"]}
    unused = [f"{k}: not a section of the key ({', '.join(KEY_SECTIONS)})" for k in key if k not in KEY_SECTIONS]
    fields: list[dict[str, Any]] = []
    files_missing, files_unread = [], []
    for spec in key.get("files") or []:
        name = spec["name"]
        found = by_name.get(_norm(name))
        if found is None:
            files_missing.append(name)
            continue
        state = found["reading"]["state"] if found["reading"] else None
        if found["withdrawn"] or state != "done":
            files_unread.append({"file": name, "state": "withdrawn" if found["withdrawn"] else state or "not queued",
                                 "note": found["reading"]["note"] if found["reading"] else ""})
        targets = [(None, _wanted(name, spec, unused, FILE_KEYS))]
        sheets = {_norm(s): s for s in found["sheets"]}
        for sheet, fs in (spec.get("sheets") or {}).items():
            expected = _wanted(f"{name} sheet {sheet}", fs or {}, unused)
            real = sheets.get(_norm(sheet))
            if real is None:
                fields += [{"file": name, "sheet": sheet, "field": f, "expected": v, "found": None,
                            "verdict": "no such sheet", "quote": f"sheets: {', '.join(found['sheets']) or 'none'}"}
                           for f, v in expected.items()]
                continue
            targets.append((real, expected))
        for sheet, expected in targets:
            facts = dict(found["map"].get("facts", {}))
            if sheet is not None:   # a sheet is what its file is, and what the sheet adds
                facts.update(found["map"].get("sheets", {}).get(sheet, {}).get("facts", {}))
            for field, want in expected.items():
                got = facts.get(field, {}).get("value")
                verdict = "found" if _same(field, want, got) else "missing" if got is None else "wrong"
                fields.append({"file": name, "sheet": sheet, "field": field, "expected": want, "found": got,
                               "verdict": verdict, "quote": facts.get(field, {}).get("quote", "")})

    confirmed, proposed = _groups(ws, "study")
    have = {name_key(s["study"]): s for s in data["studies"]}
    studies, expected_keys = [], set()
    for spec in key.get("studies") or []:
        keys = _grow({name_key(spec["id"]), *(name_key(n) for n in spec.get("names") or [])}, confirmed)
        linked = _grow(keys, proposed) - keys
        expected_keys |= keys | linked
        hit, via = [have[k] for k in keys if k in have], [have[k] for k in linked if k in have]
        studies.append({"study": spec["id"], "found": bool(hit), "as": [h["study"] for h in hit],
                        "points": sum(h["points"] for h in hit),
                        "waiting": bool(hit) and not any(h["datasets"] for h in hit),
                        "via_proposed_link": [h["study"] for h in via]})
    unexpected = [s["study"] for s in data["studies"] if name_key(s["study"]) not in expected_keys]

    confirmed_p, proposed_p = _groups(ws, "product")
    dissolution = []
    for spec in key.get("dissolution") or []:
        keys = _grow({name_key(spec["product"]), *(name_key(n) for n in spec.get("names") or [])}, confirmed_p)
        linked = _grow(keys, proposed_p) - keys
        for ph in _phs(spec):
            def at(product_keys: set[str], ph: Any = ph) -> list[dict[str, Any]]:
                return [p for p in data["dissolution"] if name_key(str(p["product"])) in product_keys
                        and (ph is None or (p["ph"] is not None and abs(float(p["ph"]) - float(ph)) < 1e-6))]
            hit, via = at(keys), at(linked)
            dissolution.append({"product": spec["product"], "ph": ph, "found": bool(hit),
                                "waiting": bool(hit) and not any(p["saved"] for p in hit),
                                "via_proposed_link": sorted({str(p["product"]) for p in via})})

    def share(rows: list[dict[str, Any]], ok: Any) -> str:
        return f"{sum(1 for r in rows if ok(r))}/{len(rows)}"

    named = len(key.get("files") or [])
    return {
        "fields": fields, "files_missing": files_missing, "files_unread": files_unread, "studies": studies,
        "unexpected_studies": unexpected, "dissolution": dissolution, "unused": unused,
        "summary": {"map_fields_found": share(fields, lambda r: r["verdict"] == "found"),
                    "map_fields_wrong": sum(1 for r in fields if r["verdict"] == "wrong"),
                    "files_read": f"{named - len(files_missing) - len(files_unread)}/{named}",
                    "studies_found": share(studies, lambda r: r["found"]),
                    "dissolution_found": share(dissolution, lambda r: r["found"]),
                    "key_entries_not_used": len(unused)},
    }


# ---- Markdown -------------------------------------------------------------------------------------------------------

def _cell(value: Any, limit: int = 0) -> str:
    """A table cell: no "|" or line break of the text breaks the row."""
    text = " ".join(str(value if value is not None else "").split()).replace("|", "/")
    return text[:limit] if limit else text


def _via(rows: list[str]) -> str:
    return f" (only through a link not confirmed: {', '.join(rows)})" if rows else ""


def _study_found(s: dict[str, Any]) -> str:
    if not s["found"]:
        return "**missing**" + _via(s["via_proposed_link"])
    return (f"found as {', '.join(s['as'])} ({s['points']} points)"
            + (", read and waiting for a person's answers" if s["waiting"] else ""))


def _dissolution_found(d: dict[str, Any]) -> str:
    if not d["found"]:
        return "**missing**" + _via(d["via_proposed_link"])
    return "found" + (", read and waiting for a person's answers" if d["waiting"] else "")


def _file_found(f: dict[str, Any]) -> str:
    bits = [f"{f[k]} {label}" for k, label in (("datasets", "datasets"), ("study_facts", "study facts"),
                                               ("dissolution_rows", "dissolution rows"), ("links", "links")) if f[k]]
    if f["sheets"]:
        bits.append(f"sheets saved {len(f['sheets_saved'])}/{len(f['sheets'])}")
        if f["sheets_waiting"]:
            bits.append(f"{len(f['sheets_waiting'])} waiting for a person")
    return ", ".join(bits) or "nothing proposed"


def _score_lines(scored: dict[str, Any]) -> list[str]:
    s = scored["summary"]
    lines = ["## Score against the key", "",
             f"- Map fields found: **{s['map_fields_found']}** ({s['map_fields_wrong']} wrong)",
             f"- Files read: **{s['files_read']}**",
             f"- Studies with a concentration-time profile: **{s['studies_found']}**",
             f"- Dissolution profiles (product × pH): **{s['dissolution_found']}**",
             f"- Key entries the score could not use: **{s['key_entries_not_used']}**", ""]
    if scored["unused"]:
        lines += ["### Key entries not used (check their spelling)", ""] + [f"- {u}" for u in scored["unused"]] + [""]
    off = [f for f in scored["fields"] if f["verdict"] != "found"]
    if off:
        lines += ["### Map fields not as the key says", "", "| file | sheet | field | key | found | quote |",
                  "|---|---|---|---|---|---|"]
        lines += [f"| {_cell(f['file'])} | {_cell(f['sheet'] or '')} | {_cell(f['field'])} | {_cell(f['expected'])} | "
                  f"{_cell(f['found'] if f['found'] is not None else '—')} ({f['verdict']}) | {_cell(f['quote'], 80)} |"
                  for f in off]
        lines.append("")
    if scored["files_missing"]:
        lines += ["### Files the key names that are not in the project", ""] + [f"- {n}" for n in scored["files_missing"]] + [""]
    if scored["files_unread"]:
        lines += ["### Files not read", ""] + [f"- {f['file']}: {f['state']} {f['note']}".rstrip()
                                               for f in scored["files_unread"]] + [""]
    lines += ["### Studies", ""] + [f"- {s['study']}: {_study_found(s)}" for s in scored["studies"]]
    if scored["unexpected_studies"]:
        lines.append(f"- found, not in the key: {', '.join(scored['unexpected_studies'])}")
    lines += ["", "### Dissolution", ""]
    lines += [f"- {d['product']} pH {d['ph'] if d['ph'] is not None else '(any)'}: {_dissolution_found(d)}"
              for d in scored["dissolution"]]
    return [*lines, ""]


def render(data: dict[str, Any], scored: dict[str, Any] | None = None) -> str:
    c = data["counts"]
    lines = [f"# Delivery report: project {data['project']}", "",
             (f"{c['files']} client files: {c['read']} read, {c['failed']} failed, {c['waiting']} waiting, "
              f"{c['never_queued']} not queued for the agent (code read them whole, or they need nothing); "
              f"{c['mapped']} mapped; {c['withdrawn']} withdrawn; {c['sheets_waiting']} sheets read and waiting for a "
              "person's answers."), ""]
    if scored:
        lines += _score_lines(scored)
    lines += ["## Each file", "", "| file | reading | found | map | refused (first) |", "|---|---|---|---|---|"]
    for f in sorted(data["files"], key=lambda f: f["file"]):
        r = f["reading"]
        if f["withdrawn"]:
            state = "withdrawn"
        elif r is None:
            state = "not queued"
        else:
            state = r["state"] + (f": {r['note']}" if r["state"] == "failed" else "")
        lines.append(f"| {_cell(f['file'])} | {_cell(state, 80)} | {_cell(_file_found(f))} | "
                     f"{_cell(f['map_line'] or ('looked at' if f['map_looked_at'] else '—'))} | "
                     f"{_cell(f['refused'][0] if f['refused'] else '', 80)} |")
    lines += ["", "## Sheets read and waiting for a person's answers", ""]
    lines += [f"- {f['file']} / {w['sheet']}: {w['kind']} {w['study_id']} ({w['points'] or 0} points); needs "
              f"{', '.join(w['needs']) or 'nothing'}" for f in data["files"] for w in f["sheets_waiting"]] or ["- none"]
    lines += ["", "## Studies with a concentration-time profile", ""]
    lines += [f"- {s['study']}: {s['datasets']} saved, {s['waiting']} waiting, {s['points']} points "
              f"({', '.join(s['states'])}; from {', '.join(s['sources'])})" for s in data["studies"]] or ["- none"]
    lines += ["", "## Dissolution profiles", ""]
    lines += [f"- {d['product']} {d['role']} pH {d['ph']} {d['medium']} {d['batch']}: {d['points']} times "
              f"({'saved' if d['saved'] else 'waiting for a person'}; {', '.join(d['files'])})"
              for d in data["dissolution"]] or ["- none"]
    lines += ["", "## Links between names (proposed; a person confirms them on Inputs)", ""]
    lines += [f"- {link['kind']}: {' = '.join(link['names'])} ({link['file']}: “{_cell(link['quote'], 80)}”)"
              for link in data["links"]] or ["- none"]
    lines += ["", "## Figures suggested for digitizing", ""]
    lines += [f"- {g['file']} p. {g['page']}: {g['kind']} {g['study_id'] or g['product']} (“{_cell(g['quote'], 80)}”)"
              for g in data["figures"]] or ["- none"]
    lines += ["", "## Delivery passes", ""]
    lines += [f"- {r['run_id'] or 'code'}: {r['status']}, {r['tried']} file(s), {r['facts']} facts, {r['links']} links, "
              f"{r['refused']} refused" for r in data["map_runs"]] or ["- none"]
    return "\n".join(lines) + "\n"


# ---- the command ------------------------------------------------------------------------------------------------------

def _plain(value: Any) -> Any:
    return sorted(value) if isinstance(value, set) else str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="What the agents made of a client's delivery (and its score).")
    parser.add_argument("--root", required=True, help="the project store root (on the server: ~/modeler-data/read-root)")
    parser.add_argument("--project", required=True, help="the project's id (in its address: /projects/<id>/…)")
    parser.add_argument("--tenant", help="the tenant (found from the project when left out)")
    parser.add_argument("--key", help="a person's reading of the delivery (YAML), to score against")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--out", help="write the report to this file instead of printing it")
    args = parser.parse_args(argv)
    root = Path(args.root).expanduser()
    if not args.root.strip() or not root.is_dir():
        print(f"no project store at {args.root!r}: give its folder (on the server, ~/modeler-data/read-root)", file=sys.stderr)
        return 2
    tenants = [args.tenant] if args.tenant else [t.name for t in root.iterdir() if (t / "projects" / args.project).is_dir()]
    if len(tenants) != 1:
        print(f"project {args.project} is {'in several tenants: give --tenant' if tenants else 'not in this store'}",
              file=sys.stderr)
        return 2
    try:
        key = load_key(Path(args.key).expanduser()) if args.key else None
    except (AnswerKeyError, yaml.YAMLError, OSError) as exc:
        print(f"the key {args.key}: {exc}", file=sys.stderr)
        return 2
    ws = Workspace(FileProjectStore(root), tenants[0], args.project)
    data = report(ws)
    scored = score(ws, data, key) if key is not None else None
    text = (json.dumps({"report": data, "score": scored}, indent=1, default=_plain, ensure_ascii=False) if args.json
            else render(data, scored))
    if args.out:
        Path(args.out).expanduser().write_text(text, encoding="utf-8")
        print(f"written to {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
